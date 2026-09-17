#!/bin/bash
# Двойной клик по этому файлу — сайт открывается в браузере.
# Окно Терминала, которое при этом появится, закрывать нельзя:
# пока оно открыто — работает сайт. Закрыли окно — сайт остановился.

cd "$(dirname "$0")/site" || { echo "Не нашёл папку site рядом с этим файлом"; read -r; exit 1; }

# Ищем свободный порт, начиная с 8080: так браузер не покажет старую версию
PORT=8916
while lsof -i :$PORT >/dev/null 2>&1; do PORT=$((PORT + 1)); done

python3 -m http.server "$PORT" >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

sleep 1
open "http://localhost:$PORT"

echo ""
echo "  Сайт работает: http://localhost:$PORT"
echo ""
echo "  Чтобы остановить — закройте это окно."
echo ""
wait $SERVER
