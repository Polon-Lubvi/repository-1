# -*- coding: utf-8 -*-
"""
TC-13  Интеграция с разделами «Документы» (Счета / Акты / Договоры)
TC-14  Контракт разметки: поля калькулятора, вкладки конфигурации, наличие всех секций
"""
import re

import tq
from harness import Checks

BLOCK = "TC-13/14 · Разметка и интеграция разделов"


def run():
    c = Checks()
    page = tq.html()
    consts = tq.data_constants()

    # --- вкладки конфигурации калькулятора ---
    tabs = re.findall(r'data-tab="([a-z-]+)"', page)
    for t in ("modules", "implementation", "tm"):
        c.ok("Вкладка конфигурации data-tab=%s" % t, t in tabs)

    # --- обязательные поля калькулятора ---
    for fid in ("licenceCount", "termMonths", "coefficient", "coefficientGrowth",
                "discountPercent", "tmHours", "modules-container",
                "implementation-presets", "implementation-rows", "export-btn"):
        c.contains("Элемент #%s присутствует" % fid, page, 'id="%s"' % fid)

    # --- модули из data.js должны иметь чекбоксы в договоре (общий modulesPicker) ---
    mp = tq.js("modulesPicker")
    c.contains("Общий компонент выбора модулей используется и в договоре", mp, "initModulesPicker")
    c.contains("В договоре состав модулей синхронизируется как в калькуляторе",
               page, "как в калькуляторе")

    all_modules = [m["id"] for g in consts["module_groups"] for m in g["modules"]]
    c.ok("Всего модулей в каталоге = 23", len(all_modules) == 23, "их %d" % len(all_modules))
    c.contains("Модуль messenger отдаётся клиенту (есть в data.js)", ",".join(all_modules), "messenger")

    # --- разделы документов присутствуют в SPA ---
    for marker, human in [
        ('data-page="invoices"', "Раздел «Счета»"),
        ('data-page="acts"', "Раздел «Акты»"),
        ('data-page="contracts"', "Раздел «Договоры»"),
        ('data-page="client-contracts"', "Раздел «Договоры по форме клиента»"),
    ]:
        c.contains(human, page, marker)

    c.contains("Счёт: кнопка «Сформировать счёт (.docx)»", page, "Сформировать счёт")
    c.contains("Акт: кнопка «Сформировать акт (.docx)»", page, "Сформировать акт")
    c.contains("Договор: кнопка «Сформировать договор (.docx)»", page, "Сформировать договор")
    c.contains("Договор по форме клиента: загрузка .docx/.xlsx", page, ".xlsx")

    # --- интеграция: договор ссылается на тарифы Джедаи/Магистры (SAAS/on-prem) ---
    contract_src = tq.js("contract")
    c.ok("Договор различает тип продукта (SAAS «Джедаи» / on-premise «Магистры»)",
         ("saas" in contract_src.lower()) and ("producttype" in contract_src.lower()))
    c.contains("В разметке договора есть тариф «Джедаи» (SAAS)", page, "Джедаи")
    c.contains("В разметке договора есть тариф «Магистры» (on-premise)", page, "Магистр")

    # --- лицензионные формулировки калькулятора совпадают с договором (ПО «Бублики») ---
    c.contains("Калькулятор оперирует ПО «Бублики»", tq.js("app"), "ПО «Бублики»")
    return c.items
