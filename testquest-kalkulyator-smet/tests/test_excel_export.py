# -*- coding: utf-8 -*-
"""
TC-11  Выгрузка сметы в Excel — кнопка, шаблон КП, формат OOXML, покраска значений
"""
import base64
import re
import struct
import zipfile
import io

import tq
from harness import Checks

BLOCK = "TC-11 · Выгрузка сметы в Excel"


def run():
    c = Checks()
    page = tq.html()
    app = tq.js("app")
    exp = tq.js("exportEstimate")

    c.contains("Кнопка «Выгрузить смету в Excel» (#export-btn)", page, 'id="export-btn"')
    c.contains("Клик по кнопке вызывает onExportExcel", app, "getElementById('export-btn').addEventListener('click', onExportExcel)")
    c.contains("Экспорт формирует .xlsx (MIME spreadsheetml.sheet)", exp, "spreadsheetml.sheet")
    c.contains("Файл скачивается через <a download>", exp, "link.download = filename")

    # библиотеки экспорта подключены на странице
    c.ok("Подключён ExcelJS (CDN)", "exceljs" in page.lower())
    c.ok("Подключён JSZip (CDN)", "jszip" in page.lower())

    # шаблон КП зашит в страницу base64 и является валидным OOXML/ZIP
    tpl_js = tq.js("kp-template-base64")
    m = re.search(r"KP_TEMPLATE_BASE64\s*=\s*['\"]([A-Za-z0-9+/=]+)['\"]", tpl_js)
    c.ok("В kp-template-base64.js есть строка KP_TEMPLATE_BASE64", bool(m))
    if m:
        raw = base64.b64decode(m.group(1))
        c.ok("Шаблон декодируется и начинается с сигнатуры ZIP (PK\\x03\\x04)",
             raw[:4] == b"PK\x03\x04", "первые байты %r" % raw[:4])
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
            names = zf.namelist()
            c.ok("Внутри шаблона есть [Content_Types].xml", "[Content_Types].xml" in names)
            c.ok("Внутри шаблона есть xl/workbook.xml", "xl/workbook.xml" in names)
            c.ok("Внутри шаблона есть хотя бы один лист xl/worksheets/sheet*.xml",
                 any(n.startswith("xl/worksheets/sheet") for n in names))
            c.ok("Шаблон содержит логотип/печать (xl/media/*)",
                 any(n.startswith("xl/media/") for n in names))
        except zipfile.BadZipFile:
            c.ok("Шаблон КП — корректный ZIP-контейнер", False, "BadZipFile")

    # покраска значений в выгрузке
    c.contains("Подставленные значения красятся зелёным (ARGB FF00B050)", exp, "FF00B050")
    c.contains("Легенда цветов на странице: «Зелёным … подставленные из сметы»", page, "подставленные из сметы")
    c.contains("Легенда: «Красным … необходимо подставить / провалидировать»", page, "провалидировать")

    # экспорт без выбранного тарифа не имеет смысла -> явная ошибка
    c.contains("Если не выбран ни один тариф — ошибка «Выберите тариф для выгрузки сметы»",
               exp, "Выберите тариф для выгрузки сметы")
    return c.items
