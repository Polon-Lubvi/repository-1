"""Краткое описание, «чем интересна» и сопроводительное письмо.

Режим 1 — Claude API (если задан ANTHROPIC_API_KEY): пишет тексты сам, а в качестве образцов
получает письма, которые кандидат исправила и прислала боту, + сводку её стиля.
Режим 2 — шаблоны: письмо собирается из фраз под интересы вакансии; если есть присланные
письма — берётся самое похожее и подставляются название вакансии и компания.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from . import candidate, config, scoring, storage

log = logging.getLogger(__name__)

_client = None


def llm_enabled() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# ------------------------------------------------------------------ похожие примеры
def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-zа-яё]{4,}", (s or "").lower())}


def similar_examples(v: dict, k: int = 3) -> list[dict]:
    exs = storage.list_examples()
    if not exs:
        return []
    vc, vw = set(v.get("categories") or []), _words(v.get("title", "") + " " + v.get("description", "")[:1500])

    def sim(ex):
        ec, ew = set(ex.get("keywords") or []), _words(ex.get("title", "") + " " + ex.get("vacancy_text", "")[:1500])
        jc = len(vc & ec) / len(vc | ec) if vc | ec else 0
        jw = len(vw & ew) / len(vw | ew) if vw | ew else 0
        return jc * 0.6 + jw * 0.4

    exs.sort(key=sim, reverse=True)
    return exs[:k]


# ------------------------------------------------------------------ Claude
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2–3 предложения: компания, чем заниматься, условия"},
        "why_interesting": {"type": "string", "description": "2–4 пункта через перенос строки, начинающихся с «• »"},
        "cover_letter": {"type": "string"},
    },
    "required": ["summary", "why_interesting", "cover_letter"],
    "additionalProperties": False,
}


def _system_prompt() -> str:
    notes = storage.get_setting("style_notes", "") or ""
    style = ("\nСТИЛЬ, КОТОРЫЙ ОНА ПРЕДПОЧИТАЕТ (выведен из её правок — соблюдай в первую очередь)\n" + notes
             if notes else "")
    return f"""Ты помогаешь графическому дизайнеру искать работу: кратко описываешь вакансию, объясняешь,
чем она ей интересна, и пишешь сопроводительное письмо от её имени.

РЕЗЮМЕ
{candidate.RESUME}

ИНТЕРЕСЫ
{candidate.INTERESTS}

Портфолио: {candidate.PORTFOLIO} (запасная ссылка: {candidate.PORTFOLIO_ALT})
Контакты: {candidate.CONTACTS}

ПРАВИЛА ДЛЯ ПИСЬМА
- Русский язык, от первого лица, женский род, обращение «Здравствуйте!».
- 90–160 слов. Без канцелярита, штампов («я коммуникабельна», «стрессоустойчива») и выдумок.
- Опираться только на факты из резюме; выбрать 1–2 самых подходящих под вакансию.
- Связать задачи вакансии с её опытом конкретно: что делала, сколько, для кого.
- Упомянуть ссылку на портфолио, закончить предложением созвониться или сделать тестовое.
- Если вакансия про маркетплейсы/карточки, senior-уровень или офис не в Ростове — всё равно
  пиши письмо, но в why_interesting честно отметь минус строкой «⚠ ...».
