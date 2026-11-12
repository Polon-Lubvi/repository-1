"""Оценка, насколько вакансия подходит кандидату (0–10), и причины."""
from __future__ import annotations

import re
from collections import Counter

from . import candidate, storage


def _rx(word: str) -> re.Pattern:
    # слово ищем с начала слова, чтобы «vk» не находилось внутри других слов
    return re.compile(r"(?<![a-zа-яё])" + re.escape(word), re.I)


_CAT_RX = [(cat, [_rx(w) for w in cat["words"]]) for cat in candidate.INTEREST_CATEGORIES]


def matched_categories(text: str) -> dict[str, int]:
    """key категории → сколько раз встретились её слова."""
    res = {}
    for cat, rxs in _CAT_RX:
        n = sum(len(rx.findall(text)) for rx in rxs)
        if n:
            res[cat["key"]] = n
    return res


def detect_format(v: dict) -> str:
    if v.get("work_format"):
        return v["work_format"]
    text = " ".join([v.get("title", ""), v.get("snippet", ""), v.get("description", "")[:3000]]).lower()
    if any(w in text for w in candidate.REMOTE_WORDS):
        return "удалённо"
    if any(w in text for w in candidate.HYBRID_WORDS):
        return "гибрид"
    return ""


# Грубый курс к рублю — только чтобы сравнить с желаемой зарплатой
RATES = [(("kzt", "тенге", "₸"), 0.18), (("usd", "$", "долл"), 90), (("eur", "€", "евро"), 100),
         (("byn", "бел. руб"), 28), (("uzs", "сум"), 0.0075)]


def _salary_numbers(s: str) -> list[int]:
    """Числа зарплаты в рублях."""
    s = s or ""
    low = s.lower()
    rate = next((r for keys, r in RATES if any(k in low for k in keys)), 1)
    nums = []
    for m in re.findall(r"\d[\d \xa0]*", s):
        digits = re.sub(r"\D", "", m)
        if not digits:
            continue
        n = int(digits)
        if n < 1000 and re.search(r"\d\s*(к|тыс)", low):
            n *= 1000
        n = int(n * rate)
        if 5000 <= n <= 1_000_000:
            nums.append(n)
    return nums


def learned_bonus() -> Counter:
    """Категории из вакансий, к которым кандидат сам переписала письмо, — сигнал «это мне интересно»."""
    cnt: Counter = Counter()
    for ex in storage.list_examples():
        for k in ex.get("keywords") or []:
            cnt[k] += 1
    return cnt


def score(v: dict, bonus: Counter | None = None) -> dict:
    """Добавляет в v: score, reasons (list[str]), warnings (list[str]), work_format, categories.
    Возвращает v. v['excluded'] = причина, если вакансию не надо показывать."""
    bonus = bonus if bonus is not None else Counter()
    title = (v.get("title") or "").lower()
    text = " ".join([v.get("title", ""), v.get("snippet", ""), v.get("description", "")])
    low = text.lower()
    reasons, warnings = [], []
    v["excluded"] = ""

    if not title or not any(w in title for w in candidate.DESIGN_TITLE_WORDS):
        v["excluded"] = "не дизайнерская должность"
    elif any(w in title for w in candidate.EXCLUDE_TITLE):
        v["excluded"] = "неподходящее направление (маркетплейсы / UX / интерьер и т.п.)"

    fmt = detect_format(v)
    v["work_format"] = fmt
    loc = (v.get("location") or "").lower()
    in_city = any(w in loc or w in low[:1500] for w in candidate.CITY_WORDS)
    s = 2.0
    if "удал" in fmt:
        s += 2
        reasons.append("удалённый формат — подходит из Ростова")
    elif "гибрид" in fmt and in_city:
        s += 2
        reasons.append("гибрид в Ростове-на-Дону")
    elif in_city:
        s += 0.5
        warnings.append("похоже на офис в Ростове — уточнить возможность гибрида")
    elif loc and not v["excluded"]:
        v["excluded"] = f"офис/гибрид не в Ростове ({v.get('location')})"

    cats = matched_categories(text)
    title_cats = matched_categories(v.get("title") or "")
    v["categories"] = sorted(cats, key=lambda k: -cats[k])
    interest = 0.0
    for cat in candidate.INTEREST_CATEGORIES:
        if cat["key"] in cats:
            # совпадение в названии весит больше, чем упоминание где-то в описании
            k = 1.0 if cat["key"] in title_cats else min(0.8, 0.3 + 0.15 * cats[cat["key"]])
            interest += cat["weight"] * k
            reasons.append(cat["title"])
            if bonus.get(cat["key"]):
                interest += min(1.5, 0.5 * bonus[cat["key"]])
    s += min(5.0, interest * 0.8)

    if any(w in title for w in candidate.WEB_TITLE_WORDS) and not title_cats.keys() & {"identity", "branding"}:
        s -= 1.5
        warnings.append("больше веб-дизайн, чем графика")

    if any(w in low for w in candidate.PENALTY_TEXT):
        s -= 3
        warnings.append("в описании есть маркетплейсы/карточки товаров")
    if any(w in title for w in candidate.SENIOR_WORDS):
        s -= 2
        warnings.append("позиция уровня senior/lead — может требовать больше опыта")
    elif any(w in title for w in candidate.JUNIOR_WORDS):
        s += 0.5
    exp = re.search(r"опыт[^.\n]{0,40}?(?:от|не менее|более)\s*(\d+)", low)
    if exp and int(exp.group(1)) >= 4:
        s -= 1.5
        warnings.append(f"просят опыт от {exp.group(1)} лет")

    nums = _salary_numbers(v.get("salary", ""))
    if nums:
        top = max(nums)
        if top >= candidate.DESIRED_SALARY:
            s += 1
            reasons.append("зарплата не ниже желаемой")
        elif top < candidate.DESIRED_SALARY * 0.7:
            s -= 1.5
            warnings.append("зарплата ниже желаемой")

    v["score"] = round(max(0.0, min(10.0, s)), 1)
    v["reasons"] = reasons
    v["warnings"] = warnings
    return v


def why_interesting(v: dict) -> str:
    """Шаблонное «чем интересна» (если нет Claude API)."""
    def cap(s: str) -> str:
        return s[:1].upper() + s[1:]

    parts = []
    by_key = {c["key"]: c for c in candidate.INTEREST_CATEGORIES}
    for key in (v.get("categories") or [])[:3]:  # самые частые в тексте вакансии
        cat = by_key[key]
        parts.append(f"• {cap(cat['title'])}: {cat['pitch']}.")
    for r in v.get("reasons", []):
        if "формат" in r or "гибрид" in r or "зарплата" in r:
            parts.append(f"• {cap(r)}.")
    for w in v.get("warnings", []):
        parts.append(f"⚠ {cap(w)}.")
    return "\n".join(parts) or "• Общая позиция графического дизайнера — стоит посмотреть задачи подробнее."
