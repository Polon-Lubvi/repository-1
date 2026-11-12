"""SQLite: сайты, уже отправленные вакансии, примеры для обучения, чаты, настройки."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vacancies (
    key TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    source TEXT, title TEXT, company TEXT, description TEXT,
    summary TEXT, why TEXT, letter TEXT,
    score REAL, sent_at TEXT
);
CREATE INDEX IF NOT EXISTS vacancies_url ON vacancies(url);
CREATE TABLE IF NOT EXISTS examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_url TEXT UNIQUE,
    title TEXT, company TEXT, vacancy_text TEXT,
    bot_letter TEXT, user_letter TEXT NOT NULL,
    keywords TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init() -> None:
    with db() as c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM sites").fetchone()[0] == 0:
            for s in json.loads(config.DEFAULT_SITES_FILE.read_text(encoding="utf-8")):
                c.execute("INSERT OR IGNORE INTO sites(name,url,kind,enabled,added_at) VALUES (?,?,?,1,?)",
                          (s["name"], s["url"], s["kind"], now()))


# ---------- сайты ----------
def list_sites(only_enabled: bool = False) -> list[sqlite3.Row]:
    q = "SELECT * FROM sites" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY id"
    with db() as c:
        return c.execute(q).fetchall()


def add_site(name: str, url: str, kind: str) -> tuple[int, bool]:
    """Возвращает (id, создан_ли_новый). Если сайт был выключен — включает."""
    with db() as c:
        row = c.execute("SELECT id FROM sites WHERE url=?", (url,)).fetchone()
        if row:
            c.execute("UPDATE sites SET enabled=1, name=?, kind=? WHERE id=?", (name, kind, row["id"]))
            return row["id"], False
        cur = c.execute("INSERT INTO sites(name,url,kind,enabled,added_at) VALUES (?,?,?,1,?)",
                        (name, url, kind, now()))
        return cur.lastrowid, True


def set_site_enabled(site_id: int, enabled: bool) -> bool:
    with db() as c:
        return c.execute("UPDATE sites SET enabled=? WHERE id=?", (int(enabled), site_id)).rowcount > 0


# ---------- вакансии ----------
def seen_keys() -> set[str]:
    with db() as c:
        return {r[0] for r in c.execute("SELECT key FROM vacancies")}


def save_sent(items: list[dict]) -> None:
    with db() as c:
        for v in items:
            c.execute(
                "INSERT OR REPLACE INTO vacancies(key,url,source,title,company,description,summary,why,letter,score,sent_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (v["key"], v["url"], v["source"], v["title"], v.get("company", ""), v.get("description", "")[:20000],
                 v.get("summary", ""), v.get("why", ""), v.get("letter", ""), v.get("score", 0), now()))


def vacancy_by_url(url: str):
    with db() as c:
        return c.execute("SELECT * FROM vacancies WHERE url=?", (url,)).fetchone()


# ---------- обучение ----------
def save_example(ex: dict) -> bool:
    """True — новый пример, False — обновили существующий."""
    with db() as c:
        existed = c.execute("SELECT 1 FROM examples WHERE vacancy_url=?", (ex["vacancy_url"],)).fetchone()
        c.execute(
            "INSERT OR REPLACE INTO examples(vacancy_url,title,company,vacancy_text,bot_letter,user_letter,keywords,created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (ex["vacancy_url"], ex.get("title", ""), ex.get("company", ""), ex.get("vacancy_text", "")[:8000],
             ex.get("bot_letter", ""), ex["user_letter"], json.dumps(ex.get("keywords", []), ensure_ascii=False), now()))
        return not existed


def list_examples() -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT * FROM examples ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["keywords"] = json.loads(d.get("keywords") or "[]")
        out.append(d)
    return out


# ---------- чаты и настройки ----------
def add_chat(chat_id: int) -> None:
    with db() as c:
        c.execute("INSERT OR IGNORE INTO chats(chat_id, added_at) VALUES (?,?)", (chat_id, now()))


def list_chats() -> list[int]:
    with db() as c:
        return [r[0] for r in c.execute("SELECT chat_id FROM chats")]


def get_setting(key: str, default: str | None = None) -> str | None:
    with db() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default


def set_setting(key: str, value: str) -> None:
    with db() as c:
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key, value))


def stats() -> dict:
    with db() as c:
        return {
            "sent": c.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0],
            "examples": c.execute("SELECT COUNT(*) FROM examples").fetchone()[0],
            "sites": c.execute("SELECT COUNT(*) FROM sites WHERE enabled=1").fetchone()[0],
        }