- В why_interesting ссылайся на её интересы и опыт, без общих слов.
{style}"""


def _examples_block(v: dict) -> str:
    exs = similar_examples(v)
    if not exs:
        return ""
    parts = ["Вот письма, которые она сама переписала для похожих вакансий. "
             "Повтори её тон, структуру и длину, но не копируй фразы про чужую компанию.\n"]
    for i, ex in enumerate(exs, 1):
        parts.append(f"<example {i}>\nВакансия: {ex['title']} — {ex['company']}\n"
                     f"Черновик бота:\n{ex['bot_letter'] or '—'}\n"
                     f"Её вариант (эталон):\n{ex['user_letter']}\n</example {i}>")
    return "\n\n".join(parts)


def _vacancy_block(v: dict) -> str:
    return (f"ВАКАНСИЯ\nНазвание: {v.get('title')}\nКомпания: {v.get('company') or 'не указана'}\n"
            f"Зарплата: {v.get('salary') or 'не указана'}\nФормат/город: {v.get('work_format') or '?'} / "
            f"{v.get('location') or '?'}\nИсточник: {v.get('source')}\nОписание:\n"
            f"{(v.get('description') or v.get('snippet') or '')[:6000]}")


def _llm_text(resp) -> str:
    if resp.stop_reason == "refusal":
        raise RuntimeError("модель отказалась отвечать")
    return next(b.text for b in resp.content if b.type == "text")


def llm_generate(v: dict) -> dict:
    user = "\n\n".join(x for x in [_examples_block(v), _vacancy_block(v),
                                   "Верни JSON: summary, why_interesting, cover_letter."] if x)
    resp = client().beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4000,
        system=_system_prompt(),
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    return json.loads(_llm_text(resp))


def update_style_notes() -> str:
    """Сравнивает черновики бота с её правками и сохраняет краткую памятку стиля."""
    exs = storage.list_examples()[:15]
    if not exs or not llm_enabled():
        return ""
    pairs = "\n\n".join(f"<pair>\nВакансия: {e['title']} — {e['company']}\nЧерновик бота:\n{e['bot_letter'] or '—'}\n"
                        f"Как она переписала:\n{e['user_letter']}\n</pair>" for e in exs)
    resp = client().beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2000,
        system="Ты анализируешь, как соискатель правит сопроводительные письма, чтобы следующие черновики "
               "сразу были в её стиле.",
        messages=[{"role": "user", "content":
                   pairs + "\n\nСформулируй 5–10 коротких правил её стиля: длина, обращение, структура, "
                           "что она добавляет, что убирает, любимые формулировки, чего избегать. "
                           "Только список правил, каждое с новой строки и с «- »."}],
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    notes = _llm_text(resp).strip()
    storage.set_setting("style_notes", notes)
    return notes


# ------------------------------------------------------------------ шаблоны
def template_summary(v: dict) -> str:
    desc = re.sub(r"\s+", " ", v.get("description") or v.get("snippet") or "").strip()
    head = []
    if v.get("company"):
        head.append(v["company"])
    if v.get("work_format") or v.get("location"):
        head.append(" / ".join(x for x in [v.get("work_format"), v.get("location")] if x))
    if v.get("salary"):
        head.append(v["salary"])
    short = desc[:350].rsplit(" ", 1)[0] + "…" if len(desc) > 350 else desc
    return (" · ".join(head) + ("\n" if head else "") + short).strip()


INTRO_BY_CAT = {
    "identity": "Мне особенно близки айдентика и визуальные системы: мой логотип для АНО «Самое время» "
                "победил в конкурсе, а в онлайн-школе я веду весь визуал в рамках фирменного стиля.",
    "branding": "Мне интересен брендинг целиком — от идеи и характера бренда до носителей и гайдлайнов; "
                "в работе держу единый стиль во всех материалах.",
    "editorial": "У меня большой опыт многостраничной вёрстки: за последние месяцы я сделала 16 презентаций "
                 "и 10 учебно-методических пособий объёмом до 200 страниц.",
    "advertising": "Люблю задачи, где нужна креативная идея: делала визуалы для продвижения онлайн-школы, "
                   "обложку сингла и оформление услуг психолога на Avito.",
    "digital": "Работаю с digital-контентом: вместе с SMM-командой сделала более 250 карточек для соцсетей "
               "и шаблоны рубрик, которые команда использует каждый день.",
    "education": "Мне близки образовательные и социальные проекты — сейчас я единственный дизайнер "
                 "в онлайн-школе и делала работы для НКО и ЮФУ.",
}


def template_letter(v: dict) -> str:
    company = v.get("company") or ""
    title = v.get("title") or "графического дизайнера"
    exs = similar_examples(v, 1)
    if exs and exs[0].get("user_letter"):
        letter = exs[0]["user_letter"]
        if exs[0].get("title"):
            letter = letter.replace(exs[0]["title"], title)
        if exs[0].get("company") and company:
            letter = letter.replace(exs[0]["company"], company)
        return letter
    body = [INTRO_BY_CAT[k] for k in (v.get("categories") or [])[:2]] or [INTRO_BY_CAT["editorial"]]
    where = f" ({company})" if company else ""
    return (
        f"Здравствуйте!\n\n"
        f"Меня зовут {candidate.FIRST_NAME}, я графический дизайнер из города {candidate.CITY}. "
        f"Откликаюсь на вакансию «{title}»{where}.\n\n"
        + " ".join(body) +
        "\n\nРаботаю в Figma, Photoshop, Illustrator и InDesign, спокойно отношусь к правкам и соблюдаю сроки. "
        f"Портфолио: {candidate.PORTFOLIO}\n\n"
        "Буду рада созвониться и обсудить задачи — готова выполнить тестовое задание.\n\n"
        f"{candidate.NAME}\n{candidate.CONTACTS}"
    )


# ------------------------------------------------------------------ общий вход
def fill_texts(vacs: list[dict]) -> list[dict]:
    """Добавляет summary, why, letter каждой вакансии."""
    def one(v):
        if llm_enabled():
            try:
                res = llm_generate(v)
                v["summary"], v["why"], v["letter"] = res["summary"], res["why_interesting"], res["cover_letter"]
                return v
            except Exception:
                log.exception("Claude не ответил для %s — использую шаблон", v.get("url"))
        v["summary"] = template_summary(v)
        v["why"] = scoring.why_interesting(v)
        v["letter"] = template_letter(v)
        return v

    with ThreadPoolExecutor(max_workers=4 if llm_enabled() else 1) as ex:
        return list(ex.map(one, vacs))
