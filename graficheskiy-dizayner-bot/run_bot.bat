@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.11+ from https://www.python.org/downloads/
    echo During install tick "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :fail
)

echo [2/3] Installing packages, please wait...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo File .env was created and opened in Notepad.
    echo Paste your bot token after TELEGRAM_BOT_TOKEN= , save the file,
    echo close Notepad and run run_bot.bat again.
    start "" notepad ".env"
    pause
    exit /b 0
)

findstr /r /c:"^TELEGRAM_BOT_TOKEN=..*" ".env" >nul
if errorlevel 1 (
    echo TELEGRAM_BOT_TOKEN is empty in .env - paste the token from @BotFather and run again.
    start "" notepad ".env"
    pause
    exit /b 1
)

echo [3/3] Bot is running. Do NOT close this window. Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" -X utf8 -m bot.main
echo.
echo Bot stopped.
pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
