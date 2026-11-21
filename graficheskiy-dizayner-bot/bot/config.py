"""Настройки из .env и пути проекта."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "bot.sqlite3"
DEFAULT_SITES_FILE = ROOT / "config" / "sites.json"


def _ids(name: str) -> list[int]:
    raw = os.getenv(name, "")
    return [int(x) for x in raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()]


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_IDS = _ids("TELEGRAM_CHAT_ID")
ALLOWED_USER_IDS = _ids("ALLOWED_USER_IDS")
# Прокси для связи с Telegram, если api.telegram.org не открывается напрямую:
# http://host:port, socks5://user:pass@host:port и т.п.
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "").strip()
TELEGRAM_TIMEOUT = float(os.getenv("TELEGRAM_TIMEOUT", "60"))
SEND_TIME = os.getenv("SEND_TIME", "17:00").strip()
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow").strip()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip()

# Максимум вакансий в одной выгрузке; 0 — без ограничения (попадают все подходящие).
# Раньше настройка называлась MAX_VACANCIES (=40) — старое имя намеренно больше не читается,
# чтобы у тех, у кого оно осталось в .env, лимит снялся без ручной правки.
MAX_VACANCIES = int(os.getenv("VACANCY_LIMIT", "0") or 0)
FRESH_DAYS = int(os.getenv("FRESH_DAYS", "7"))
# Сколько вакансий с одного сайта читать подробно (открывать страницу); остальные отсекаются по заголовку
DETAIL_LIMIT_PER_SOURCE = int(os.getenv("DETAIL_LIMIT_PER_SOURCE", "60"))
