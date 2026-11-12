"""Telegram-бот: ежедневная выгрузка вакансий, обучение по присланному Excel, управление сайтами.

Запуск:  python -m bot.main
"""
from __future__ import annotations

import asyncio
import functools
import html
import logging
import re
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from . import config, letters, pipeline, sources, storage

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

TZ = ZoneInfo(config.TIMEZONE)
RUN_LOCK = asyncio.Lock()

HELP = """<b>Бот вакансий для графического дизайнера</b>

Каждый день в <b>{time}</b> присылаю Excel со свежими вакансиями: кратко о вакансии, чем она интересна, ссылка, готовое сопроводительное письмо и пустая колонка для вашего варианта.

<b>Обучение</b>
Впишите свои письма в жёлтую колонку «Моё сопроводительное письмо», сохраните файл и просто отправьте его сюда. Я запомню ваш стиль и подниму похожие вакансии выше.

<b>Команды</b>
/now — собрать выгрузку прямо сейчас
/sites — список сайтов и каналов
/addsite ссылка [название] — добавить сайт или Telegram-канал
/removesite номер — убрать сайт из выгрузки
/enablesite номер — вернуть сайт
/settime ЧЧ:ММ — поменять время ежедневной выгрузки
/stats — статистика и чему я уже научилась
/stop — не присылать ежедневную выгрузку в этот чат
/id — показать ID чата (для настройки)"""


# ---------------------------------------------------------------- доступ
def allowed(update: Update) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    user = update.effective_user
    return bool(user and user.id in config.ALLOWED_USER_IDS)


def guarded(fn):
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not allowed(update):
            await update.effective_message.reply_text("Этот бот приватный.")
            return
        return await fn(update, context)
    return wrapper


def send_time() -> dtime:
    raw = storage.get_setting("send_time") or config.SEND_TIME
    h, m = (int(x) for x in raw.split(":"))
    return dtime(h, m, tzinfo=TZ)


def recipients() -> list[int]:
    return config.TELEGRAM_CHAT_IDS or storage.list_chats()


# ---------------------------------------------------------------- выгрузка
def _caption(vacs: list[dict], stats: dict) -> str:
    top = "\n".join(f"• {html.escape(v['title'][:70])} — {v['score']}/10" for v in vacs[:5])
    src = sum(1 for s in stats.values() if s["fit"])
    mode = "письма написал Claude" if letters.llm_enabled() else "письма по шаблону"
    cap = (f"<b>Вакансии на {datetime.now(TZ):%d.%m.%Y}</b>: {len(vacs)} шт. из {src} источников ({mode}).\n\n"
           f"Лучшие:\n{top}\n\nПоправьте письма в жёлтой колонке и пришлите файл обратно — я научусь.")
    return cap[:1024]


async def build_and_send(context: ContextTypes.DEFAULT_TYPE, chat_ids: list[int]) -> bool:
    """True — выгрузка собрана и разослана (или новых вакансий нет); False — сбой или уже идёт сбор."""
    if RUN_LOCK.locked():
        for cid in chat_ids:
            await context.bot.send_message(cid, "Выгрузка уже собирается, пришлю, как будет готово.")
        return False
    async with RUN_LOCK:
        try:
            path, vacs, stats = await asyncio.to_thread(pipeline.make_report)
        except Exception:
            log.exception("Сбор вакансий упал")
            for cid in chat_ids:
                await context.bot.send_message(cid, "Не получилось собрать вакансии — подробности в логе бота.")
            return False
        for cid in chat_ids:
            try:
                if not path:
                    await context.bot.send_message(cid, "Новых подходящих вакансий за сегодня не нашлось. Завтра проверю снова.")
                    continue
                with open(path, "rb") as f:
                    await context.bot.send_document(cid, document=f, filename=path.name,
                                                    caption=_caption(vacs, stats), parse_mode=ParseMode.HTML)
            except Exception:  # один недоступный чат (бот заблокирован и т.п.) не мешает остальным
                log.exception("Не удалось отправить выгрузку в чат %s", cid)
        return True


