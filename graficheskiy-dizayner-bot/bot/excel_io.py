"""Сборка Excel-выгрузки и чтение файла, который прислали обратно для обучения."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

COL_LINK = "Ссылка"
COL_BOT_LETTER = "Сопроводительное письмо (черновик бота)"
COL_USER_LETTER = "Моё сопроводительное письмо (заполните — бот обучится)"

COLUMNS = [
    ("№", 5),
    ("Дата", 11),
    ("Источник", 16),
    ("Вакансия", 30),
    ("Компания", 20),
    ("Зарплата", 16),
    ("Формат / город", 16),
    ("Подходит, из 10", 10),
    ("Кратко о вакансии", 50),
    ("Чем интересна", 50),
    (COL_LINK, 28),
    (COL_BOT_LETTER, 70),
    (COL_USER_LETTER, 70),
]

HEAD_FILL = PatternFill("solid", fgColor="2F2A4A")
USER_FILL = PatternFill("solid", fgColor="FFF6D6")
THIN = Side(style="thin", color="D0D0D0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _score_fill(score: float) -> PatternFill:
    color = "C8E6C9" if score >= 7 else "FFF3C4" if score >= 5 else "F8D7DA"
    return PatternFill("solid", fgColor=color)


def build(vacs: list[dict], path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Вакансии"
    for i, (name, width) in enumerate(COLUMNS, 1):
        c = ws.cell(row=1, column=i, value=name)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        c.border = BORDER
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[1].height = 45

    for n, v in enumerate(vacs, 1):
        pub = v.get("published")
        fmt_loc = " / ".join(x for x in [v.get("work_format"), v.get("location")] if x)
        row = [n, pub.strftime("%d.%m.%Y") if pub else "", v.get("source", ""), v.get("title", ""),
               v.get("company", ""), v.get("salary", ""), fmt_loc, v.get("score", 0),
               v.get("summary", ""), v.get("why", ""), v.get("url", ""), v.get("letter", ""), ""]
        r = n + 1
        for i, val in enumerate(row, 1):
            c = ws.cell(row=r, column=i, value=val)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = BORDER
        link = ws.cell(row=r, column=11)
        link.hyperlink = v.get("url", "")
        link.font = Font(color="1A56DB", underline="single")
        ws.cell(row=r, column=8).fill = _score_fill(float(v.get("score", 0)))
        ws.cell(row=r, column=8).alignment = Alignment(horizontal="center", vertical="top")
        ws.cell(row=r, column=13).fill = USER_FILL
        ws.row_dimensions[r].height = 260

    ws.freeze_panes = "E2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(vacs) + 1}"

    help_ws = wb.create_sheet("Как пользоваться")
    lines = [
        "Как пользоваться выгрузкой",
        "",
        "1. Вакансии отсортированы по колонке «Подходит, из 10»: зелёные — лучшие совпадения с вашими интересами.",
        "2. «Чем интересна» — почему бот выбрал вакансию; строки с ⚠ — возможные минусы.",
        "3. «Сопроводительное письмо (черновик бота)» — готовый текст, его можно сразу отправлять.",
        "4. Если хотите письмо лучше — впишите свой вариант в жёлтую колонку «Моё сопроводительное письмо».",
        "   Заполнять все строки не нужно: достаточно 1–3 писем.",
        "5. Сохраните файл и отправьте его боту в Telegram. Бот запомнит ваши письма и следующие черновики",
        "   будет писать в вашем стиле. Вакансии, для которых вы писали письмо, бот считает интересными",
        "   и поднимает похожие выше.",
        "",
        f"Файл создан: {datetime.now():%d.%m.%Y %H:%M}",
    ]
    for i, t in enumerate(lines, 1):
        help_ws.cell(row=i, column=1, value=t).font = Font(bold=(i == 1), size=13 if i == 1 else 11)
    help_ws.column_dimensions["A"].width = 120

    wb.save(path)
    return path


def _norm(s) -> str:
    return " ".join(str(s or "").split()).lower()


def parse_feedback(path: Path) -> list[dict]:
    """Читает присланный файл и возвращает строки, где заполнено «Моё сопроводительное письмо».
    Колонки ищем по названию, поэтому порядок можно менять."""
    wb = load_workbook(path, data_only=True)
    ws = wb["Вакансии"] if "Вакансии" in wb.sheetnames else wb.active
    header = [_norm(c.value) for c in ws[1]]

    def col(*names):
        for name in names:
            n = _norm(name)
            for i, h in enumerate(header):
                if h == n or (n and h.startswith(n)):
                    return i
        return None

    i_user = col(COL_USER_LETTER, "моё сопроводительное", "мое сопроводительное")
    i_link = col(COL_LINK)
    if i_user is None or i_link is None:
        raise ValueError("Не нашла колонки «Ссылка» и «Моё сопроводительное письмо». "
                         "Пришлите файл, который делал бот.")
    i_bot = col(COL_BOT_LETTER, "сопроводительное письмо")
    i_title, i_comp = col("Вакансия"), col("Компания")
    i_sum, i_why = col("Кратко о вакансии"), col("Чем интересна")

    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        def val(i):
            return str(row[i]).strip() if i is not None and i < len(row) and row[i] is not None else ""
        user_letter = val(i_user)
        link = val(i_link)
        if len(user_letter) < 20 or not link:
            continue
        out.append({
            "vacancy_url": link,
            "title": val(i_title),
            "company": val(i_comp),
            "bot_letter": val(i_bot),
            "user_letter": user_letter,
            "vacancy_text": "\n".join(x for x in [val(i_sum), val(i_why)] if x),
        })
    return out
