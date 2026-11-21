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


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>FL</title>
<item><title>Изготовление 3-х логотипов (Бюджет: 5000 &#8381;)</title><link>https://www.fl.ru/projects/1/logo.html</link>
<description>Нужно сделать три логотипа для кофейни в едином стиле, фирменные цвета, варианты для соцсетей. Бюджет: 5000 руб</description>
<pubDate>Mon, 16 Nov 2026 10:00:00 +0300</pubDate><category>Дизайн и Арт</category></item>
<item><title>Программирование / верстка Битрикс</title><link>https://www.fl.ru/projects/2/b.html</link>
<description>Битрикс</description><pubDate>Mon, 16 Nov 2026 10:00:00 +0300</pubDate></item>
<item><title>Написать статьи для блога</title><link>https://www.fl.ru/projects/3/t.html</link>
<description>Тексты</description><pubDate>Mon, 16 Nov 2026 10:00:00 +0300</pubDate></item>
</channel></rss>"""


def test_freelance_rss_parsing(monkeypatch):
    monkeypatch.setattr(sources, "get", lambda url, params=None, timeout=25: SimpleNamespace(content=RSS.encode(), text=RSS))
    items = sources.rss({"name": "FL.ru", "url": "https://www.fl.ru/rss/all.xml"})
    assert len(items) == 1
    v = items[0]
    assert v["title"] == "Изготовление 3-х логотипов" and v["project"] and v["published"].day == 16
    assert "5000" in v["salary"]
    v = scoring.score(v)
    assert not v["excluded"] and not any("зарплата" in w for w in v["warnings"])


def test_freelance_kwork_parsing(monkeypatch):
    import json as _json
    state = {"wantsListData": {"wants": [
        {"id": 1, "name": "Создание логотипа", "description": "Логотип для пекарни", "priceLimit": "1000.00",
         "date_create": "2026-11-17 19:32:42"},
        {"id": 2, "name": "Визуализация интерьера", "description": "3D", "priceLimit": "3000.00",
         "date_create": "2026-11-17 19:32:42"}]}}
    page = f"<script>window.stateData = {_json.dumps(state, ensure_ascii=False)};</script>"
    monkeypatch.setattr(sources, "get", lambda url, params=None, timeout=25: SimpleNamespace(text=page))
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    items = sources.kwork({"name": "Kwork", "url": "https://kwork.ru/projects"})
    assert [v["title"] for v in items] == ["Создание логотипа"]
    assert items[0]["url"] == "https://kwork.ru/projects/1/view" and items[0]["salary"] == "до 1 000 ₽"


def test_freelance_detect_kind_and_title_filter():
    assert sources.detect_kind("https://www.fl.ru/rss/all.xml") == "rss"
    assert sources.detect_kind("https://pchel.net/rss/") == "rss"
    assert sources.detect_kind("https://kwork.ru/projects?c=15") == "kwork"
    assert sources.detect_kind("https://illustrators.ru/jobs") == "illustrators"
    assert sources.title_ok("Нарисовать логотип для кофейни", project=True)
    assert not sources.title_ok("Нарисовать логотип для кофейни")      # как вакансия — не должность
    assert not sources.title_ok("Логистика и доставка", project=True)
    assert not sources.title_ok("Дизайн проект квартиры", project=True)


def test_tc11_date_in_text():
    assert sources.date_in_text("Опубликовано 13 февраля 2024. Обновлено 6 июля 2024").date().isoformat() == "2024-07-06"
    assert sources.date_in_text("Дата: 05.03.2025").date().isoformat() == "2025-03-05"
    assert sources.date_in_text("© 2026 Все права защищены") is None
    assert sources.date_in_text("Дедлайн 31 декабря 2099") is None  # будущие даты не считаем


def test_tc06_old_vacancy_without_listing_date_dropped(monkeypatch):
    """Случай remote-job: в поиске даты нет, на странице — «13 февраля 2024»."""
    old = vac(key="rj:old", url="https://remote-job.ru/vacancy/show/784147", published=None, description="")
    monkeypatch.setattr(sources, "collect_site", lambda site: [dict(old)])
    monkeypatch.setattr(sources, "fetch_detail", lambda url: {
        "title": "Графический дизайнер", "description": "Вакансия от 13 февраля 2024. Ищем дизайнера логотипов "
        "и айдентики на удалёнку, задачи по брендингу и упаковке.",
        "published": sources.date_in_text("13 февраля 2024")})
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    vs, _ = pipeline.collect(sites=[{"name": "rj", "url": "u", "kind": "remote_job"}])
    assert vs == []


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


DESC = ("Студия брендинга ищет графического дизайнера на удалённую работу. Задачи: разработка логотипов, "
        "фирменного стиля, брендбуков, упаковки и презентаций для клиентов из сферы образования и культуры. "
        "Требования: уверенное владение Figma, Illustrator, InDesign, портфолио с проектами айдентики, "
        "внимательность к деталям и соблюдение сроков. Условия: полная занятость, гибкий график, белая зарплата.")


def _collect_with(monkeypatch, per_site: dict[str, list[dict]]):
    monkeypatch.setattr(sources, "collect_site", lambda site: [dict(v) for v in per_site[site["name"]]])
    monkeypatch.setattr(sources, "enrich", lambda v: v)
    vs, stats = pipeline.collect(sites=[{"name": n, "url": n, "kind": "generic"} for n in per_site])
    return vs, stats


def test_tc06_dup_same_vacancy_on_two_sites(monkeypatch):
    hh = vac(key="hh:1", url="https://hh.ru/vacancy/1", company="Ромашка", description=DESC)
    trud = vac(key="trud:9", url="https://trudvsem.ru/v/9", company='ООО "Ромашка"',
               title="Графический дизайнер (удалённо)", description="Вакансия компании: " + DESC)
    vs, _ = _collect_with(monkeypatch, {"hh": [hh], "trud": [trud]})
    assert len(vs) == 1


def test_tc06_dup_across_days_by_content(monkeypatch):
    first = vac(key="rj:1", url="https://remote-job.ru/vacancy/show/1", company="", description=DESC)
    vs, _ = _collect_with(monkeypatch, {"rj": [first]})
    storage.save_sent(vs)
    repost = vac(key="rj:2", url="https://remote-job.ru/vacancy/show/2", company="", title="Дизайнер",
                 description=DESC + " Откликайтесь!")
    vs2, stats = _collect_with(monkeypatch, {"rj": [repost]})
    assert vs2 == [] and stats["rj"]["dup"] == 1


def test_tc06_dup_telegram_repost_in_two_channels(monkeypatch):
    a = vac(key="tg:a/1", url="https://t.me/a/1", company="", description=DESC)
    b = vac(key="tg:b/7", url="https://t.me/b/7", company="", description="#вакансия\n" + DESC)
    vs, _ = _collect_with(monkeypatch, {"a": [a], "b": [b]})
    assert len(vs) == 1


def test_tc06_different_vacancies_not_merged(monkeypatch):
    other = ("Издательство ищет верстальщика-дизайнера для подготовки журналов и каталогов к печати. "
             "Работа с InDesign, подготовка макетов, допечатная подготовка, взаимодействие с редакцией, "
             "контроль качества цветопробы и соблюдение графика выпуска номеров каждую неделю в офисе.")
    v1 = vac(key="x:1", url="https://x/1", company="", title="Графический дизайнер", description=DESC)
    v2 = vac(key="x:2", url="https://x/2", company="", title="Графический дизайнер", description=other)
    v3 = vac(key="x:3", url="https://x/3", company="Ромашка", title="Дизайнер упаковки", description="")
    v4 = vac(key="x:4", url="https://x/4", company="Ромашка", title="Дизайнер презентаций", description="")
    # одна компания, общий абзац «о компании», но разные должности (случай X5)
    v5 = vac(key="x:5", url="https://x/5", company="X5", title="Дизайнер упаковки", description=DESC)
    v6 = vac(key="x:6", url="https://x/6", company="X5", title="Дизайнер-верстальщик", description=DESC)
    vs, _ = _collect_with(monkeypatch, {"x": [v1, v2, v3, v4, v5, v6]})
    assert len(vs) == 6  # все шесть — разные вакансии
    titles = sorted(v["title"] for v in vs)
    assert "Дизайнер-верстальщик" in titles and titles.count("Дизайнер упаковки") == 2


def test_tc06_dedup_helpers():
    from bot import dedup
    assert dedup.norm_company('ООО «Ромашка»') == dedup.norm_company("Ромашка")
    assert dedup.norm_title("Графический дизайнер (удалённо)") == dedup.norm_title("Графический дизайнер")
    assert dedup.title_company_key("Дизайнер", "Company hidden") is None
    assert dedup.title_company_key("Дизайнер", "") is None


def test_no_limit_by_default(monkeypatch):
    monkeypatch.setattr(config, "MAX_VACANCIES", 0)
    many = [vac(key=f"k:{i}", url=f"https://e.com/{i}", company=f"Компания {i}",
                description=f"Вакансия номер {i}") for i in range(55)]
    vs, _ = _collect_with(monkeypatch, {"s": many})
    assert len(vs) == 55
    monkeypatch.setattr(config, "MAX_VACANCIES", 10)
    storage.init()
    vs, _ = _collect_with(monkeypatch, {"s2": [dict(v, key="z" + v["key"], url=v["url"] + "z",
                                                     company=v["company"] + "z") for v in many]})
    assert len(vs) == 10


def test_old_max_vacancies_setting_ignored(monkeypatch):
    import importlib
    monkeypatch.setenv("MAX_VACANCIES", "40")
    monkeypatch.delenv("VACANCY_LIMIT", raising=False)
    cfg = importlib.reload(config)
    try:
        assert cfg.MAX_VACANCIES == 0
    finally:
        monkeypatch.delenv("MAX_VACANCIES")
        importlib.reload(config)


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


def test_network_build_app_timeouts_and_proxy(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TEST")
    monkeypatch.setattr(config, "TELEGRAM_PROXY", "socks5://127.0.0.1:1080")
    app = main.build_app()
    req = app.bot._request[1]  # обычные запросы (0 — getUpdates)
    assert req._client_kwargs["timeout"].connect == config.TELEGRAM_TIMEOUT
    assert "1080" in str(req._client_kwargs.get("proxy") or req._client_kwargs.get("mounts"))
    assert len(app.handlers[0]) >= 11


def test_network_main_retries_instead_of_crashing(monkeypatch):
    from telegram.error import TimedOut
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TEST")
    monkeypatch.setattr("time.sleep", lambda s: None)
    reach = iter([False, True, True])
    monkeypatch.setattr(main, "telegram_reachable", lambda: next(reach))
    runs = []

    class FakeApp:
        def run_polling(self, **kw):
            runs.append(kw)
            if len(runs) == 1:
                raise TimedOut("Timed out")
    monkeypatch.setattr(main, "build_app", lambda: FakeApp())
    main.main()  # не должен упасть: недоступно → повтор, TimedOut → повтор, затем штатный выход
    assert len(runs) == 2 and runs[0]["bootstrap_retries"] == -1


def test_network_post_init_survives_menu_failure(monkeypatch):
    from telegram.error import TimedOut
    from telegram.ext import Application
    app = Application.builder().token("123:TEST").build()
    monkeypatch.setattr(type(app.bot), "set_my_commands", AsyncMock(side_effect=TimedOut("x")))
    run(main.post_init(app))
    assert app.job_queue.get_jobs_by_name("daily")


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
