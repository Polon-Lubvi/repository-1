"""Полный цикл: сбор → фильтр → оценка → тексты → Excel. И обучение по присланному файлу."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from . import config, excel_io, letters, scoring, sources, storage

log = logging.getLogger(__name__)


def collect(sites=None, limit: int | None = None) -> tuple[list[dict], dict]:
    """Возвращает (вакансии для выгрузки, статистика по источникам)."""
    sites = sites if sites is not None else storage.list_sites(only_enabled=True)
    seen = storage.seen_keys()
    border = datetime.now(sources.MSK) - timedelta(days=config.FRESH_DAYS)
    bonus = scoring.learned_bonus()
    stats: dict[str, dict] = {}

    def run_site(site):
        raw = sources.collect_site(site)
        st = {"found": len(raw), "new": 0, "fit": 0}
        cand = []
        for v in raw:
            if v["key"] in seen or v["url"] in seen:
                continue
            if v["title"] and not sources.title_ok(v["title"]):
                continue
            if v["published"] and v["published"] < border:
                continue
            cand.append(v)
        st["new"] = len(cand)
        # Сначала оцениваем по заголовку/сниппету, описание дочитываем только для лучших
        for v in cand:
            scoring.score(v, bonus)
        cand.sort(key=lambda x: x["score"], reverse=True)
        picked = []
        for v in cand[: config.DETAIL_LIMIT_PER_SOURCE]:
            sources.enrich(v)
            if v["published"] and v["published"] < border:
                continue
            scoring.score(v, bonus)
            if not v["excluded"]:
                picked.append(v)
        st["fit"] = len(picked)
        stats[site["name"]] = st
        return picked

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(run_site, sites))

    # убираем дубли между сайтами (одна вакансия на hh и zarplata, или в двух каналах)
    best: dict[str, dict] = {}
    for v in (v for chunk in results for v in chunk):
        company = (v.get("company") or "").lower().strip()
        k = f"{v['title'].lower().strip()[:60]}|{company[:40]}" if company else v["key"]
        if k not in best or v["score"] > best[k]["score"]:
            best[k] = v
    vacs = sorted(best.values(), key=lambda x: (x["score"], x["published"] or border), reverse=True)
    vacs = vacs[: (limit or config.MAX_VACANCIES)]
    return vacs, stats


def make_report(mark_sent: bool = True, limit: int | None = None) -> tuple[Path | None, list[dict], dict]:
    vacs, stats = collect(limit=limit)
    if not vacs:
        return None, [], stats
    letters.fill_texts(vacs)
    path = config.REPORTS_DIR / f"vakansii_{datetime.now():%Y-%m-%d_%H%M}.xlsx"
    excel_io.build(vacs, path)
    if mark_sent:
        storage.save_sent(vacs)
    return path, vacs, stats


def learn_from_file(path: Path) -> dict:
    rows = excel_io.parse_feedback(path)
    added = updated = 0
    for r in rows:
        stored = storage.vacancy_by_url(r["vacancy_url"])
        text = (stored["description"] if stored and stored["description"] else r["vacancy_text"]) or ""
        r["vacancy_text"] = text
        r["keywords"] = list(scoring.matched_categories(" ".join([r["title"], text])))
        if storage.save_example(r):
            added += 1
        else:
            updated += 1
    notes = ""
    if rows and letters.llm_enabled():
        try:
            notes = letters.update_style_notes()
        except Exception:
            log.exception("Не удалось обновить памятку стиля")
    return {"rows": len(rows), "added": added, "updated": updated, "notes": notes,
            "total": storage.stats()["examples"]}


def test_site(site_like: dict) -> tuple[int, list[str]]:
    """Пробный сбор для /addsite: сколько вакансий нашлось и примеры заголовков."""
    raw = sources.collect_site(site_like)
    titles = [v["title"] for v in raw if v["title"]][:5]
    return len(raw), titles