async def daily_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chats = recipients()
    if not chats:
        log.warning("Некому отправлять: задайте TELEGRAM_CHAT_ID или нажмите /start в боте")
        return
    if await build_and_send(context, chats):
        storage.set_setting("last_daily", datetime.now(TZ).date().isoformat())


def needs_catch_up(now: datetime | None = None) -> bool:
    """Бот запустили после времени выгрузки, а сегодняшняя ещё не уходила (компьютер был выключен)."""
    now = now or datetime.now(TZ)
    st = send_time()
    return (now.time() >= dtime(st.hour, st.minute)
            and storage.get_setting("last_daily") != now.date().isoformat()
            and bool(recipients()))


def schedule(app: Application) -> None:
    for job in app.job_queue.get_jobs_by_name("daily"):
        job.schedule_removal()
    # Если компьютер спал в 17:00 и проснулся позже — выгрузка всё равно уйдёт (в пределах 6 часов)
    app.job_queue.run_daily(daily_job, time=send_time(), name="daily",
                            job_kwargs={"misfire_grace_time": 6 * 3600, "coalesce": True})
    log.info("Ежедневная выгрузка в %s (%s)", send_time().strftime("%H:%M"), config.TIMEZONE)


# ---------------------------------------------------------------- команды
@guarded
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage.add_chat(update.effective_chat.id)
    await update.message.reply_text(HELP.format(time=send_time().strftime("%H:%M")), parse_mode=ParseMode.HTML)


@guarded
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage.remove_chat(update.effective_chat.id)
    await update.message.reply_text("Больше не присылаю сюда ежедневную выгрузку. Вернуть — /start")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"ID чата: {update.effective_chat.id}\nВаш ID: {u.id if u else '?'}")


@guarded
async def cmd_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage.add_chat(update.effective_chat.id)
    await update.message.reply_text("Собираю вакансии со всех сайтов — это займёт несколько минут…")
    await build_and_send(context, [update.effective_chat.id])


@guarded
async def cmd_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    for s in storage.list_sites():
        mark = "✅" if s["enabled"] else "⏸"
        lines.append(f"{mark} <b>{s['id']}</b>. {html.escape(s['name'])} — {html.escape(s['url'])}")
    await update.message.reply_text("<b>Сайты в выгрузке</b>\n" + "\n".join(lines) +
                                    "\n\n/addsite ссылка — добавить, /removesite номер — убрать",
                                    parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@guarded
async def cmd_addsite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Пришлите ссылку после команды, например:\n/addsite https://t.me/designhunters\n"
            "/addsite https://example.ru/jobs Название сайта\n\n"
            "Telegram-каналы (t.me/… или @канал) и сайты hh, Хабр Карьера, SuperJob и др. я разбираю точно, "
            "для остальных сайтов ищу на странице ссылки на дизайнерские вакансии.")
        return
    url = sources.normalize_url(context.args[0])
    kind = sources.detect_kind(url)
    if kind == "telegram":
        url = f"https://t.me/{sources.tg_channel_name(url)}"
    name = " ".join(context.args[1:]).strip() or (
        f"@{sources.tg_channel_name(url)} (TG)" if kind == "telegram" else re.sub(r"^https?://(www\.)?", "", url).split("/")[0])
    await update.message.reply_text(f"Проверяю {url} …")
    found, titles = await asyncio.to_thread(pipeline.test_site, {"name": name, "url": url, "kind": kind})
    site_id, created = storage.add_site(name, url, kind)
    verb = "Добавила" if created else "Уже был в списке — включила"
    if found:
        ex = "\n".join(f"• {html.escape(t[:80])}" for t in titles) or "—"
        msg = f"{verb}: <b>{site_id}. {html.escape(name)}</b>\nСейчас нашлось {found} объявлений, например:\n{ex}"
    else:
        msg = (f"{verb}: <b>{site_id}. {html.escape(name)}</b>\n⚠ Сейчас не нашла там дизайнерских вакансий. "
               "Возможно, сайт подгружает их скриптом или требует вход. Сайт оставлен в списке — "
               f"если в выгрузке от него ничего не будет, уберите его: /removesite {site_id}")
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, enabled: bool):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Укажите номер сайта из /sites, например: /removesite 5")
        return
    ok = storage.set_site_enabled(int(context.args[0]), enabled)
    await update.message.reply_text(("Включила" if enabled else "Убрала из выгрузки") + f" сайт №{context.args[0]}."
                                    if ok else "Нет сайта с таким номером, посмотрите /sites")


