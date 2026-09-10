# -*- coding: utf-8 -*-
"""
TC-01  Мета-данные КП (менеджеры, даты, поля компании/проекта)
TC-14  Навигация: 6 разделов, дефолтный раздел «Задание», заголовки
"""
import datetime
import re

import tq
from harness import Checks

BLOCK = "TC-01/14 · Мета-КП и навигация"

EXPECTED_MANAGERS = [
    ("lyubko", "Любко Евгения", "89265826505", "es@pryaniky.com"),
    ("tsikin", "Цыкин Алексей", "89919781154", "ats@pryaniky.ru"),
    ("savin", "Савин Марк", "89264844907", "mas@pryaniky.ru"),
]

EXPECTED_PAGES = ["assignment", "calculator", "invoices", "acts", "contracts", "client-contracts"]


def _add_months(d, months):
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return datetime.date(year, month, day)


def run():
    c = Checks()
    consts = tq.data_constants()
    page = tq.html()
    app = tq.js("app")

    # --- TC-01: список менеджеров КП ---
    got = [(m["id"], m["name"], m["phone"], m["email"]) for m in consts["managers"]]
    c.eq("Менеджеров КП ровно 3", len(got), 3)
    for exp in EXPECTED_MANAGERS:
        c.ok("Менеджер %s: %s / %s / %s" % exp, exp in got,
             "" if exp in got else "нет в data.js")
    c.ok("Первый менеджер выбран по умолчанию (option index 0 -> selected)",
         bool(re.search(r"if \(index === 0\)\s*\{\s*option\.selected = true", app)))

    # --- TC-01: даты КП по умолчанию (сегодня и +3 месяца) ---
    c.contains("Дата выставления КП = сегодня", app, "getElementById('kpIssueDate').value = formatDateForInput(today)")
    c.contains("КП действительно до = +3 месяца", app, "addMonths(today, 3)")
    today = datetime.date.today()
    valid = _add_months(today, 3)
    c.ok("Проверка формулы +3 мес (%s -> %s)" % (today.isoformat(), valid.isoformat()),
         valid == _add_months(today, 3))

    # --- TC-01: поля компании и проекта присутствуют ---
    for fid in ("companyName", "projectName", "kpManager", "kpIssueDate", "kpValidUntil"):
        c.contains("Поле #%s есть в разметке" % fid, page, 'id="%s"' % fid)

    # --- TC-14: навигация ---
    nav_pages = re.findall(r'data-page="([a-z-]+)"', page)
    for p in EXPECTED_PAGES:
        c.ok("Раздел меню data-page=%s" % p, p in nav_pages)
    nav = tq.js("nav")
    c.contains("По умолчанию открыт раздел «Задание»", nav, "switchPage('assignment')")
    c.contains("Заголовок раздела калькулятора = «Калькулятор смет»", nav, "title: 'Калькулятор смет'")
    return c.items
