# -*- coding: utf-8 -*-
"""
TC-06  Модули — коэффициенты групп и модуля «Мессенджер», поле «К-т по модулям»
TC-07  Модуль «в подарок» — цена «в подарок», коэффициент НЕ увеличивается
"""
import tq
from harness import Checks

BLOCK = "TC-06/07 · Модули и подарки"


def run():
    c = Checks()
    consts = tq.data_constants()
    page = tq.html()
    app = tq.js("app")

    groups = {g["id"]: g for g in consts["module_groups"]}
    c.eq("Базовая конфигурация: coefAdd 0", groups["base"]["coefAdd"], 0.0)
    c.eq("Ключевые модули: coefAdd 0.2", groups["extended"]["coefAdd"], 0.2)
    c.eq("Дополнительные модули: coefAdd 0.1", groups["other"]["coefAdd"], 0.1)
    c.eq("Планируются к выходу: coefAdd 0.2", groups["planned"]["coefAdd"], 0.2)

    msgr = next(m for m in groups["extended"]["modules"] if m["id"] == "messenger")
    c.eq("«Мессенджер» имеет индивидуальный coefAdd 0.3", msgr["coefAdd"], 0.3)

    base_group = groups["base"]["modules"]
    c.ok("Все 4 базовых модуля обязательные (mandatory)", all(m["mandatory"] for m in base_group))

    # --- TC-06: расчёт коэффициента ---
    c.eq("Коэф. без доп. модулей = 1.0", tq.modules_coefficient([]), 1.0)
    c.eq("+1 ключевой модуль -> 1.2", tq.modules_coefficient(["process-builder"]), 1.2)
    c.eq("+1 доп. модуль -> 1.1", tq.modules_coefficient(["tasks"]), 1.1)
    c.eq("+Мессенджер -> 1.3", tq.modules_coefficient(["messenger"]), 1.3)
    c.eq("ключевой + доп. + мессенджер -> 1.6",
         tq.modules_coefficient(["process-builder", "tasks", "messenger"]), 1.6)
    c.contains("Поле «К-т по модулям» (#coefficient) есть и только для чтения", page, 'id="coefficient"')
    c.contains("#coefficient блокируется (disabled) — считается автоматически", app,
               "coefInput.disabled = true")

    # эффект коэффициента на цену
    price_1 = tq.calc_licenses(0, 100, 12, coefficient=1.0)
    price_13 = tq.calc_licenses(0, 100, 12, coefficient=1.3)
    c.near("Коэф. 1.3 повышает цену лицензий ровно в 1.3 раза",
           price_13, price_1 * 1.3, tol=2.0)

    # --- TC-07: подарок ---
    c.eq("Подарочный модуль не входит в коэффициент (1.0)",
         tq.modules_coefficient(["messenger"], gift_ids=["messenger"]), 1.0)
    c.eq("Из двух модулей подарочный не считается (1.2, а не 1.5)",
         tq.modules_coefficient(["process-builder", "messenger"], gift_ids=["messenger"]), 1.2)
    c.contains("В UI подарочная цена выводится как «в подарок»", app, "'в подарок'")
    c.contains("Кнопка «В подарок» доступна только для необязательных модулей вне базы", app,
               "!module.mandatory && groupId !== 'base'")
    return c.items
