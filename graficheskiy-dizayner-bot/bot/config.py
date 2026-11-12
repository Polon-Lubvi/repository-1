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
SEND_TIME = os.getenv("SEND_TIME", "17:00").strip()
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow").strip()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip()

MAX_VACANCIES = int(os.getenv("MAX_VACANCIES", "40"))
FRESH_DAYS = int(os.getenv("FRESH_DAYS", "7"))
# Сколько страниц вакансий на сайт открывать для чтения описания
DETAIL_LIMIT_PER_SOURCE = int(os.getenv("DETAIL_LIMIT_PER_SOURCE", "20"))
