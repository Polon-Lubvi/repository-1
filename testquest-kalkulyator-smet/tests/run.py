#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Оркестратор прогона тестов калькулятора смет TestQuest.

Запуск:
    BASE_URL=https://testquest.pryaniky.com python3 tests/run.py

Что делает:
  * по очереди выполняет блоки тестов (tests/test_*.py),
  * печатает результат по каждому блоку и каждой проверке,
  * печатает финальный итог PASSED / FAILED,
  * код выхода: 0 если всё зелёное, 1 если есть падения, 2 при сетевой/иной ошибке.
"""

import importlib.util
import io
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

# Гарантируем UTF-8 вывод (Windows-консоль по умолчанию cp1251).
for stream_name in ("stdout", "stderr"):
    stream = getattr(sys, stream_name)
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        setattr(sys, stream_name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))

import tq  # noqa: E402

# Порядок блоков = порядок кейсов в TESTCASES.md
BLOCK_FILES = [
    "test_meta_and_nav.py",
    "test_tariffs.py",
    "test_licenses_term.py",
    "test_modules.py",
    "test_implementation_tm.py",
    "test_totals.py",
    "test_excel_export.py",
    "test_validation.py",
    "test_dom_contract.py",
]

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"
if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
    GREEN = RED = YELLOW = BOLD = RESET = ""

TICK = "PASS"
CROSS = "FAIL"


def load_block(filename):
    path = os.path.join(HERE, filename)
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    print("%s== TestQuest / Калькулятор смет — прогон автотестов ==%s" % (BOLD, RESET))
    print("BASE_URL = %s" % tq.BASE_URL)

    # быстрый sanity-check доступности стенда
    try:
        tq.html()
        tq.js("data")
    except Exception as exc:  # noqa: BLE001
        print("%sНЕ УДАЛОСЬ ОБРАТИТЬСЯ К СТЕНДУ:%s %s" % (RED, RESET, exc))
        print("\nИТОГ: %sFAILED%s (стенд недоступен, код выхода 2)" % (RED, RESET))
        return 2

    started = time.time()
    total_ok = 0
    total_fail = 0
    block_summary = []

    for filename in BLOCK_FILES:
        try:
            mod = load_block(filename)
            block_name = getattr(mod, "BLOCK", filename)
            checks = mod.run()
        except Exception:  # noqa: BLE001
            block_name = filename
            print("\n%s### %s%s" % (BOLD, block_name, RESET))
            traceback.print_exc()
            total_fail += 1
            block_summary.append((block_name, 0, 1))
            continue

        b_ok = sum(1 for c in checks if c["ok"])
        b_fail = sum(1 for c in checks if not c["ok"])
        total_ok += b_ok
        total_fail += b_fail
        block_summary.append((block_name, b_ok, b_fail))

        status = "%sOK%s" % (GREEN, RESET) if b_fail == 0 else "%sПАДЕНИЕ%s" % (RED, RESET)
        print("\n%s### %s%s  [%s]  (%d/%d)" % (BOLD, block_name, RESET, status, b_ok, b_ok + b_fail))
        for c in checks:
            mark = "%s%s%s" % (GREEN, TICK, RESET) if c["ok"] else "%s%s%s" % (RED, CROSS, RESET)
            line = "  %s  %s" % (mark, c["name"])
            if c.get("info"):
                line += "  — %s" % c["info"]
            print(line)

    elapsed = time.time() - started
    print("\n%s== Итоги по блокам ==%s" % (BOLD, RESET))
    for name, ok, fail in block_summary:
        tag = "%sOK    %s" % (GREEN, RESET) if fail == 0 else "%sFAILED%s" % (RED, RESET)
        print("  %s  %-42s %d pass / %d fail" % (tag, name, ok, fail))

    verdict = "PASSED" if total_fail == 0 else "FAILED"
    color = GREEN if total_fail == 0 else RED
    print(
        "\n%s%sИТОГ: %s%s  —  %d проверок, %d успешно, %d провалено, %.1f c"
        % (BOLD, color, verdict, RESET, total_ok + total_fail, total_ok, total_fail, elapsed)
    )
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(2)
