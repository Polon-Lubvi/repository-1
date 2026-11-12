@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение...
    python -m venv .venv
)
.venv\Scripts\python -m pip install -q -r requirements.txt
if not exist ".env" (
    copy .env.example .env >nul
    echo Создан файл .env - впишите в него TELEGRAM_BOT_TOKEN и запустите снова.
    notepad .env
    pause
    exit /b
)
echo Бот запущен. Не закрывайте это окно.
.venv\Scripts\python -X utf8 -m bot.main
pause
