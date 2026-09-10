#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# TestQuest / Калькулятор смет — запуск автотестов (Linux / macOS)
#
#   BASE_URL=https://testquest.pryaniky.com ./run-tests.sh
#
# Зависимостей ставить не нужно. Набор запускается на любом из рантаймов
# (используется первый найденный, только стандартная библиотека рантайма):
#   * Node.js 18+  ->  node tests/run       (файл без расширения, CommonJS)
#   * Python 3.8+  ->  python tests/run.py
#
# Итог: строка PASSED / FAILED и код выхода (0 успех, 1 падения, 2 ошибка окружения).
# ---------------------------------------------------------------------------
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo .)"
cd "$SCRIPT_DIR" || exit 2

export BASE_URL="${BASE_URL:-https://testquest.pryaniky.com}"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "== TestQuest QA · run-tests.sh =="
echo "BASE_URL = $BASE_URL"

CODE=""

# --- 1. Node.js 18+ ---
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  if [ "${NODE_MAJOR:-0}" -ge 18 ]; then
    echo "Runtime = Node $(node -v)"
    echo
    node tests/run
    CODE=$?
  fi
fi

# --- 2. Python 3.8+ (если Node не подошёл) ---
if [ -z "$CODE" ]; then
  PY=""
  for cand in "${PYTHON:-}" python3 python py /usr/bin/python3 /usr/local/bin/python3; do
    [ -n "$cand" ] || continue
    if { command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; } &&
       "$cand" -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,8) else 1)' >/dev/null 2>&1; then
      PY="$cand"; break
    fi
  done
  if [ -n "$PY" ]; then
    echo "Runtime = $("$PY" --version 2>&1)"
    echo
    "$PY" tests/run.py
    CODE=$?
  fi
fi

# --- 3. рантайм не найден ---
if [ -z "$CODE" ]; then
  echo "ОШИБКА: не найден ни Node.js 18+, ни Python 3.8+."
  echo "  PATH=$PATH"
  for t in node python3 python perl awk curl wget; do
    echo "  $t : $(command -v "$t" 2>&1 || echo '(нет)')"
  done
  echo "RESULT: FAILED (exit 2)"
  exit 2
fi

echo
if [ "$CODE" -eq 0 ]; then
  echo "RESULT: PASSED (exit 0)"
else
  echo "RESULT: FAILED (exit $CODE)"
fi
exit "$CODE"
