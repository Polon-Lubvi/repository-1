@echo off
REM ---------------------------------------------------------------------------
REM  TestQuest / Калькулятор смет — запуск автотестов (Windows)
REM
REM    set BASE_URL=https://testquest.pryaniky.com
REM    run-tests.bat
REM
REM  Зависимостей ставить не нужно. Запускается на Node.js 18+ (node tests\run)
REM  либо на Python 3.8+ (python tests\run.py) — берётся первый найденный.
REM  Итог: PASSED / FAILED и ERRORLEVEL (0 успех, 1 падения, 2 ошибка окружения).
REM ---------------------------------------------------------------------------
setlocal enableextensions
cd /d "%~dp0"

if "%BASE_URL%"=="" set "BASE_URL=https://testquest.pryaniky.com"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo == TestQuest QA - run-tests.bat ==
echo BASE_URL = %BASE_URL%

where node >nul 2>&1
if %ERRORLEVEL%==0 (
  for /f "delims=" %%v in ('node -v') do echo Runtime = Node %%v
  echo.
  node tests\run
  set "CODE=%ERRORLEVEL%"
  goto done
)

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY ( where py >nul 2>&1 && set "PY=py -3" )
if not defined PY (
  echo ERROR: neither Node.js 18+ nor Python 3.8+ found.
  echo RESULT: FAILED
  exit /b 2
)
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do echo Runtime = %%v
echo.
%PY% tests\run.py
set "CODE=%ERRORLEVEL%"

:done
echo.
if "%CODE%"=="0" (
  echo RESULT: PASSED ^(exit 0^)
) else (
  echo RESULT: FAILED ^(exit %CODE%^)
)
exit /b %CODE%
