"""Сбор вакансий с сайтов и Telegram-каналов.

Каждый «адаптер» получает строку сайта из БД и возвращает список вакансий (dict):
key, url, source, title, company, salary, location, work_format, published (datetime|None),
description, snippet.
Описание вакансии, если адаптер его не дал, дочитывается со страницы вакансии (fetch_detail).
"""
from __future__ import annotations

import html as htmllib
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import candidate, config

log = logging.getLogger(__name__)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.6",
}
SESSION = requests.Session()
SESSION.headers.update(UA)
MSK = timezone(timedelta(hours=3))


# ---------------------------------------------------------------- утилиты
def get(url: str, params: dict | None = None, timeout: int = 25) -> requests.Response | None:
    for attempt in range(2):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            log.warning("HTTP %s %s", r.status_code, url)
            if r.status_code in (403, 404):
                return None
        except requests.RequestException as e:
            log.warning("Ошибка запроса %s: %s", url, e)
        time.sleep(1.5 * (attempt + 1))
    return None


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4"]):
        br.insert_after("\n")
    text = soup.get_text(" ")
    text = htmllib.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=MSK)
    s = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s.replace("Z", "+0000").replace("+03:00", "+0300"), fmt)
            return d if d.tzinfo else d.replace(tzinfo=MSK)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=MSK)
    except ValueError:
        return None


RU_MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7,
             "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}


def parse_ru_date(text: str) -> datetime | None:
    """'9 ноября 2026', '9 ноя', 'сегодня', 'вчера'."""
    t = text.lower()
    today = datetime.now(MSK)
    if "сегодня" in t or "час" in t or "минут" in t:
        return today
    if "вчера" in t:
        return today - timedelta(days=1)
    m = re.search(r"(\d{1,2})\s+([а-я]+)\.?\s*(\d{4})?", t)
    if not m:
        return None
    day, mon, year = int(m.group(1)), m.group(2), m.group(3)
    month = next((n for k, n in sorted(RU_MONTHS.items(), key=lambda x: -len(x[0])) if mon.startswith(k[:3])), None)
    if not month:
        return None
    y = int(year) if year else today.year
    try:
        d = datetime(y, month, day, tzinfo=MSK)
    except ValueError:
        return None
    if d > today + timedelta(days=1):
        d = d.replace(year=y - 1)
    return d


def fmt_salary(frm=None, to=None, cur: str = "₽", note: str = "") -> str:
    def n(x):
        return f"{int(x):,}".replace(",", " ")
    cur = {"RUR": "₽", "RUB": "₽", "rub": "₽", "USD": "$", "EUR": "€", None: "₽"}.get(cur, cur)
    if frm and to:
        s = f"{n(frm)}–{n(to)} {cur}"
    elif frm:
        s = f"от {n(frm)} {cur}"
    elif to:
        s = f"до {n(to)} {cur}"
    else:
        return ""
    return (s + (f" {note}" if note else "")).strip()


def _has(text: str, words) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def title_ok(title: str) -> bool:
    t = (title or "").lower()
    return bool(t) and _has(t, candidate.DESIGN_TITLE_WORDS) and not _has(t, candidate.EXCLUDE_TITLE)


def new_vac(**kw) -> dict:
    base = dict(key="", url="", source="", title="", company="", salary="", location="",
                work_format="", published=None, description="", snippet="")
    base.update(kw)
    if not base["key"]:
        base["key"] = base["url"].split("?")[0].rstrip("/")
    return base


# ---------------------------------------------------------------- страница вакансии
def _jobposting(soup: BeautifulSoup) -> dict | None:
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or sc.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                return it
    return None


def _jp_salary(jp: dict) -> str:
    bs = jp.get("baseSalary")
    if not isinstance(bs, dict):
        return ""
    val = bs.get("value") if isinstance(bs.get("value"), dict) else {}
    return fmt_salary(val.get("minValue") or val.get("value"), val.get("maxValue"), bs.get("currency") or "₽")


