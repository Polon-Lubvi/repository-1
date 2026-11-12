"""Собрать выгрузку один раз без Telegram (для проверки).

python -m bot.run_once            — собрать Excel в data/reports (вакансии НЕ помечаются отправленными)
python -m bot.run_once --learn файл.xlsx  — обучиться на файле с вашими письмами
"""
import argparse
import logging
from pathlib import Path

from . import pipeline, storage


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--learn", type=Path, help="Excel с заполненной колонкой «Моё сопроводительное письмо»")
    ap.add_argument("--limit", type=int, default=None, help="максимум вакансий")
    ap.add_argument("--mark-sent", action="store_true", help="пометить вакансии отправленными")
    args = ap.parse_args()
    storage.init()
    if args.learn:
        print(pipeline.learn_from_file(args.learn))
        return
    path, vacs, stats = pipeline.make_report(mark_sent=args.mark_sent, limit=args.limit)
    for name, st in stats.items():
        print(f"{name:<40} найдено {st['found']:>3}  новых {st['new']:>3}  подходит {st['fit']:>3}")
    print(f"\nВ выгрузке: {len(vacs)}  →  {path}")


if __name__ == "__main__":
    main()
