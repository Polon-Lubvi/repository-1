"""Поиск повторов: одна и та же вакансия с разных сайтов, перевыложенная с новым номером
или разосланная по нескольким Telegram-каналам."""
from __future__ import annotations

import re

ORG_FORMS = r"\b(ооо|оао|зао|пао|ао|ип|нко|ано|фгбу|гбу|мбу|llc|ltd|inc)\b"
TITLE_NOISE = r"\b(удал[её]нн\w*|удал[её]нка|remote|гибрид\w*|офис\w*|работа|вакансия|в команду|ищем|ищет|ищут|требуется|срочно)\b"
SIMILAR = 0.75     # доля общих слов в описаниях, начиная с которой это одна вакансия
MIN_WORDS = 25     # короче — описание не сравниваем (слишком мало слов)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-zа-яё0-9]+", " ", (s or "").lower().replace("ё", "е"))).strip()


def norm_company(s: str) -> str:
    s = _norm(s)
    s = re.sub(ORG_FORMS, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_title(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", s or "")          # «(удалённо)», «(Москва)» и т.п.
    s = re.sub(TITLE_NOISE, " ", _norm(s))
    return re.sub(r"\s+", " ", s).strip()


def title_company_key(title: str, company: str) -> str | None:
    c = norm_company(company)
    if not c or "скрыт" in c or "hidden" in c:
        return None
    return f"{norm_title(title)}|{c}"


def words(text: str) -> frozenset[str]:
    return frozenset(w for w in _norm(text)[:1500].split() if len(w) >= 4)


def similar(a: frozenset[str], b: frozenset[str]) -> bool:
    if len(a) < MIN_WORDS or len(b) < MIN_WORDS:
        return False
    return len(a & b) / min(len(a), len(b)) >= SIMILAR


def title_words(title: str) -> frozenset[str]:
    return frozenset(w for w in norm_title(title).split() if len(w) >= 3)


def titles_compatible(a: frozenset[str], b: frozenset[str]) -> bool:
    """Похожие названия: «Дизайнер» ≈ «Графический дизайнер», но «Дизайнер упаковки» ≠ «Дизайнер-верстальщик».
    Нужно, чтобы общий абзац «о компании» не склеивал разные вакансии одной компании."""
    if not a or not b:
        return True
    return len(a & b) / min(len(a), len(b)) >= 0.6


class Seen:
    """Набор уже отправленных (или уже взятых в выгрузку) вакансий для быстрой проверки."""

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.tc: set[str] = set()
        self.texts: list[tuple[frozenset[str], frozenset[str]]] = []  # (слова названия, слова описания)

    def add(self, key: str, url: str, title: str, company: str, description: str) -> None:
        self.keys.update(k for k in (key, url) if k)
        tc = title_company_key(title, company)
        if tc:
            self.tc.add(tc)
        w = words(description)
        if len(w) >= MIN_WORDS:
            self.texts.append((title_words(title), w))

    def is_dup(self, v: dict) -> bool:
        if v.get("key") in self.keys or v.get("url") in self.keys:
            return True
        tc = title_company_key(v.get("title", ""), v.get("company", ""))
        if tc and tc in self.tc:
            return True
        w = words(v.get("description") or "")
        tw = title_words(v.get("title", ""))
        return any(titles_compatible(tw, t) and similar(w, d) for t, d in self.texts)

    def add_vac(self, v: dict) -> None:
        self.add(v.get("key", ""), v.get("url", ""), v.get("title", ""), v.get("company", ""),
                 v.get("description") or "")