def _jp_location(jp: dict) -> str:
    loc = jp.get("jobLocation")
    locs = loc if isinstance(loc, list) else [loc] if loc else []
    names = []
    for l in locs:
        if isinstance(l, dict):
            addr = l.get("address")
            if isinstance(addr, dict):
                names.append(addr.get("addressLocality") or addr.get("addressRegion") or "")
            elif isinstance(addr, str):
                names.append(addr)
    return ", ".join(dict.fromkeys(n for n in names if n))


def main_text(soup: BeautifulSoup) -> str:
    """Упрощённый readability: блок, который непосредственно содержит больше всего текста абзацев.
    Списки соседних вакансий (почти целиком из ссылок) не учитываются."""
    scores: dict = {}
    for el in soup.find_all(["p", "li", "h2", "h3"]):
        text = el.get_text(" ", strip=True)
        if len(text) < 25:
            continue
        link_len = sum(len(a.get_text(strip=True)) for a in el.find_all("a"))
        if link_len > 0.5 * len(text):
            continue
        holder = el.parent.parent if el.name == "li" and el.parent is not None else el.parent
        if holder is None:
            continue
        entry = scores.setdefault(id(holder), [holder, 0])
        entry[1] += len(text)
    if scores:
        best = max(scores.values(), key=lambda x: x[1])[0]
        # если текст разбит на соседние блоки (заголовок + абзацы), берём общего родителя
        parent = best.parent
        if parent is not None and len(parent.get_text(" ", strip=True)) < 2.2 * len(best.get_text(" ", strip=True)):
            best = parent
        return html_to_text(str(best))
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    return meta.get("content", "") if meta else ""


def fetch_detail(url: str) -> dict:
    """Читает страницу вакансии: JobPosting из ld+json, иначе h1 + основной текст."""
    r = get(url)
    if not r:
        return {}
    soup = BeautifulSoup(r.text, "html.parser")
    out: dict = {}
    jp = _jobposting(soup)
    if jp:
        org = jp.get("hiringOrganization")
        out = {
            "title": htmllib.unescape(jp.get("title") or ""),
            "company": (org.get("name") if isinstance(org, dict) else org) or "",
            "description": html_to_text(jp.get("description") or ""),
            "published": parse_date(jp.get("datePosted")),
            "salary": _jp_salary(jp),
            "location": _jp_location(jp),
            "work_format": "удалённо" if str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE" else "",
        }
    # hh отдаёт описание в отдельном блоке — он полнее, чем ld+json
    hh_desc = soup.find(attrs={"data-qa": "vacancy-description"})
    if hh_desc:
        out["description"] = html_to_text(str(hh_desc))
    if not out.get("description"):
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "form", "aside"]):
            tag.decompose()
        h1 = soup.find("h1")
        out.setdefault("title", h1.get_text(" ", strip=True) if h1 else "")
        out["description"] = main_text(soup)[:8000]
        meta_date = soup.find("meta", attrs={"property": "article:published_time"})
        tm = soup.find("time", attrs={"datetime": True})
        out.setdefault("published", parse_date(meta_date["content"]) if meta_date else
                       parse_date(tm["datetime"]) if tm else None)
    if not out.get("published"):
        # «Дата публикации: 11 ноября 2026» — так пишут в og:description careerspace и др.
        og = soup.find("meta", attrs={"property": "og:description"})
        m = re.search(r"(?:дата публикации|опубликовано)\s*:?\s*([^.\n]{4,25})", og.get("content", "") if og else "", re.I)
        if m:
            out["published"] = parse_ru_date(m.group(1))
    return out


COMPANY_IN_TITLE = re.compile(r"^(.{2,50}?)\s+(?:ищет|ищут|приглашает|ищем)\s", re.I)


def enrich(v: dict) -> dict:
    if len(v.get("description") or "") < 200:
        d = fetch_detail(v["url"])
        for k, val in d.items():
            if val and (not v.get(k) or k == "description"):
                v[k] = val
        time.sleep(0.6)
    if not v.get("company"):
        m = COMPANY_IN_TITLE.match(v.get("title") or "")
        if m:
            v["company"] = m.group(1).strip(" «»\"")
    return v


# ---------------------------------------------------------------- hh.ru / zarplata.ru
HH_FORMATS = {"REMOTE": "удалённо", "HYBRID": "гибрид", "ON_SITE": "офис", "FIELD_WORK": "разъездной"}
ROSTOV_HH_AREA = "76"


