@echo off
chcp 65001 >nul
cd /d "%~dp0site"
set PORT=8906
echo.
echo   Сайт работает: http://localhost:%PORT%
echo   Чтобы остановить — закройте это окно.
echo.
start "" "http://localhost:%PORT%"
python -m http.server %PORT%
