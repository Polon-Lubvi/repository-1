#!/bin/bash
# Двойной клик — на Рабочем столе появится архив со всем шаблоном.
# Его можно кинуть на флешку, в облако или отправить себе на другой компьютер.

HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="Shablon_Day_Gazu_$(date +%Y-%m-%d)"
OUT="$HOME/Desktop/$NAME.zip"

cd "$(dirname "$HERE")" || exit 1
rm -f "$OUT"
zip -r -q -X "$OUT" "$(basename "$HERE")" -x "*.DS_Store"

echo ""
echo "  Готово: $OUT"
echo ""
echo "  На новом компьютере распакуйте архив куда угодно"
echo "  и запустите «Запустить сайт.command» внутри папки."
echo ""
read -r -p "  Нажмите Enter, чтобы закрыть..."