def _hh_period() -> int:
    return next(p for p in (1, 3, 7, 30) if p >= min(config.FRESH_DAYS, 30))


_HH_LOCK = threading.Lock()  # hh.ru и zarplata.ru — одна платформа; параллельные запросы она режет


def hh_like(site, host: str) -> list[dict]:
    with _HH_LOCK:
        return _hh_like(site, host)


def _hh_like(site, host: str) -> list[dict]:
    out: dict[str, dict] = {}
    common = {"text": "дизайнер", "search_field": "name", "professional_role": "34",
              "order_by": "publication_time", "search_period": _hh_period(), "items_on_page": 50}
    for extra in ({"schedule": "remote"}, {"area": ROSTOV_HH_AREA}):
        r = get(f"https://{host}/search/vacancy", params={**common, **extra})
        if not r:
            continue
        m = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>(.*?)</template>', r.text, re.S)
        if not m:
            log.warning("%s: не нашли данные поиска на странице", host)
            continue
        state = json.loads(htmllib.unescape(m.group(1)))
        for v in state.get("vacancySearchResult", {}).get("vacancies", []):
            vid = v.get("vacancyId")
            comp = v.get("compensation") or {}
            fmts = [HH_FORMATS.get(x, x) for f in (v.get("workFormats") or []) for x in f.get("workFormatsElement", [])]
            if not fmts and v.get("@workSchedule") == "remote":
                fmts = ["удалённо"]
            out[str(vid)] = new_vac(
                key=f"hh:{vid}",
                url=f"https://{host}/vacancy/{vid}",
                source=site["name"],
                title=v.get("name", ""),
                company=(v.get("company") or {}).get("visibleName") or (v.get("company") or {}).get("name", ""),
                salary=fmt_salary(comp.get("from"), comp.get("to"), comp.get("currencyCode"),
                                  "до вычета" if comp.get("gross") else "на руки") if comp.get("from") or comp.get("to") else "",
                location=(v.get("area") or {}).get("name", ""),
                work_format=", ".join(dict.fromkeys(fmts)),
                published=parse_date((v.get("publicationTime") or {}).get("$")),
            )
        time.sleep(0.8)
    return list(out.values())


def hh(site):
    return hh_like(site, "hh.ru")


def zarplata(site):
    return hh_like(site, "zarplata.ru")


# ---------------------------------------------------------------- Хабр Карьера
def habr(site) -> list[dict]:
    out = {}
    for q in ("графический дизайнер", "бренд дизайнер", "дизайнер"):
        r = get("https://career.habr.com/vacancies", params={"q": q, "type": "all", "sort": "date"})
        if not r:
            continue
        sc = BeautifulSoup(r.text, "html.parser").find("script", attrs={"data-ssr-state": True})
        if not sc:
            continue
        for v in json.loads(sc.string).get("vacancies", {}).get("list", []):
            sal = v.get("salary") or {}
            locs = [l.get("title", "") for l in (v.get("locations") or []) if isinstance(l, dict)]
            out[v["id"]] = new_vac(
                key=f"habr:{v['id']}",
                url=urljoin("https://career.habr.com", v.get("href", "")),
                source=site["name"],
                title=v.get("title", ""),
                company=(v.get("company") or {}).get("title", ""),
                salary=sal.get("formatted", "") or "",
                location=", ".join(locs),
                work_format="удалённо" if v.get("remoteWork") else "",
                published=parse_date((v.get("publishedDate") or {}).get("date")),
                snippet=", ".join(s.get("title", "") for s in (v.get("skills") or [])),
            )
        time.sleep(0.8)
    return list(out.values())


