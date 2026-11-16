@echo off
setlocal
cd /d "%~dp0"
rem Updates the bot code from GitHub. Keeps .env, bot\candidate_private.py and data\ untouched.
set "URL=https://codeload.github.com/Polon-Lubvi/repository-1/zip/refs/heads/main"
set "TMPZ=%TEMP%\jobsbot_update.zip"
set "TMPD=%TEMP%\jobsbot_update"

echo [1/3] Downloading the latest version from GitHub...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing '%URL%' -OutFile '%TMPZ%'"
if errorlevel 1 goto :fail

echo [2/3] Unpacking...
if exist "%TMPD%" rmdir /s /q "%TMPD%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%TMPZ%' -DestinationPath '%TMPD%' -Force"
if errorlevel 1 goto :fail
set "SRC=%TMPD%\repository-1-main\graficheskiy-dizayner-bot"
if not exist "%SRC%\bot\main.py" goto :fail

echo [3/3] Updating files (your .env, resume and learned letters are kept)...
robocopy "%SRC%" "%CD%" /E /NFL /NDL /NJH /NJS /NP /XF .env candidate_private.py /XD data .venv >nul
if errorlevel 8 goto :fail
rmdir /s /q "%TMPD%" 2>nul
del "%TMPZ%" 2>nul

echo.
echo Done. Close the bot window if it is open and start run_bot.bat again.
pause
exit /b 0

:fail
echo.
echo Update failed - check the internet connection and try again.
pause
exit /b 1
