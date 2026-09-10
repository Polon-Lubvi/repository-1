# -*- coding: utf-8 -*-
"""
TC-02  Тариф «TestQuest Облако (SAAS)» — базовый расчёт лицензий
TC-03  Тариф «TestQuest Коробка (on-premise)» — модель «Магистры»
       (срок в расчёте всегда 24 мес, тех.поддержка 30%/год со 2-го года)
"""
import tq
from harness import Checks

BLOCK = "TC-02/03 · Тарифы Облако / Коробка"


def run():
    c = Checks()
    page = tq.html()
    calc_src = tq.js("calc")

    # разметка: два чекбокса тарифа
    c.contains("Чекбокс тарифа «Облако» (#tariff-cloud)", page, 'id="tariff-cloud"')
    c.contains("Чекбокс тарифа «Коробка» (#tariff-onprem)", page, 'id="tariff-onprem"')

    # --- TC-02: Облако, 100 лицензий / 12 мес / без модулей ---
    c.eq("Облако 100 лиц · 12 мес = 200 429 ₽",
         tq.calc_licenses(tq.TARIFF_CLOUD, 100, 12), 200429.0)
    c.eq("Облако 100 лиц · 12 мес форматируется как '200 429 ₽'",
         tq.norm_ws(tq.format_currency_rub(tq.calc_licenses(tq.TARIFF_CLOUD, 100, 12))), "200 429 ₽")
    c.eq("Облако 200 лиц · 12 мес = 400 858 ₽ (2 блока по 100, дивизор 1.0)",
         tq.calc_licenses(tq.TARIFF_CLOUD, 200, 12), 400858.0)

    # --- TC-03: Коробка ---
    c.contains("В calc.js для Коробки срок расчёта фиксируется 24 мес",
               calc_src.replace(" ", ""), "calcTerm=24")
    c.contains("В calc.js для Коробки применяется supportFee (тех.поддержка)",
               calc_src, "supportFee")
    c.eq("Коробка 100 лиц · 12 мес = 308 352 ₽ (1 год поддержки в цене)",
         tq.calc_licenses(tq.TARIFF_BOX, 100, 12), 308352.0)
    c.eq("Коробка 100 лиц · 24 мес = 400 858 ₽ (+1 год поддержки ×1.3)",
         tq.calc_licenses(tq.TARIFF_BOX, 100, 24), 400858.0)
    c.eq("Коробка 100 лиц · 36 мес = 493 363 ₽ (+2 года поддержки ×1.6)",
         tq.calc_licenses(tq.TARIFF_BOX, 100, 36), 493363.0)
    c.ok("Коробка дороже Облака при равных вводных (12 мес)",
         tq.calc_licenses(tq.TARIFF_BOX, 100, 12) > tq.calc_licenses(tq.TARIFF_CLOUD, 100, 12))

    # --- поведение при выборе обоих/ни одного тарифа ---
    app = tq.js("app")
    c.contains("Нельзя снять оба тарифа (ensureAtLeastOneTariff -> cloud)", app,
               "cloud.checked = true")
    return c.items