# ---------------------------------------------------------------- Работа России
def trudvsem(site) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=config.FRESH_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    out = {}
    for text in ("графический дизайнер", "дизайнер"):
        r = get("https://opendata.trudvsem.ru/api/v1/vacancies",
                params={"text": text, "limit": 100, "modifiedFrom": since})
        if not r:
            continue
        try:
            items = r.json().get("results", {}).get("vacancies", []) or []
        except ValueError:
            continue
        for it in items:
            v = it.get("vacancy", {})
            req = v.get("requirement") or {}
            desc = "\n".join(x for x in [
                html_to_text(v.get("duty") or ""),
                "Требования: " + html_to_text(req.get("qualification") or "") if req.get("qualification") else "",
                f"Опыт: {req.get('experience')} г." if req.get("experience") is not None else "",
                f"Условия: {v.get('employment', '')}, {v.get('schedule', '')}",
            ] if x)
            emp = (v.get("employment") or "").lower()
            out[v.get("id")] = new_vac(
                key=f"trud:{v.get('id')}",
                url=v.get("vac_url", ""),
                source=site["name"],
                title=v.get("job-name", ""),
                company=(v.get("company") or {}).get("name", ""),
                salary=fmt_salary(v.get("salary_min"), v.get("salary_max"), "₽"),
                location=(v.get("region") or {}).get("name", ""),
                work_format="удалённо" if "дистанц" in emp or "удал" in emp else "",
                published=parse_date(v.get("date_modify")) or parse_date(v.get("creation-date")),
                description=desc,
            )
        time.sleep(0.8)
    return list(out.values())


# ---------------------------------------------------------------- SuperJob
def superjob(site) -> list[dict]:
    urls: dict[str, None] = {}
    for page in ("https://russia.superjob.ru/vakansii/dizajner-graficheskij.html",
                 "https://russia.superjob.ru/vakansii/dizajner.html"):
        r = get(page)
        if not r:
            continue
        for u in re.findall(r'https://[a-z]+\.superjob\.ru/vakansii/[a-z0-9-]+-\d+\.html', r.text):
            urls[u.replace("://russia.", "://www.").replace("://taganrog.", "://www.")] = None
        time.sleep(0.8)
    out = []
    for u in urls:
        slug = u.rsplit("/", 1)[-1]
        if not re.search(r"dizajn|design|verst|illjustr|brend", slug):
            continue
        sid = re.search(r"-(\d+)\.html", u).group(1)
        out.append(new_vac(key=f"sj:{sid}", url=u, source=site["name"]))
    return out


# ---------------------------------------------------------------- Карьерист
def careerist(site) -> list[dict]:
    out = {}
    for text in ("графический дизайнер", "дизайнер"):
        r = get("https://careerist.ru/search/", params={"category": "vacancy", "text": text,
                                                         "onlytitle": 1, "sort_mode": "time"})
        if not r:
            continue
        for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=re.compile(r"careerist\.ru/vakansii/.+-\d+\.html")):
            title = a.get_text(" ", strip=True)
            out[a["href"]] = new_vac(url=a["href"], source=site["name"], title=title)
        time.sleep(0.8)
    return list(out.values())


# ---------------------------------------------------------------- remote-job.ru
def remote_job(site) -> list[dict]:
    out = {}
    for q in ("графический дизайнер", "дизайнер"):
        r = get("https://remote-job.ru/search", params={"search[query]": q, "search[sort]": "1"})
        if not r:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".vacancy_item"):
            a = item.find("a", href=re.compile(r"^/vacancy/show/"))
            if not a:
                continue
            text = item.get_text(" | ", strip=True)
            url = urljoin("https://remote-job.ru", a["href"])
            sal = re.search(r"(от\s*[\d\s]+(?:до\s*[\d\s]+)?руб\.?|до\s*[\d\s]+руб\.?)", text)
            # карточка: «Название | дата, | Компания | зарплата | текст…»
            parts = [p.strip(" ,") for p in text.split("|")]
            company = next((p for p in parts[1:4] if p and not re.search(r"\d{4}|руб|^от |^до |^\(", p)
                            and len(p) < 60), "")
            out[url] = new_vac(
                url=url, source=site["name"], company=company,
                title=re.sub(r"\s*\(удал[её]нная работа\)", "", re.sub(r"\s+", " ", a.get_text("")).strip()),
                work_format="удалённо",
                salary=re.sub(r"\s+", " ", sal.group(1)).strip() if sal else "",
                published=parse_ru_date(text),
                snippet=text[:600],
            )
        time.sleep(0.8)
    return list(out.values())