@guarded
async def cmd_removesite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, context, False)


@guarded
async def cmd_enablesite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle(update, context, True)


@guarded
async def cmd_settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (context.args or [""])[0])
    if not m:
        await update.message.reply_text("Формат: /settime 17:00")
        return
    storage.set_setting("send_time", f"{int(m.group(1)):02d}:{m.group(2)}")
    schedule(context.application)
    await update.message.reply_text(f"Готово: выгрузка каждый день в {send_time():%H:%M}.")


@guarded
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = storage.stats()
    notes = storage.get_setting("style_notes", "")
    text = (f"Сайтов в работе: {st['sites']}\nВакансий отправлено: {st['sent']}\n"
            f"Ваших писем для обучения: {st['examples']}\n"
            f"Режим писем: {'Claude API' if letters.llm_enabled() else 'шаблоны'}\n"
            f"Выгрузка: каждый день в {send_time():%H:%M}")
    if notes:
        text += "\n\n<b>Что я поняла о вашем стиле:</b>\n" + html.escape(notes[:2500])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


@guarded
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".xlsx"):
        await update.message.reply_text("Пришлите Excel-файл (.xlsx), который я присылала, с заполненной колонкой "
                                        "«Моё сопроводительное письмо».")
        return
    safe_name = re.sub(r"[^\w.-]", "_", doc.file_name)
    path = config.UPLOADS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{safe_name}"
    tg_file = await doc.get_file()
    await tg_file.download_to_drive(path)
    await update.message.reply_text("Читаю ваши письма…")
    try:
        res = await asyncio.to_thread(pipeline.learn_from_file, path)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    except Exception:
        log.exception("Ошибка обучения по файлу")
        await update.message.reply_text("Не смогла прочитать файл. Проверьте, что это выгрузка от бота.")
        return
    if not res["rows"]:
        await update.message.reply_text("В колонке «Моё сопроводительное письмо» пусто — нечему учиться. "
                                        "Впишите хотя бы одно письмо и пришлите файл снова.")
        return
    text = (f"Спасибо! Учла писем: {res['rows']} (новых {res['added']}, обновлено {res['updated']}). "
            f"Всего примеров: {res['total']}.\nСледующие черновики будут в вашем стиле, "
            "а похожие вакансии поднимутся выше.")
    if res["notes"]:
        text += "\n\n<b>Что я поняла о вашем стиле:</b>\n" + html.escape(res["notes"][:2500])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


@guarded
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if re.match(r"^(https?://|@|t\.me/)", t):
        await update.message.reply_text(f"Хотите добавить этот источник? Отправьте:\n/addsite {t.split()[0]}")
    else:
        await update.message.reply_text("Команды — /help. Чтобы обучить меня, пришлите Excel-выгрузку с вашими письмами.")


async def post_init(app: Application) -> None:
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("now", "Собрать выгрузку сейчас"),
        BotCommand("sites", "Список сайтов"),
        BotCommand("addsite", "Добавить сайт или канал"),
        BotCommand("removesite", "Убрать сайт"),
        BotCommand("settime", "Время ежедневной выгрузки"),
        BotCommand("stats", "Статистика и обучение"),
        BotCommand("stop", "Отписаться от рассылки"),
        BotCommand("help", "Помощь"),
    ])
    schedule(app)
    if needs_catch_up():
        log.info("Сегодняшняя выгрузка ещё не уходила — отправлю через минуту")
        app.job_queue.run_once(daily_job, when=60, name="catch_up")


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Не задан TELEGRAM_BOT_TOKEN — скопируйте .env.example в .env и впишите токен от @BotFather")
    storage.init()
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("sites", cmd_sites))
    app.add_handler(CommandHandler("addsite", cmd_addsite))
    app.add_handler(CommandHandler("removesite", cmd_removesite))
    app.add_handler(CommandHandler("enablesite", cmd_enablesite))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
