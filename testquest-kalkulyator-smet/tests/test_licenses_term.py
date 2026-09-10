# -*- coding: utf-8 -*-
"""
TC-04  Количество пользователей (лицензий) — прогрессивные дивизоры цены
TC-05  Срок лицензии — пороги скидок (0% / 10% / 20%)
"""
import tq
from harness import Checks

BLOCK = "TC-04/05 · Кол-во лицензий и срок"


def run():
    c = Checks()
    page = tq.html()
    consts = tq.data_constants()

    c.contains("Поле «Число лицензий» (#licenceCount)", page, 'id="licenceCount"')
    c.contains("Поле «Срок, мес» (#termMonths)", page, 'id="termMonths"')

    # --- TC-04: дивизоры ---
    divs = [d["divisor"] for d in consts["priceDivisors"]]
    c.eq("Таблица дивизоров как в data.js", divs, [1.0, 1.0, 1.5, 1.5, 1.5, 2.0, 3.0, 4.0, 5.0])
    c.eq("Облако 100 · 12 = 200 429 ₽ (дивизор 1.0)", tq.calc_licenses(0, 100, 12), 200429.0)
    c.eq("Облако 300 · 12 = 564 507 ₽ (3-й блок дивизор 1.5)", tq.calc_licenses(0, 300, 12), 564507.0)
    c.eq("Облако 500 · 12 = 891 806 ₽", tq.calc_licenses(0, 500, 12), 891806.0)
    c.ok("Удельная цена за лицензию падает с ростом объёма",
         tq.calc_licenses(0, 500, 12) / 500 < tq.calc_licenses(0, 100, 12) / 100)
    c.ok("Хвост < 100 лицензий тарифицируется (250 лиц > 200 лиц)",
         tq.calc_licenses(0, 250, 12) > tq.calc_licenses(0, 200, 12))

    # --- TC-05: пороги скидки по сроку ---
    c.eq("Пороги скидок из data.js", consts["termDiscounts"],
         [{"minTerm": 6, "discount": 10.0}, {"minTerm": 12, "discount": 20.0}])
    base_1m = tq.calc_licenses(0, 100, 1)   # скидки нет
    base_3m = tq.calc_licenses(0, 100, 3)   # скидки нет
    base_6m = tq.calc_licenses(0, 100, 6)   # -10%
    base_12m = tq.calc_licenses(0, 100, 12)  # -20%
    c.eq("Срок 3 мес: скидки нет — 62 634 ₽", base_3m, 62634.0)
    c.eq("Срок 6 мес: -10% — 112 741 ₽", base_6m, 112741.0)
    c.eq("Срок 12 мес: -20% — 200 429 ₽", base_12m, 200429.0)
    c.ok("Цена за месяц при 3 мес > цены за месяц при 12 мес (скидка работает)",
         base_3m / 3 > base_12m / 12)
    c.ok("Срок 1 и 5 мес — в одной ценовой группе (скидки нет): 5м = 5×(1м)",
         tq.calc_licenses(0, 100, 5) == round(base_1m * 5))

    # --- граничные: 0 лицензий / 0 мес для Облака => 0 ₽ ---
    c.eq("Облако: 0 лицензий -> 0 ₽", tq.calc_licenses(0, 0, 12), 0.0)
    c.eq("Облако: 0 месяцев -> 0 ₽", tq.calc_licenses(0, 100, 0), 0.0)
    return c.items
