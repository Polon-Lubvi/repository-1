# -*- coding: utf-8 -*-
"""
TC-10  ИТОГО — агрегатор сметы: лицензии − скидка + внедрение (с НДС) + T&M
"""
import re

import tq
from harness import Checks

BLOCK = "TC-10 · ИТОГО (агрегатор сметы)"


def grand_total(licenses, discount_pct=0.0, implementation_nets=None, implementation_vat=5.0):
    """Порт renderEstimateForTariff -> grandTotal (без строки T&M, она идёт отдельным блоком)."""
    after_discount = licenses * (1.0 - discount_pct / 100.0)
    impl_gross = sum(
        tq.implementation_row_gross(net, implementation_vat)["gross"]
        for net in (implementation_nets or [])
    )
    return after_discount + impl_gross


def run():
    c = Checks()
    app = tq.js("app")

    lic = tq.calc_licenses(0, 300, 12, coefficient=tq.modules_coefficient(["messenger"]))  # 1.3
    c.near("Лицензии: 300 · 12 мес · коэф 1.3", lic, tq.calc_licenses(0, 300, 12) * 1.3, tol=3.0)

    # скидка 10%
    disc_total = lic * 0.9
    c.near("Скидка 10% уменьшает лицензии на 10%", lic - disc_total, lic * 0.1, tol=1.0)

    # + внедрение: ТЗ 117 000 + приёмочные тесты 58 500, НДС 5%
    impl_nets = [117000, 58500]
    impl_gross = sum(tq.implementation_row_gross(n, 5.0)["gross"] for n in impl_nets)
    c.eq("Внедрение (117 000 + 58 500) с НДС 5% = 184 275 ₽", impl_gross, 184275)

    gt = grand_total(lic, 10.0, impl_nets)
    c.near("ИТОГО «Всего» = лицензии−10% + внедрение_с_НДС",
           gt, disc_total + impl_gross, tol=1.0)
    c.ok("ИТОГО больше стоимости одних лицензий со скидкой", gt > disc_total)

    # формулы агрегатора присутствуют в app.js
    c.contains("grandTotal = totalAfterDiscount + implementationTotals.gross",
               app.replace(" ", ""), "grandTotal=totalAfterDiscount+implementationTotals.gross")
    c.contains("Строка «Всего» помечается классом total final", app, "'total final'")
    c.contains("Строка «Скидка N %» появляется только при discount > 0", app, "if (discountPct > 0)")

    # T&M-блок отдельно, со своим «Всего»
    c.contains("Отдельный блок T&M со своим итогом", app, "renderTmEstimate")

    # маска имени файла экспорта содержит «КП по реализации проекта»
    exp = tq.js("exportEstimate")
    c.contains("Имя файла Excel строится по маске «КП по реализации проекта …»",
               exp, "КП по реализации проекта")
    return c.items
