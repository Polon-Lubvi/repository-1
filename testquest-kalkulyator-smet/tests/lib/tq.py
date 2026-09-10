"""
Общая библиотека для тестов калькулятора смет TestQuest.

Ничего не устанавливает: только стандартная библиотека Python 3.8+.
Всё тянется по сети с BASE_URL (по умолчанию https://testquest.pryaniky.com).

Тут же лежит порт движка ценообразования (calc.js -> Python), сверенный
1:1 с живым стендом на десятках сценариев.
"""

import base64
import json
import math
import os
import re
import ssl
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "https://testquest.pryaniky.com").rstrip("/")

_CACHE = {}
# Некоторые окружения без корневых сертификатов -> не валим тесты из-за TLS.
_SSL_CTX = ssl.create_default_context()
if os.environ.get("TQ_INSECURE_TLS") == "1":
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch(path, binary=False):
    """GET относительно BASE_URL, с кэшем в рамках прогона."""
    key = (path, binary)
    if key in _CACHE:
        return _CACHE[key]
    url = path if path.startswith("http") else BASE_URL + path
    req = urllib.request.Request(url, headers={"User-Agent": "TestQuest-QA-kit/1.0"})
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        data = resp.read()
    out = data if binary else data.decode("utf-8", "replace")
    _CACHE[key] = out
    return out


def js(name):
    """Содержимое /js/<name>.js со стенда."""
    return fetch("/js/%s.js" % name)


def html():
    return fetch("/")


# --------------------------------------------------------------------------
# Разбор констант из js/data.js (это не eval — аккуратные регэкспы/JSON).
# --------------------------------------------------------------------------

def _num_list(src, key):
    m = re.search(key + r"\s*:\s*\[(.*?)\]", src, re.S)
    if not m:
        return []
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m.group(1))]


def data_constants():
    if "data_constants" in _CACHE:
        return _CACHE["data_constants"]
    src = js("data")

    base_values = []
    block = re.search(r"baseValues\s*:\s*\[(.*?)\]", src, re.S).group(1)
    for row in re.finditer(
        r"variant\s*:\s*(\d+)\s*,\s*baseCloudPrice\s*:\s*([\d.]+)\s*,\s*baseYearSupportFee\s*:\s*([\d.]+)",
        block,
    ):
        base_values.append(
            {
                "variant": int(row.group(1)),
                "baseCloudPrice": float(row.group(2)),
                "baseYearSupportFee": float(row.group(3)),
            }
        )

    divisors = []
    dblock = re.search(r"priceDivisors\s*:\s*\[(.*?)\]", src, re.S).group(1)
    for row in re.finditer(r"PriceTag\s*:\s*(\d+)\s*,\s*Divisor\s*:\s*([\d.]+)", dblock):
        divisors.append({"tag": int(row.group(1)), "divisor": float(row.group(2))})

    term_discounts = []
    tblock = re.search(r"termDiscounts\s*:\s*\[(.*?)\]", src, re.S).group(1)
    for row in re.finditer(r"minTerm\s*:\s*(\d+)\s*,\s*discount\s*:\s*([\d.]+)", tblock):
        term_discounts.append({"minTerm": int(row.group(1)), "discount": float(row.group(2))})

    tm_rate = int(re.search(r"TM_HOURLY_RATE\s*:\s*(\d+)", src).group(1))
    tm_hours = int(re.search(r"TM_DEFAULT_HOURS\s*:\s*(\d+)", src).group(1))

    managers = []
    mblock = re.search(r"KP_MANAGERS\s*:\s*\[(.*?)\]\s*,\s*MODULE_GROUPS", src, re.S).group(1)
    for row in re.finditer(
        r"id:\s*'([^']+)'\s*,\s*name:\s*'([^']+)'\s*,\s*phone:\s*'([^']+)'\s*,\s*email:\s*'([^']+)'",
        mblock,
    ):
        managers.append(
            {"id": row.group(1), "name": row.group(2), "phone": row.group(3), "email": row.group(4)}
        )

    # MODULE_GROUPS: id + coefAdd + модули (id, mandatory, coefAdd?)
    groups = []
    gblock = re.search(r"MODULE_GROUPS\s*:\s*\[(.*)\]\s*,?\s*\};", src, re.S).group(1)
    for gm in re.finditer(
        r"\{\s*id:\s*'([^']+)',\s*title:\s*'([^']*)',\s*coefAdd:\s*([\d.]+),\s*modules:\s*\[(.*?)\]\s*,?\s*\}",
        gblock,
        re.S,
    ):
        mods = []
        for mm in re.finditer(r"\{([^}]*)\}", gm.group(4)):
            body = mm.group(1)
            mid = re.search(r"id:\s*'([^']+)'", body).group(1)
            mandatory = "mandatory: true" in body
            ca = re.search(r"coefAdd:\s*([\d.]+)", body)
            mods.append(
                {
                    "id": mid,
                    "mandatory": mandatory,
                    "coefAdd": float(ca.group(1)) if ca else None,
                }
            )
        groups.append(
            {"id": gm.group(1), "title": gm.group(2), "coefAdd": float(gm.group(3)), "modules": mods}
        )

    # IMPLEMENTATION_PRESET_GROUPS: собираем плоский список пресетов
    presets = []
    iblock = re.search(
        r"IMPLEMENTATION_PRESET_GROUPS\s*:\s*\[(.*?)\]\s*,\s*KP_MANAGERS", src, re.S
    ).group(1)
    for it in re.finditer(r"\{\s*id:\s*'([^']+)',\s*label:\s*'((?:[^'\\]|\\.)*)'(.*?)\}", iblock, re.S):
        tail = it.group(3)
        pricing = re.search(r"pricing:\s*'([^']+)'", tail)
        dp = re.search(r"defaultPrice:\s*(\d+)", tail)
        presets.append(
            {
                "id": it.group(1),
                "label": it.group(2),
                "pricing": pricing.group(1) if pricing else "custom",
                "defaultPrice": int(dp.group(1)) if dp else None,
                "onPremOnly": "onPremOnly: true" in tail,
            }
        )

    out = {
        "baseValues": base_values,
        "priceDivisors": divisors,
        "termDiscounts": term_discounts,
        "tm_rate": tm_rate,
        "tm_hours": tm_hours,
        "managers": managers,
        "module_groups": groups,
        "presets": presets,
    }
    _CACHE["data_constants"] = out
    return out


