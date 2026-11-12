"""Собирает архив для переноса бота на другой компьютер.

    .venv\\Scripts\\python tools\\make_transfer_zip.py [путь_к_архиву.zip]

В архив попадает всё, что нужно для работы (код, настройки, .env с токеном, резюме,
база обучения), и не попадает то, что привязано к этому компьютеру (.venv, автопуш на GitHub).
В архиве токен бота и контакты соискателя — передавайте его лично, не выкладывайте в общий доступ.
"""
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = Path.home() / "Desktop" / f"bot_vakansii_{datetime.now():%Y-%m-%d}.zip"

INCLUDE_DIRS = ["bot", "config"]
INCLUDE_FILES = [".env", ".env.example", "requirements.txt", "run_bot.bat", "README.md",
                 "КАК_ЗАПУСТИТЬ.txt", "data/bot.sqlite3"]
SKIP_PARTS = {"__pycache__"}


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    out.parent.mkdir(parents=True, exist_ok=True)
    missing = [f for f in (".env", "bot/candidate_private.py") if not (ROOT / f).exists()]
    if missing:
        sys.exit(f"Нет файлов {missing} — без них бот на новом компьютере не заработает.")
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d in INCLUDE_DIRS:
            for p in sorted((ROOT / d).rglob("*")):
                if p.is_file() and not SKIP_PARTS & set(p.parts) and p.suffix != ".pyc":
                    z.write(p, p.relative_to(ROOT).as_posix())
                    count += 1
        for f in INCLUDE_FILES:
            p = ROOT / f
            if p.exists():
                z.write(p, f)
                count += 1
    print(f"Готово: {out}  ({count} файлов, {out.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()
