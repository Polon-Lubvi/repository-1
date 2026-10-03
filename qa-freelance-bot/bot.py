"""QA-фриланс монитор: собирает заказы с бирж, фильтрует по QA/тестированию
и шлёт новые в Telegram.

Режимы:
  python bot.py                 один проход (для GitHub Actions / планировщика)
  python bot.py --loop          бесконечный цикл, проход раз в CHECK_INTERVAL секунд
  python bot.py --dry-run       один проход без отправки, печатает найденное
  python bot.py --get-chat-id   показать chat_id тех, кто написал боту
  python bot.py --mark-seen     пометить всё текущее просмотренным, ничего не слать
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "seen.json"
MAX_SEEN = 5000
INIT = "__init__:"  # метка в seen.json: источник уже встречался
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

# --- Фильтр ---------------------------------------------------------------
# Заказ подходит, если хоть одно из этих слов есть в ЗАГОЛОВКЕ...
KEYWORDS = [
    r"\bqa\b", r"\bq\.a\.", r"\bsdet\b", r"\baqa\b", r"\bqc\b", r"quality (assurance|control)",
    r"тестир", r"тестиров", r"тестировщик", r"протестир", r"потестит", r"протестит",
    r"автотест", r"тест[- ]?кейс", r"чек[- ]?лист\w* для тест", r"баг[- ]?репорт", r"регресс\w* тест",
    r"нагрузочн\w* тест", r"юзабилити[- ]тест", r"поиск баг", r"найти баг",
    r"\btest(ing|er|ers)?\b", r"test[- ]?cases?", r"bug[- ]?report", r"\bbug hunt",
    r"selenium", r"playwright", r"cypress", r"appium", r"\bjmeter\b", r"\bpostman\b",
    r"\bpytest\b", r"testrail", r"\bk6\b", r"load testing", r"smoke test",
]
# ...или если в ОПИСАНИИ есть явный признак QA-заказа (просто «testing» в описании
# dev-заказа — не признак: там почти всегда «разработка, тестирование, деплой»).
STRONG = [
    r"тестировщик", r"нуж\w* (провести |сделать )?(ручное |функциональное )?тестирование",
    r"провести тестирование", r"протестировать (наш |мой )?(сайт|приложение|бот|игру|сервис|api)",
    r"qa[- ](engineer|tester|specialist|инженер|специалист)", r"manual (qa|tester|testing)",
    r"(looking for|need|hire)\w* (a |an )?(qa|tester|testers)", r"beta[- ]?test(er|ers|ing)",
    r"write (test cases|automated tests|autotests)", r"написать автотест", r"баг[- ]?репорт",
]
# Фразы, которые вырезаются перед проверкой — «тест» в них не про QA.
EXCLUDE = [
    r"тестов\w* задани\w*", r"тестов\w* период\w*", r"тестов\w* статья", r"тест[- ]?драйв\w*",
    r"тестов\w* текст\w*", r"тестов\w* перевод\w*", r"тестов\w* (рисун\w*|макет\w*|ролик\w*|видео)",
    r"test (task|assignment|article|translation|drive)", r"paid test", r"a/b[- ]?тест\w*", r"a/b[- ]?test\w*",
    r"тестирование гипотез", r"(covid|пцр|днк|генетическ\w*)[- ]?тест\w*",
]
KW_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE)
EX_RE = re.compile("|".join(EXCLUDE), re.IGNORECASE)
STRONG_RE = re.compile("|".join(STRONG), re.IGNORECASE)
# Пост в профильном канале считаем заказом/вакансией, только если похоже на объявление, а не на статью.
OFFER_RE = re.compile(r"ваканси|ищем|ищу|требует|нуж[еа]н|зарплат|з/п|оплат|бюджет|заказ|удал[её]нн?|офис|гибрид|"
                      r"engineer|hiring|salary|remote|\$|₽|€|usd", re.IGNORECASE)


@dataclass
class Job:
    source: str
    id: str
    title: str
    url: str
    description: str = ""
    budget: str = ""
    loose: bool = False  # профильный QA-источник: ключевое слово может быть где угодно в тексте
    title_only: bool = False  # общий канал вакансий: тестировщиков упоминают и в чужих вакансиях

    @property
    def key(self):
        return f"{self.source}:{self.id}"

    @property
    def fingerprint(self):
        """Одна и та же вакансия, опубликованная в нескольких каналах, даёт один отпечаток."""
        text = re.sub(r"\W+", "", f"{self.title} {self.description[:200]}".lower())
        return "fp:" + hashlib.sha1(text.encode()).hexdigest()[:12]


def is_qa(job: Job) -> bool:
    title = EX_RE.sub(" ", job.title)
    desc = EX_RE.sub(" ", job.description)
    if job.title_only:
        return bool(KW_RE.search(title))
    if job.loose:
        return bool((KW_RE.search(title) or KW_RE.search(desc)) and OFFER_RE.search(f"{title} {desc}"))
    return bool(KW_RE.search(title) or STRONG_RE.search(desc))


# --- HTTP / утилиты --------------------------------------------------------
def fetch(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s)).strip()


def rss_items(url):
    root = ET.fromstring(fetch(url).encode("utf-8"))
    for it in root.iter("item"):
        yield {t: (it.findtext(t) or "").strip() for t in ("title", "link", "description", "guid")}


# --- Источники -------------------------------------------------------------
def src_fl():
    for it in rss_items("https://www.fl.ru/rss/all.xml"):
        m = re.search(r"/projects/(\d+)", it["link"])
        title, budget = it["title"], ""
        b = re.search(r"\s*\(Бюджет:\s*([^)]*)\)\s*$", title)
        if b:
            title, budget = title[: b.start()], html.unescape(b.group(1)).strip()
        yield Job("FL.ru", m.group(1) if m else it["link"], html.unescape(title), it["link"],
                  strip_tags(it["description"]), budget)


def src_freelancehunt():
    for it in rss_items("https://freelancehunt.com/projects.rss"):
        m = re.search(r"/project/[^/]*?(\d+)\.html", it["link"]) or re.search(r"(\d+)", it["link"])
        title, budget = it["title"], ""
        b = re.search(r"\s+-\s+(\d[\d\s]*\s?[A-Z₴$€]{1,4})$", title)
        if b:
            title, budget = title[: b.start()], b.group(1)
        yield Job("Freelancehunt", m.group(1) if m else it["link"], title, it["link"],
                  strip_tags(it["description"]), budget)


def src_kwork():
    seen = set()
    for q in ("тестирование", "тестировщик", "QA", "автотесты"):
        page = fetch("https://kwork.ru/projects?keyword=" + urllib.parse.quote(q))
        i = page.find('"wantsListData":')
        if i < 0:
            continue
        data, _ = json.JSONDecoder().raw_decode(page[i + len('"wantsListData":'):])
        for w in data.get("pagination", {}).get("data", []):
            if w["id"] in seen:
                continue
            seen.add(w["id"])
            price = w.get("priceLimit") or ""
            budget = f"до {float(price):,.0f} ₽".replace(",", " ") if price else ""
            yield Job("Kwork", str(w["id"]), w.get("name", ""), f"https://kwork.ru/projects/{w['id']}/view",
                      strip_tags(w.get("description", "")), budget)
        time.sleep(1)


def src_freelance_ru():
    page = fetch("https://freelance.ru/task")
    for card in re.findall(r'<article class="task-card">(.*?)</article>', page, re.S):
        m = re.search(r'href="/task/view/(\d+)"[^>]*>(.*?)</a>', card, re.S)
        if not m:
            continue
        d = re.search(r'<p class="task-card__desc">(.*?)</p>', card, re.S)
        yield Job("Freelance.ru", m.group(1), strip_tags(m.group(2)), f"https://freelance.ru/task/view/{m.group(1)}",
                  strip_tags(d.group(1)) if d else "")


def src_weblancer():
    page = fetch("https://www.weblancer.net/freelance/")
    for m in re.finditer(r'<h2[^>]*><a[^>]*href="(/freelance/[^"]*-(\d+)/)"[^>]*>(.*?)</a></h2>(.*?)</p>', page, re.S):
        tail = m.group(4)
        price = re.search(r'text-green-600[^>]*>(.*?)</span>', tail, re.S)
        desc = re.search(r"<p[^>]*>(.*)$", tail, re.S)
        yield Job("Weblancer", m.group(2), strip_tags(m.group(3)), "https://www.weblancer.net" + m.group(1),
                  strip_tags(desc.group(1)) if desc else "", strip_tags(price.group(1)) if price else "")


def src_freelancer_com():
    seen = set()
    for q in ("qa testing", "software testing", "manual testing", "test automation"):
        url = ("https://www.freelancer.com/api/projects/0.1/projects/active/?limit=30&full_description=true"
               "&sort_field=time_updated&query=" + urllib.parse.quote(q))
        for p in json.loads(fetch(url))["result"]["projects"]:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            b, cur = p.get("budget") or {}, (p.get("currency") or {}).get("code", "")
            budget = f"{b.get('minimum', '')}–{b.get('maximum', '')} {cur}".strip("– ") if b else ""
            yield Job("Freelancer.com", str(p["id"]), p["title"], f"https://www.freelancer.com/projects/{p['seo_url']}",
                      p.get("description") or p.get("preview_description") or "", budget)
        time.sleep(1)


def src_peopleperhour():
    seen = set()
    for path in ("technology-programming/software-testing", "technology-programming"):
        page = fetch("https://www.peopleperhour.com/freelance-jobs/" + path)
        # цена в карточке стоит перед заголовком, поэтому запоминаем последнюю встреченную
        price, pos = "", 0
        for m in re.finditer(r'card__price[^>]*>.*?<span>([^<]+)</span>|<h6 class="item__title[^"]*">'
                             r'<a[^>]*href="([^"]+-(\d+))">(.*?)</a></h6>\s*<p class="item__desc[^"]*">(.*?)</p>', page, re.S):
            if m.group(1):
                price = m.group(1)
                continue
            if m.group(3) not in seen:
                seen.add(m.group(3))
                yield Job("PeoplePerHour", m.group(3), strip_tags(m.group(4)), m.group(2), strip_tags(m.group(5)), price)
            price = ""
        time.sleep(1)


def src_guru():
    seen = set()
    for path in ("c/programming-development/", ""):
        page = fetch("https://www.guru.com/d/jobs/" + path)
        for card in re.split(r'<div class="record jobRecord"', page)[1:]:
            m = re.search(r'<h2 class="jobRecord__title[^"]*">\s*<a[^>]*href="/jobs/([^"/]+)/(\d+)[^"]*">(.*?)</a>', card, re.S)
            if not m or m.group(2) in seen:
                continue
            seen.add(m.group(2))
            d = re.search(r'<p class="jobRecord__desc"[^>]*>(.*?)</p>', card, re.S)
            b = re.search(r'<div class="jobRecord__budget">(.*?)</div>', card, re.S)
            yield Job("Guru", m.group(2), strip_tags(m.group(3)), f"https://www.guru.com/jobs/{m.group(1)}/{m.group(2)}",
                      strip_tags(d.group(1)) if d else "", strip_tags(b.group(1)) if b else "")
        time.sleep(1)


# Telegram-каналы читаются через публичное веб-превью t.me/s/<канал>, без бота и авторизации.
TG_QA_CHANNELS = [      # профильные: каждый пост про QA
    "forallqa",         # Job for QA, ~23K
    "ingamejob_qa",     # QA and Testing в геймдеве (InGameJob), ~12K
    "qa_jobs_rabota",   # Вакансии QA Engineer / тестировщикам, ~6K
    "qa_rabota",        # QA_Jobs, ~1K
]
TG_GENERAL_CHANNELS = [  # общие IT / фриланс: берём только QA-посты
    "jobforjunior",     # Job for Junior, ~85K
    "Remoteit",         # Remote IT, ~51K
    "geekjobs",         # Job in IT & Digital, ~51K
    "habr_career",      # Хабр Карьера, ~33K
    "vakansii_it",      # Вакансии айти, ~28K
    "FreeWorkFeed",     # фриланс и удалёнка, ~24K
    "Getitrussia",      # Get IT, ~21K
    "remote_w0rk",      # Удалёнка, ~15K
]


def tg_channel(channel, loose):
    page = fetch(f"https://t.me/s/{channel}")
    for block in re.split(r'<div class="tgme_widget_message_wrap', page)[1:]:
        post = re.search(r'data-post="([^"]+)/(\d+)"', block)
        text = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        if not post or not text:
            continue
        body = strip_tags(text.group(1))
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        if not lines:
            continue
        # у дайджестов первая строка — хэштег, заголовок берём со следующей
        head = next((l for l in lines if not l.startswith("#")), lines[0])
        title = head[:120]
        yield Job(f"Telegram @{channel}", post.group(2), title, f"https://t.me/{post.group(1)}/{post.group(2)}",
                  " ".join(lines[1:]), loose=loose, title_only=not loose)


def src_telegram():
    for channel in TG_QA_CHANNELS + TG_GENERAL_CHANNELS:
        try:
            yield from tg_channel(channel, loose=channel in TG_QA_CHANNELS)
        except Exception as e:
            print(f"  ! @{channel}: {e!r}", file=sys.stderr)
        time.sleep(0.5)


SOURCES = [src_fl, src_freelancehunt, src_kwork, src_freelance_ru, src_weblancer, src_freelancer_com,
           src_peopleperhour, src_guru, src_telegram]


# --- Состояние и Telegram ---------------------------------------------------
def load_env():
    env = BASE_DIR / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def load_seen():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []


def save_seen(seen):
    marks = [k for k in seen if k.startswith(INIT)]  # метки источников не вытесняются старыми заказами
    jobs = [k for k in seen if not k.startswith(INIT)]
    STATE_FILE.write_text(json.dumps(marks + jobs[-MAX_SEEN:], ensure_ascii=False, indent=0), encoding="utf-8")


def tg(method, **params):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    body = urllib.parse.urlencode(params).encode()
    return json.loads(fetch(f"https://api.telegram.org/bot{token}/{method}", data=body))


def format_job(job: Job):
    desc = re.sub(r"\s+", " ", job.description)
    if len(desc) > 350:
        desc = desc[:350].rsplit(" ", 1)[0] + "…"
    lines = [f"🧪 <b>{html.escape(job.title)}</b>", f"📍 {job.source}" + (f" · 💰 {html.escape(job.budget)}" if job.budget else "")]
    if desc:
        lines.append(html.escape(desc))
    link = "Открыть пост →" if job.source.startswith("Telegram") else "Открыть заказ →"
    lines.append(f'<a href="{html.escape(job.url)}">{link}</a>')
    return "\n".join(lines)


def send(job: Job):
    for attempt in range(3):
        try:
            tg("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=format_job(job),
               parse_mode="HTML", disable_web_page_preview="true")
            return True
        except urllib.error.HTTPError as e:
            if e.code == 429:  # flood control
                time.sleep(int(json.loads(e.read()).get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            print(f"  ! Telegram {e.code}: {e.read()[:200]}", file=sys.stderr)
            return False
    return False


def run_once(dry_run=False, mark_only=False):
    seen = load_seen()
    seen_set = set(seen)
    found = 0
    for src in SOURCES:
        try:
            jobs = list(src())
        except Exception as e:  # один упавший источник не должен ломать остальные
            print(f"[{src.__name__}] ошибка: {e!r}", file=sys.stderr)
            continue
        qa = [j for j in jobs if is_qa(j)]
        new = [j for j in qa if j.key not in seen_set]
        print(f"[{src.__name__}] всего {len(jobs)}, QA {len(qa)}, новых {len(new)}")
        # Новый источник (например, добавленный канал): при первой встрече не шлём его старые
        # посты пачкой, а молча запоминаем — дальше приходят только свежие.
        fresh = {j.source for j in jobs} - {k[len(INIT):] for k in seen_set if k.startswith(INIT)}
        for name in sorted(fresh):
            if not dry_run:
                seen.append(INIT + name)
                seen_set.add(INIT + name)
        for j in new:
            if dry_run:
                print(f"   + {j.source} | {j.title} | {j.budget} | {j.url}")
                continue
            # первая встреча с источником, кросс-пост уже присланной вакансии или --mark-seen: не шлём
            if j.source in fresh or j.fingerprint in seen_set or mark_only or send(j):
                if j.source not in fresh and j.fingerprint not in seen_set and not mark_only:
                    found += 1
                    time.sleep(1.1)
                for k in (j.key, j.fingerprint):
                    if k not in seen_set:
                        seen.append(k)
                        seen_set.add(k)
    if not dry_run:
        save_seen(seen)
    return found


def main():
    for stream in (sys.stdout, sys.stderr):  # консоль Windows (cp1251) не умеет ₽ и эмодзи
        stream.reconfigure(errors="replace")
    load_env()
    args = set(sys.argv[1:])
    if "--get-chat-id" in args:
        updates = tg("getUpdates").get("result", [])
        for u in updates:
            chat = (u.get("message") or u.get("my_chat_member") or {}).get("chat", {})
            print(chat.get("id"), chat.get("username") or chat.get("title"))
        if not updates:
            me = tg("getMe")["result"]["username"]
            print(f"Сообщений пока нет. Откройте https://t.me/{me}, нажмите Start "
                  "или напишите что угодно, затем запустите команду ещё раз.")
        return
    if "--loop" in args:
        interval = int(os.environ.get("CHECK_INTERVAL", "300"))
        while True:
            try:
                print(time.strftime("%Y-%m-%d %H:%M:%S"), "отправлено:", run_once())
            except Exception as e:
                print("ошибка прохода:", repr(e), file=sys.stderr)
            time.sleep(interval)
    n = run_once(dry_run="--dry-run" in args, mark_only="--mark-seen" in args)
    print("готово, обработано новых:", n)


if __name__ == "__main__":
    main()