# ---------------------------------------------------------------- hirify / careerspace / designer.ru / любые сайты
def _links_from_listing(site, page_url: str, href_re: str, need_design_title: bool = True) -> list[dict]:
    r = get(page_url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out = {}
    for a in soup.find_all("a", href=re.compile(href_re)):
        url = urljoin(page_url, a["href"]).split("#")[0]
        title = a.get_text(" ", strip=True)
        card = a
        for _ in range(3):
            if card.parent is not None and len(card.parent.get_text(" ", strip=True)) < 900:
                card = card.parent
        card_text = card.get_text(" | ", strip=True)
        if need_design_title and not _has(card_text, candidate.DESIGN_TITLE_WORDS):
            continue
        if need_design_title and _has(card_text.split("|")[0] if len(title) > 100 else title, candidate.EXCLUDE_TITLE):
            continue
        # Текст ссылки на таких сайтах — вся карточка; настоящий заголовок возьмём со страницы вакансии
        out[url] = new_vac(url=url, source=site["name"], title="", snippet=card_text[:600],
                           published=parse_ru_date(card_text))
    return list(out.values())


def hirify(site) -> list[dict]:
    return _links_from_listing(site, site["url"], r"^/jobs/\d+")


# API и адреса с «?» у careerspace закрыты в robots.txt, поэтому читаем только публичные подборки
# (в каждой ~10 свежих вакансий) и страницы самих вакансий /job/ID.
CAREERSPACE_PAGES = [
    "/jobs", "/collection/remote", "/collection/junior", "/collection/junior_marketing_content_production",
    "/collection/brand_marketing", "/collection/digital_marketing", "/collection/motion_design",
    "/collection/ux_ui",
]


def careerspace(site) -> list[dict]:
    out = {}
    for path in CAREERSPACE_PAGES:
        r = get("https://careerspace.app" + path)
        if not r:
            continue
        for a in BeautifulSoup(r.text, "html.parser").select('a.job-card__i[href^="/job/"]'):
            title_el = a.select_one(".job-card__title")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if not title_ok(title):
                continue
            company = a.select_one(".job-card__company-name")
            labels = [x.get_text(" ", strip=True) for x in a.select(".job-lb__tx")]
            salary = next((x for x in labels if re.search(r"\d.*(₽|\$|€)", x)), "")
            fmt = next((x.lower() for x in labels if re.search(r"удал|гибрид|офис", x, re.I)), "")
            city = next((x for x in labels if x not in (salary,) and x.lower() != fmt), "")
            jid = re.search(r"/job/(\d+)", a["href"]).group(1)
            out[jid] = new_vac(
                key=f"cs:{jid}", url=f"https://careerspace.app/job/{jid}", source=site["name"],
                title=title, company=company.get_text(" ", strip=True) if company else "",
                salary=salary.replace("\xa0", " "), location=city,
                work_format="удалённо" if "удал" in fmt else "гибрид" if "гибрид" in fmt else fmt,
            )
        time.sleep(0.7)
    return list(out.values())


def designer_ru(site) -> list[dict]:
    return _links_from_listing(site, "https://designer.ru/vacancy/", r"^/vacancy/[a-z0-9-]{6,}/$")


def generic(site) -> list[dict]:
    """Любой добавленный сайт: ищем ссылки с «дизайнерскими» словами на том же домене."""
    r = get(site["url"])
    if not r:
        return []
    host = urlparse(r.url).netloc
    soup = BeautifulSoup(r.text, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        url = urljoin(r.url, a["href"]).split("#")[0]
        if urlparse(url).netloc != host or url.rstrip("/") == r.url.rstrip("/"):
            continue
        if 5 <= len(title) <= 150 and title_ok(title):
            out[url] = new_vac(url=url, source=site["name"], title=title)
    return list(out.values())


# ---------------------------------------------------------------- Telegram-каналы
VACANCY_MARKERS = ["ваканс", "ищем", "ищет", "требуется", "в команду", "открыта позиция", "hiring",
                   "#работа", "#job", "зарплат", "з/п", "зп ", "оплата", "оклад", "₽", "руб", "откликнуться",
                   "резюме", "портфолио", "условия", "обязанности", "задачи"]


def tg_channel_name(url: str) -> str:
    path = urlparse(url).path.strip("/").split("/")
    return path[1] if path and path[0] == "s" and len(path) > 1 else path[0]


def _tg_title(text: str) -> str:
    for line in text.split("\n"):
        line = re.sub(r"#\S+", "", line)
        line = re.sub(r"[^\w\s«»\"'()/+.,:–—-]", "", line).strip(" -–—:.")
        if len(line) >= 5:
            return line[:120]
    return text[:120]


def telegram(site) -> list[dict]:
    channel = tg_channel_name(site["url"])
    border = datetime.now(MSK) - timedelta(days=config.FRESH_DAYS)
    out = []
    url = f"https://t.me/s/{channel}"
    for _ in range(4):  # до 4 страниц ленты (по ~20 постов)
        r = get(url)
        if not r:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        msgs = soup.select("div.tgme_widget_message[data-post]")
        if not msgs:
            break
        oldest = None
        for m in msgs:
            if "service_message" in (m.get("class") or []):
                continue
            body = m.select_one(".tgme_widget_message_text")
            tm = m.select_one("time[datetime]")
            if not body:
                continue
            text = html_to_text(str(body))
            pub = parse_date(tm["datetime"]) if tm else None
            oldest = pub if oldest is None or (pub and pub < oldest) else oldest
            low = text.lower()
            if not (_has(low, candidate.DESIGN_TITLE_WORDS) and _has(low, VACANCY_MARKERS)):
                continue
            title = _tg_title(text)
            comp = re.search(r"(?:компания|работодатель|company)\s*[:—-]\s*([^\n]{2,60})", text, re.I)
            sal = re.search(r"(?:зарплата|з/п|зп|оплата|оклад|доход|вилка|salary)\s*[:—-]?\s*([^\n]{2,60})", text, re.I)
            post = m["data-post"]
            out.append(new_vac(
                key=f"tg:{post}", url=f"https://t.me/{post}", source=site["name"],
                title=title, company=comp.group(1).strip() if comp else "",
                salary=sal.group(1).strip() if sal else "",
                published=pub, description=text[:6000],
                work_format="удалённо" if _has(low, candidate.REMOTE_WORDS) else
                            "гибрид" if _has(low, candidate.HYBRID_WORDS) else "",
            ))
        first_id = msgs[0]["data-post"].split("/")[-1]
        if oldest and oldest < border:
            break
        url = f"https://t.me/s/{channel}?before={first_id}"
        time.sleep(0.8)
    return out


# ---------------------------------------------------------------- реестр
ADAPTERS = {
    "hh": hh, "zarplata": zarplata, "habr": habr, "trudvsem": trudvsem, "superjob": superjob,
    "careerist": careerist, "remote_job": remote_job, "hirify": hirify, "careerspace": careerspace,
    "designer_ru": designer_ru, "telegram": telegram, "generic": generic,
}
KNOWN_DOMAINS = {
    "hh.ru": "hh", "zarplata.ru": "zarplata", "career.habr.com": "habr", "trudvsem.ru": "trudvsem",
    "superjob.ru": "superjob", "careerist.ru": "careerist", "remote-job.ru": "remote_job",
    "hirify.me": "hirify", "careerspace.app": "careerspace", "designer.ru": "designer_ru",
    "t.me": "telegram", "telegram.me": "telegram",
}


def detect_kind(url: str) -> str:
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")
    for dom, kind in KNOWN_DOMAINS.items():
        if host == dom or host.endswith("." + dom):
            return kind
    return "generic"


def normalize_url(url: str) -> str:
    url = url.strip()
    if url.startswith("@"):
        url = "https://t.me/" + url[1:]
    if "://" not in url:
        url = "https://" + url
    return url


def collect_site(site) -> list[dict]:
    fn = ADAPTERS.get(site["kind"], generic)
    try:
        items = fn(site)
    except Exception:  # один сломанный сайт не должен ронять всю выгрузку
        log.exception("Сайт %s упал при сборе", site["name"])
        return []
    log.info("%s: найдено %d", site["name"], len(items))
    return items