# --------------------------------------------------------------------------
# Порт движка ценообразования (js/calc.js). Сверен со стендом.
# --------------------------------------------------------------------------

TARIFF_CLOUD = 0   # TariffType.Test  -> "TestQuest Облако (SAAS)"
TARIFF_BOX = 1     # TariffType.Quest -> "TestQuest Коробка (on-premise)"


def _term_discount(term, term_discounts):
    applicable = [d["discount"] for d in term_discounts if d["minTerm"] <= term]
    if not applicable:
        return 1.0
    return 1.0 - max(applicable) / 100.0


def calc_licenses(tariff, licence_count, term_months, coefficient=1.0, variant=0, consts=None):
    """Возвращает стоимость лицензий (округлённую), как в calc.js -> formatCurrency."""
    c = consts or data_constants()
    divisors = [d["divisor"] for d in c["priceDivisors"]]
    base_row = next(b for b in c["baseValues"] if b["variant"] == variant)

    if (term_months == 0 or licence_count == 0) and tariff == TARIFF_CLOUD:
        return 0.0

    calc_term = 24 if tariff == TARIFF_BOX else term_months
    discount = _term_discount(calc_term, c["termDiscounts"])

    tail = licence_count % 100
    row_count = (licence_count - tail) // 100
    rows = [100] * row_count + [tail]

    base_price = base_row["baseCloudPrice"] * coefficient
    support_fee = base_row["baseYearSupportFee"]

    cur = 0
    month_sum = 0.0
    for i, cnt in enumerate(rows):
        cur += 100
        if i < len(divisors):
            dc = 1.0 / math.sqrt(divisors[i])
        else:
            dc = 1.0 / math.sqrt(cur / 100.0)
        month_sum += base_price * dc * cnt

    total = month_sum * calc_term * discount

    if tariff == TARIFF_BOX:
        magister_base = total / (1.0 + support_fee / 100.0)
        support_years = math.ceil(term_months / 12) if term_months else 0
        support_coef = 1.0
        if support_years > 1:
            support_coef = 1.0 + (support_fee / 100.0) * (support_years - 1)
        total = magister_base * support_coef

    return float(round(total))


def modules_coefficient(selected_ids, gift_ids=None, consts=None):
    """Порт calculateModulesCoefficient(): 1 + сумма надбавок выбранных не-подарочных модулей."""
    c = consts or data_constants()
    gift = set(gift_ids or [])
    adds = 0.0
    for g in c["module_groups"]:
        for m in g["modules"]:
            if m["id"] in selected_ids and m["id"] not in gift:
                if m["mandatory"]:
                    continue
                adds += m["coefAdd"] if m["coefAdd"] is not None else g["coefAdd"]
    return round((1.0 + adds) * 100) / 100.0


def implementation_row_gross(net, vat_rate=5.0):
    net = round(net)
    vat = round(net * vat_rate / 100.0)
    return {"net": net, "vat": vat, "gross": net + vat}


def tm_amount(hours, consts=None):
    c = consts or data_constants()
    return hours * c["tm_rate"]


def format_currency_rub(value):
    """Аналог Intl.NumberFormat ru-RU RUB, maximumFractionDigits:0.

    Возвращает строку с обычными пробелами; на стенде Intl использует
    неразрывный пробел — для сравнения применяйте norm_ws().
    """
    n = int(round(value))
    s = "{:,}".format(abs(n)).replace(",", " ")
    sign = "- " if n < 0 else ""
    return "%s%s ₽" % (sign, s)


def norm_ws(text):
    """Схлопывает любые юникод-пробелы (NBSP U+00A0, узкий U+202F) в обычный."""
    swapped = str(text)
    for ch in (' ', ' ', ' ', ' '):
        swapped = swapped.replace(ch, ' ')
    return re.sub(r"\s+", " ", swapped).strip()
