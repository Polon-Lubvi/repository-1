"""Автотесты бота (без сети и без Telegram). Запуск: .venv\\Scripts\\python -m pytest -q tests
Номера TC — из tests/TEST_PLAN.md."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from openpyxl import load_workbook

from bot import config, excel_io, letters, pipeline, scoring, sources, storage

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ окружение
@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Своя база и папки на каждый тест, без ключа Claude."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.sqlite3")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", [])
    monkeypatch.setattr(config, "TELEGRAM_CHAT_IDS", [])
    storage.init()
    yield


def vac(**kw):
    base = dict(title="Графический дизайнер", company="Студия", description="Разработка айдентики и логотипов, "
                "фирменный стиль, брендбуки. Удалённая работа.", work_format="удалённо", location="Москва",
                salary="от 70 000 ₽", source="test", url="https://example.com/v/1", published=datetime.now(sources.MSK))
    base.update(kw)
    return sources.new_vac(**base)


# ------------------------------------------------------------------ TC-07 фильтры и оценка
@pytest.mark.parametrize("title", ["Дизайнер карточек для маркетплейсов", "UX/UI дизайнер", "Бренд-менеджер",
                                   "Дизайнер интерьера", "Product Designer", "Менеджер по продажам"])
def test_tc07_excluded_titles(title):
    v = scoring.score(vac(title=title))
    assert v["excluded"], title


def test_tc07_office_outside_rostov_excluded():
    v = scoring.score(vac(work_format="", location="Екатеринбург", description="Офис в центре города, дизайн"))
    assert "не в Ростове" in v["excluded"]


def test_tc07_rostov_hybrid_and_remote_pass():
    assert not scoring.score(vac(work_format="гибрид", location="Ростов-на-Дону"))["excluded"]
    assert not scoring.score(vac())["excluded"]


def test_tc07_scores_order_interest_senior_salary():
    good = scoring.score(vac())["score"]
    senior = scoring.score(vac(title="Senior графический дизайнер"))["score"]
    cheap = scoring.score(vac(salary="до 30 000 ₽"))["score"]
    market = scoring.score(vac(description="Оформление карточек товаров для Wildberries и Ozon"))
    assert good > senior and good > cheap and good > market["score"]
    assert any("маркетплейс" in w for w in market["warnings"])
    assert 0 <= good <= 10


def test_tc07_currency_conversion():
    assert max(scoring._salary_numbers("100 000–120 000 KZT")) < 60000
    assert max(scoring._salary_numbers("500-700$/мес.")) >= 45000
    assert scoring._salary_numbers("от 120 000 до 210 000 руб.") == [120000, 210000]


# ------------------------------------------------------------------ TC-11 разбор данных
def test_tc11_parsers():
    assert sources.parse_ru_date("9 ноября 2026").date().isoformat() == "2026-11-09"
    assert sources.parse_ru_date("сегодня").date() == datetime.now(sources.MSK).date()
    assert sources.parse_date("2026-11-03T11:23:31+03:00").day == 3
    assert sources.fmt_salary(60000, 90000, "RUR") == "60 000–90 000 ₽"
    assert sources.fmt_salary(None, None) == ""
    assert sources.normalize_url("@designhunters") == "https://t.me/designhunters"
    assert sources.tg_channel_name("https://t.me/s/fordesigner") == "fordesigner"
    assert sources.detect_kind("https://www.hh.ru/x") == "hh"
    assert sources.detect_kind("https://rostov.superjob.ru") == "superjob"
    assert sources.detect_kind("https://example.org/jobs") == "generic"
    assert sources.title_ok("Графический дизайнер") and not sources.title_ok("Бухгалтер")


def test_tc11_main_text_skips_link_lists():
    from bs4 import BeautifulSoup
    html = ("<body><ul>" + "".join(f"<li><a href='/v/{i}'>Другая вакансия дизайнера номер {i}</a></li>" for i in range(30))
            + "</ul><div class='d'><p>Мы ищем графического дизайнера для разработки айдентики.</p>"
              "<p>Задачи: логотипы, брендбуки, упаковка и презентации для клиентов.</p></div></body>")
    text = sources.main_text(BeautifulSoup(html, "html.parser"))
    assert "айдентики" in text and "Другая вакансия" not in text


def test_tc11_telegram_post_parsing(monkeypatch):
    now = datetime.now(sources.MSK).isoformat()
    page = f"""<div class="tgme_widget_message" data-post="chan/10"><div class="tgme_widget_message_text">
      #вакансия<br>Графический дизайнер в студию<br>Удалённо. Зарплата: от 80 000 ₽<br>Компания: Студия Альфа</div>
      <time datetime="{now}"></time></div>
      <div class="tgme_widget_message" data-post="chan/11"><div class="tgme_widget_message_text">Просто новости канала</div>
      <time datetime="{now}"></time></div>"""
    calls = []

    def fake_get(url, params=None, timeout=25):
        calls.append(url)
        return SimpleNamespace(text=page if len(calls) == 1 else "")
    monkeypatch.setattr(sources, "get", fake_get)
    items = sources.telegram({"name": "TG", "url": "https://t.me/chan"})
    assert len(items) == 1
    v = items[0]
    assert v["url"] == "https://t.me/chan/10" and v["work_format"] == "удалённо"
    assert v["company"] == "Студия Альфа" and "80 000" in v["salary"]


# ------------------------------------------------------------------ TC-01 Excel
def test_tc01_excel_structure(tmp_path):
    vs = [scoring.score(vac(url=f"https://e.com/{i}", title=f"Графический дизайнер {i}")) for i in range(3)]
    letters.fill_texts(vs)
    path = excel_io.build(vs, tmp_path / "r.xlsx")
    ws = load_workbook(path)["Вакансии"]
    head = [c.value for c in ws[1]]
    assert len(head) == 13
    assert head[-2] == excel_io.COL_BOT_LETTER and head[-1] == excel_io.COL_USER_LETTER
    assert head.index("Ссылка") < head.index(excel_io.COL_BOT_LETTER)
    row = list(ws.iter_rows(min_row=2, max_row=2))[0]
    assert row[-1].value in (None, "") and row[-1].fill.fgColor.rgb.endswith("FFF6D6")
    assert row[-2].value and "Здравствуйте" in row[-2].value
    assert row[10].hyperlink.target == "https://e.com/0"
    assert all(ws.cell(row=r, column=9).value for r in range(2, 5))  # кратко
    assert all(ws.cell(row=r, column=10).value for r in range(2, 5))  # чем интересна


# ------------------------------------------------------------------ TC-02/03 обучение
def _report_with_letter(tmp_path, letter: str | None):
    v = scoring.score(vac())
    letters.fill_texts([v])
    storage.save_sent([v])
    path = excel_io.build([v], tmp_path / "fb.xlsx")
    wb = load_workbook(path)
    if letter is not None:
        wb["Вакансии"].cell(row=2, column=13).value = letter
    wb.save(path)
    return path, v


def test_tc02_learning_roundtrip(tmp_path):
    my = "Добрый день! Увидела вашу вакансию и хочу помочь с айдентикой. С уважением, Татьяна."
    path, v = _report_with_letter(tmp_path, my)
    res = pipeline.learn_from_file(path)
    assert res["rows"] == 1 and res["added"] == 1
    ex = storage.list_examples()[0]
    assert ex["user_letter"] == my and ex["vacancy_url"] == v["url"]
    assert "identity" in ex["keywords"]
    # повторная отправка того же файла — обновление, не дубль
    assert pipeline.learn_from_file(path)["updated"] == 1 and storage.stats()["examples"] == 1


def test_tc02_empty_and_foreign_files(tmp_path):
    path, _ = _report_with_letter(tmp_path, None)
    assert pipeline.learn_from_file(path)["rows"] == 0
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["a", "b"])
    wb.save(tmp_path / "foreign.xlsx")
    with pytest.raises(ValueError):
        pipeline.learn_from_file(tmp_path / "foreign.xlsx")


def test_tc03_learning_changes_next_letter_and_score(tmp_path):
    my = "Добрый день! Мой особый стиль письма про «Графический дизайнер» в Студия. Татьяна."
    path, _ = _report_with_letter(tmp_path, my)
    before = scoring.score(vac(title="Дизайнер айдентики", url="https://e.com/2"), scoring.learned_bonus())["score"]
    pipeline.learn_from_file(path)
    new = scoring.score(vac(title="Дизайнер айдентики", company="Новая", url="https://e.com/2"), scoring.learned_bonus())
    assert new["score"] >= before
    letter = letters.template_letter(new)
    assert "особый стиль" in letter and "«Дизайнер айдентики»" in letter and "Новая" in letter


# ------------------------------------------------------------------ TC-12 Claude недоступен
def test_tc12_llm_failure_falls_back(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(letters, "llm_generate", MagicMock(side_effect=RuntimeError("API down")))
    v = scoring.score(vac())
    letters.fill_texts([v])
    assert "Здравствуйте" in v["letter"] and v["summary"] and v["why"]


# ------------------------------------------------------------------ TC-06 без повторов
def test_tc06_no_repeats(monkeypatch):
    items = [vac(url="https://e.com/a", key="k:a"), vac(url="https://e.com/b", key="k:b", title="Дизайнер упаковки")]
    monkeypatch.setattr(sources, "collect_site", lambda site: [dict(i) for i in items])
    monkeypatch.setattr(sources, "enrich", lambda v: v)
    site = {"name": "s", "url": "u", "kind": "generic"}
    first, _ = pipeline.collect(sites=[site])
    assert len(first) == 2
    storage.save_sent(first[:1])
    second, _ = pipeline.collect(sites=[site])
    assert [v["key"] for v in second] == [first[1]["key"]]
    storage.save_sent(second)
    assert pipeline.collect(sites=[site])[0] == []


def test_tc06_old_vacancies_skipped(monkeypatch):
    old = vac(url="https://e.com/old", key="k:old", published=datetime.now(sources.MSK) - timedelta(days=30))
    monkeypatch.setattr(sources, "collect_site", lambda site: [old])
    monkeypatch.setattr(sources, "enrich", lambda v: v)
    vs, _ = pipeline.collect(sites=[{"name": "s", "url": "u", "kind": "generic"}])
    assert vs == []


# ------------------------------------------------------------------ Telegram-команды (TC-04/05/08/09/10)
from bot import main  # noqa: E402  (после фикстур config)


def make_update(user_id=1, chat_id=100, text="", document=None):
    msg = SimpleNamespace(reply_text=AsyncMock(), text=text, document=document)
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id), effective_chat=SimpleNamespace(id=chat_id),
                           effective_message=msg, message=msg)


def make_ctx(args=None, app=None):
    bot = SimpleNamespace(send_message=AsyncMock(), send_document=AsyncMock())
    return SimpleNamespace(args=args or [], bot=bot, application=app)


def replies(update):
    return " ".join(str(c.args[0]) for c in update.message.reply_text.call_args_list)


def run(coro):
    return asyncio.run(coro)


def test_tc05_access_control(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", [42])
    u = make_update(user_id=7)
    run(main.cmd_stats(u, make_ctx()))
    assert "приватный" in replies(u)
    u = make_update(user_id=7)
    run(main.cmd_id(u, make_ctx()))
    assert "Ваш ID: 7" in replies(u)
    u = make_update(user_id=42)
    run(main.cmd_stats(u, make_ctx()))
    assert "Сайтов в работе" in replies(u)


def test_tc05_start_registers_chat():
    run(main.cmd_start(make_update(chat_id=555), make_ctx()))
    assert 555 in storage.list_chats() and main.recipients() == [555]


def test_tc04_schedule_and_settime():
    from telegram.ext import Application
    app = Application.builder().token("123:TEST").build()
    main.schedule(app)
    jobs = app.job_queue.get_jobs_by_name("daily")
    assert len(jobs) == 1
    assert main.send_time().strftime("%H:%M") == config.SEND_TIME and str(main.send_time().tzinfo) == config.TIMEZONE
    u = make_update()
    run(main.cmd_settime(u, make_ctx(["18:30"], app)))
    assert main.send_time().strftime("%H:%M") == "18:30" and "18:30" in replies(u)
    for bad in (["25:00"], ["abc"], []):
        u = make_update()
        run(main.cmd_settime(u, make_ctx(bad, app)))
        assert "Формат" in replies(u)
    assert main.send_time().strftime("%H:%M") == "18:30"


def test_tc08_sites_commands(monkeypatch):
    monkeypatch.setattr(pipeline, "test_site", lambda s: (3, ["Графический дизайнер", "Дизайнер упаковки"]))
    u = make_update()
    run(main.cmd_addsite(u, make_ctx(["@new_design_jobs"])))
    site = [s for s in storage.list_sites() if s["url"] == "https://t.me/new_design_jobs"][0]
    assert site["kind"] == "telegram" and "Добавила" in replies(u)
    u = make_update()
    run(main.cmd_addsite(u, make_ctx(["example.org/jobs", "Мой", "сайт"])))
    s2 = [s for s in storage.list_sites() if s["url"] == "https://example.org/jobs"][0]
    assert s2["kind"] == "generic" and s2["name"] == "Мой сайт"
    u = make_update()
    run(main.cmd_removesite(u, make_ctx([str(site["id"])])))
    assert "Убрала" in replies(u) and not [s for s in storage.list_sites(True) if s["id"] == site["id"]]
    u = make_update()
    run(main.cmd_enablesite(u, make_ctx([str(site["id"])])))
    assert [s for s in storage.list_sites(True) if s["id"] == site["id"]]
    for args in ([], ["abc"], ["99999"]):
        u = make_update()
        run(main.cmd_removesite(u, make_ctx(args)))
        assert "номер" in replies(u).lower()
    u = make_update()
    run(main.cmd_addsite(u, make_ctx([])))
    assert "Пришлите ссылку" in replies(u)
    u = make_update()
    run(main.cmd_sites(u, make_ctx()))
    assert "hh.ru" in replies(u)


def test_tc08_addsite_empty_site_warns(monkeypatch):
    monkeypatch.setattr(pipeline, "test_site", lambda s: (0, []))
    u = make_update()
    run(main.cmd_addsite(u, make_ctx(["https://empty.example.com"])))
    assert "не нашла" in replies(u)


def test_tc09_build_and_send(monkeypatch, tmp_path):
    f = tmp_path / "x.xlsx"
    f.write_bytes(b"x")
    vs = [dict(scoring.score(vac()), title="Дизайнер " + "очень длинное название " * 5) for _ in range(5)]
    monkeypatch.setattr(pipeline, "make_report", lambda: (f, vs, {"s": {"fit": 5}}))
    ctx = make_ctx()
    run(main.build_and_send(ctx, [1, 2]))
    assert ctx.bot.send_document.await_count == 2
    cap = ctx.bot.send_document.call_args.kwargs["caption"]
    assert len(cap) <= 1024 and "Лучшие" in cap
    # нет вакансий
    monkeypatch.setattr(pipeline, "make_report", lambda: (None, [], {}))
    ctx = make_ctx()
    run(main.build_and_send(ctx, [1]))
    assert "не нашлось" in ctx.bot.send_message.call_args.args[1]
    # сбой сбора
    monkeypatch.setattr(pipeline, "make_report", MagicMock(side_effect=RuntimeError("boom")))
    ctx = make_ctx()
    run(main.build_and_send(ctx, [1]))
    assert "Не получилось" in ctx.bot.send_message.call_args.args[1]


def test_tc09_concurrent_now(monkeypatch, tmp_path):
    import time
    f = tmp_path / "x.xlsx"
    f.write_bytes(b"x")

    def slow():
        time.sleep(0.5)
        return f, [scoring.score(vac())], {}
    monkeypatch.setattr(pipeline, "make_report", slow)
    main.RUN_LOCK = asyncio.Lock()

    async def both():
        c1, c2 = make_ctx(), make_ctx()
        t = asyncio.create_task(main.build_and_send(c1, [1]))
        await asyncio.sleep(0.05)
        await main.build_and_send(c2, [2])
        await t
        return c1, c2
    c1, c2 = run(both())
    assert c1.bot.send_document.await_count == 1
    assert "уже собирается" in c2.bot.send_message.call_args.args[1]


def test_tc04_misfire_grace_after_sleep():
    from telegram.ext import Application
    app = Application.builder().token("123:TEST").build()
    main.schedule(app)
    job = app.job_queue.get_jobs_by_name("daily")[0]
    assert job.job.misfire_grace_time >= 3600 and job.job.coalesce


def test_tc04_catch_up_after_late_start(monkeypatch):
    late = datetime.now(main.TZ).replace(hour=19, minute=0)
    early = late.replace(hour=9)
    assert not main.needs_catch_up(late)          # нет получателей
    storage.add_chat(100)
    assert main.needs_catch_up(late) and not main.needs_catch_up(early)
    storage.set_setting("last_daily", late.date().isoformat())
    assert not main.needs_catch_up(late)          # сегодня уже отправляли


def test_tc04_daily_job_marks_day_and_survives_blocked_chat(monkeypatch, tmp_path):
    f = tmp_path / "x.xlsx"
    f.write_bytes(b"x")
    monkeypatch.setattr(pipeline, "make_report", lambda: (f, [scoring.score(vac())], {}))
    storage.add_chat(1)
    storage.add_chat(2)
    ctx = make_ctx()
    ctx.bot.send_document = AsyncMock(side_effect=[RuntimeError("bot blocked"), None])
    run(main.daily_job(ctx))
    assert ctx.bot.send_document.await_count == 2
    assert storage.get_setting("last_daily") == datetime.now(main.TZ).date().isoformat()


def test_stop_unsubscribes():
    run(main.cmd_start(make_update(chat_id=777), make_ctx()))
    u = make_update(chat_id=777)
    run(main.cmd_stop(u, make_ctx()))
    assert 777 not in storage.list_chats() and "/start" in replies(u)


def test_tc09_daily_job_without_recipients(monkeypatch):
    called = MagicMock()
    monkeypatch.setattr(main, "build_and_send", AsyncMock(side_effect=called))
    run(main.daily_job(make_ctx()))
    called.assert_not_called()


def test_tc10_document_handler(monkeypatch, tmp_path):
    u = make_update(document=SimpleNamespace(file_name="photo.png"))
    run(main.on_document(u, make_ctx()))
    assert "Excel" in replies(u)
    path, _ = _report_with_letter(tmp_path, "Добрый день! Мой вариант письма для этой вакансии. Татьяна.")

    async def download(dst):
        Path(dst).write_bytes(path.read_bytes())
    doc = SimpleNamespace(file_name="Вакансии 12.11.xlsx",
                          get_file=AsyncMock(return_value=SimpleNamespace(download_to_drive=download)))
    u = make_update(document=doc)
    run(main.on_document(u, make_ctx()))
    assert "Учла писем: 1" in replies(u)


# ------------------------------------------------------------------ TC-13 run_bot.bat
def test_tc13_bat_is_ascii_crlf():
    raw = (ROOT / "run_bot.bat").read_bytes()
    raw.decode("ascii")
    assert b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")
    assert b"bot.main" in raw and b"requirements.txt" in raw


def test_privacy_no_personal_data_in_tracked_code():
    """Личные данные — только в candidate_private.py (он в .gitignore)."""
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "bot/candidate_private.py" in gi and ".env" in gi
    priv = ROOT / "bot" / "candidate_private.py"
    if not priv.exists():
        pytest.skip("нет candidate_private.py")
    ns: dict = {}
    exec(priv.read_text(encoding="utf-8"), ns)
    secret_bits = [x.strip() for x in ns["CONTACTS"].split("·")]
    for f in list((ROOT / "bot").glob("*.py")) + [ROOT / "README.md", ROOT / "config" / "sites.json"]:
        if f.name == "candidate_private.py":
            continue
        text = f.read_text(encoding="utf-8")
        for bit in secret_bits:
            assert bit.split(":")[-1].strip() not in text, f.name
