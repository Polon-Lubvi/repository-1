# -*- coding: utf-8 -*-
"""
TC-12  Валидация обязательных полей
       * Счёт / Акт / Договор (.docx) — обязательные поля, ИНН 10/12 цифр
       * Калькулятор смет: Облако при 0 лицензий / 0 месяцев -> 0 ₽
       * Известное поведение: выгрузка Excel НЕ валидирует мета-поля КП
"""
import re

import tq
from harness import Checks

BLOCK = "TC-12 · Валидация"


def run():
    c = Checks()
    invoice = tq.js("invoice")
    act = tq.js("act")
    contract = tq.js("contract")
    fv = tq.js("formValidation")
    app = tq.js("app")

    # общий модуль подсветки ошибок
    c.contains("Есть модуль подсветки ошибок форм", fv, "applyFormValidation")
    c.contains("Невалидное поле помечается классом param-input--invalid", fv, "param-input--invalid")

    # --- Счёт ---
    c.contains("Счёт: требуется номер счёта", invoice, "Укажите номер счёта")
    c.contains("Счёт: требуется дата счёта", invoice, "Укажите дату счёта")
    c.contains("Счёт: ИНН должен быть 10 или 12 цифр", invoice, "10 или 12 цифр")
    c.contains("Счёт: требуется юр. название заказчика", invoice, "Укажите юридическое название заказчика")
    c.contains("Счёт: применяется applyFormValidation при ошибке", invoice, "applyFormValidation")
    inn_re = re.search(r"/\^\\d\{10\}\(\?:\\d\{2\}\)\?\$/", invoice) or re.search(r"\\d\{10\}", invoice)
    c.ok("Счёт: в коде есть регэксп проверки ИНН (10/12 цифр)", bool(inn_re))

    # --- Акт ---
    c.contains("Акт: требуется номер акта", act, "Укажите номер акта")
    c.contains("Акт: требуется дата акта", act, "Укажите дату акта")
    c.contains("Акт: требуются реквизиты заказчика", act, "Укажите реквизиты заказчика")
    c.contains("Акт: есть выбор типа (работы / передача прав)", tq.html(), 'value="rights"')

    # --- Договор ---
    c.contains("Договор: требуется номер договора", contract, "Укажите номер договора")
    c.contains("Договор: требуется дата договора", contract, "Укажите дату договора")
    c.contains("Договор: требуется размер пакета лицензий", contract, "Укажите размер пакета лицензий")
    c.contains("Договор: требуется стоимость пакета лицензий", contract, "Укажите стоимость пакета лицензий")

    # --- Калькулятор: граничные значения ---
    c.eq("Облако: 0 лицензий -> смета 0 ₽", tq.calc_licenses(0, 0, 12), 0.0)
    c.eq("Облако: срок 0 мес -> смета 0 ₽", tq.calc_licenses(0, 100, 0), 0.0)
    c.contains("В calc.js есть защита (term==0 || licenceCount==0) для Облака",
               tq.js("calc").replace(" ", ""), "termMonths===0||licenceCount===0")
    c.contains("Числовые поля калькулятора чистятся от нецифровых символов",
               app, "replace(/\\D/g, '')")

    # --- Известный дефект: выгрузка Excel не проверяет мета-поля ---
    has_meta_guard = any(
        s in app for s in ("Укажите компанию", "Заполните название компании", "companyName.*required")
    )
    c.contains("BUG-4: «К-т роста г/г» не валидируется (getGrowthCoefficient без границ)",
               app, "getGrowthCoefficient")
    c.eq("BUG-4 следствие: коэффициент роста 0 обнуляет смету по лицензиям",
         tq.calc_licenses(0, 100, 12, coefficient=0.0), 0.0)

    c.ok("BUG-канарейка: экспорт Excel не валидирует «Компания»/«Число лицензий» "
         "(тест зафиксирует регресс, если валидацию добавят)",
         not has_meta_guard,
         "сейчас валидации мета-полей КП нет — задокументировано в TESTCASES.md (BUG-1)")
    return c.items
