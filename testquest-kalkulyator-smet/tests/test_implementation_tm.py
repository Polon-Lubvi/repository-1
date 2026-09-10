# -*- coding: utf-8 -*-
"""
TC-08  Внедрение — типовые пресеты, фикс-цены, НДС 5%, строки «только on-premise», метка T&M
TC-09  Time&Material — резерв часов × ставка, НДС 5% в Excel, пересчёт при смене часов
"""
import tq
from harness import Checks

BLOCK = "TC-08/09 · Внедрение и Time&Material"


def run():
    c = Checks()
    consts = tq.data_constants()
    page = tq.html()
    app = tq.js("app")
    exp = tq.js("exportEstimate")

    presets = {p["id"]: p for p in consts["presets"]}

    # --- TC-08: пресеты внедрения ---
    c.ok("Пресетов внедрения >= 15", len(consts["presets"]) >= 15, "их %d" % len(consts["presets"]))
    c.eq("«Подготовка технического задания» — фикс 117 000 ₽",
         (presets["tech-spec"]["pricing"], presets["tech-spec"]["defaultPrice"]), ("fixed", 117000))
    c.eq("«Подготовка приемочных тестов» — фикс 58 500 ₽",
         presets["acceptance-tests"]["defaultPrice"], 58500)
    c.eq("«Настройка синхронизации (1 источник)» — фикс 187 200 ₽",
         presets["user-sync-single"]["defaultPrice"], 187200)
    c.ok("«Прохождение проверок ИБ» — тип T&M", presets["ib-review"]["pricing"] == "tm")
    c.ok("«Настройка портала в соответствии с ТЗ» — бесплатно (free)",
         presets["portal-tz"]["pricing"] == "free")

    onprem_only = {p["id"] for p in consts["presets"] if p["onPremOnly"]}
    for pid in ("deploy-arch", "test-env", "prod-migration"):
        c.ok("Пресет «%s» помечен onPremOnly" % pid, pid in onprem_only)
    c.contains("Облачная смета исключает строки on-premise",
               app.replace(" ", ""), "isImplementationOnPremOnly")
    c.contains("tariffIndex===0 -> строки onPremOnly отфильтровываются",
               app.replace(" ", ""), "tariffIndex===0&&isImplementationOnPremOnly(item)")

    # --- TC-08: НДС и итог по строке внедрения ---
    c.contains("НДС по умолчанию для внедрения = 5%", app, "DEFAULT_IMPLEMENTATION_VAT = 5")
    r = tq.implementation_row_gross(117000, 5.0)
    c.eq("ТЗ 117 000 ₽ + НДС 5% = 5 850 ₽ НДС", r["vat"], 5850)
    c.eq("ТЗ 117 000 ₽ с НДС = 122 850 ₽", r["gross"], 122850)
    c.contains("Строки T&M выводятся меткой «T&M», а не суммой", app, "IMPLEMENTATION_TM_LABEL = 'T&M'")

    # разметка панели
    c.contains("Панель «Внедрение» (пресеты)", page, 'id="implementation-presets"')
    c.contains("Кнопка «+ Добавить произвольную строку»", page, 'id="implementation-add-row"')

    # --- TC-09: Time&Material ---
    c.eq("Ставка T&M = 5 850 ₽/чч", consts["tm_rate"], 5850)
    c.eq("Резерв по умолчанию = 100 чч", consts["tm_hours"], 100)
    c.eq("Резерв 100 чч = 585 000 ₽ (без НДС)", tq.tm_amount(100), 585000)
    c.eq("Резерв 50 чч = 292 500 ₽ (пересчёт при смене часов)", tq.tm_amount(50), 292500)
    c.eq("Резерв 0 чч = 0 ₽", tq.tm_amount(0), 0)
    c.contains("Поле «Часы Time&Material» (#tmHours)", page, 'id="tmHours"')
    tm_vat = tq.implementation_row_gross(tq.tm_amount(100), 5.0)
    c.eq("T&M 585 000 ₽ + НДС 5% в Excel = 614 250 ₽", tm_vat["gross"], 614250)
    c.contains("В exportEstimate T&M считается с НДС 5%", exp.replace(" ", ""), "net*0.05")
    return c.items
