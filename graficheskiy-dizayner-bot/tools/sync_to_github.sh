#!/usr/bin/env bash
# Синхронизирует проект в бэкап-репозиторий и пушит на GitHub, если что-то изменилось.
# Запускается Stop-хуком Claude Code (.claude/settings.local.json) или вручную:
#   bash tools/sync_to_github.sh
# Личные данные и секреты не копируются; перед коммитом копия проверяется на них.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${BACKUP_REPO:-/c/Users/user/Desktop/Cloudeu/ClaudeCode/_github-backup}"
SUB="graficheskiy-dizayner-bot"
DST="$REPO/$SUB"

msg() { printf '{"systemMessage": "%s"}\n' "$1"; }

[ -d "$REPO/.git" ] || { msg "GitHub-синхронизация: не найден репозиторий $REPO"; exit 0; }

# 1. Свежая копия без секретов (удалённые файлы тоже исчезнут из копии)
rm -rf "$DST"
mkdir -p "$DST"
( cd "$SRC" && tar \
    --exclude=./.venv --exclude=./data --exclude=./.env --exclude=./.claude \
    --exclude=./bot/candidate_private.py --exclude=./пример_выгрузки.xlsx \
    --exclude='__pycache__' --exclude='~$*' --exclude='*.pyc' \
    -cf - . ) | ( cd "$DST" && tar -xf - )

# 2. Проверка, что в копию не попали личные данные (значения берём из локального файла)
PY="$SRC/.venv/Scripts/python.exe"; [ -x "$PY" ] || PY="python"
LEAKS="$("$PY" -X utf8 - "$SRC" "$DST" <<'PYEOF'
import re, sys, pathlib
src, dst = map(pathlib.Path, sys.argv[1:3])
priv = src / "bot" / "candidate_private.py"
if not priv.exists():
    sys.exit(0)
ns = {}
exec(priv.read_text(encoding="utf-8"), ns)
text = " ".join(str(ns.get(k, "")) for k in ("CONTACTS", "PORTFOLIO", "PORTFOLIO_ALT"))
tokens = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+|@\w{4,}|https?://\S+", text))
tokens |= {re.sub(r"\D", "", p)[-7:] for p in re.findall(r"\+?\d[\d\s()-]{8,}\d", text)}
surname = str(ns.get("NAME", "")).split()[-1:]
tokens |= {s for s in surname if len(s) > 3}
found = []
for f in dst.rglob("*"):
    if f.is_file():
        data = f.read_bytes().decode("utf-8", "ignore")
        digits = re.sub(r"\D", "", data)
        for t in tokens:
            if t and (t in data or (t.isdigit() and t in digits)):
                found.append(f"{f.relative_to(dst)}")
print(", ".join(sorted(set(found))))
PYEOF
)"
if [ -n "$LEAKS" ]; then
    rm -rf "$DST"; git -C "$REPO" checkout -- "$SUB" 2>/dev/null || true
    msg "GitHub-синхронизация ОТМЕНЕНА: личные данные в файлах: $LEAKS"
    exit 0
fi

# 3. Коммит и пуш, только если есть изменения
cd "$REPO"
git add -A -- "$SUB"
if git diff --cached --quiet -- "$SUB"; then
    exit 0
fi
CHANGED="$(git diff --cached --name-only -- "$SUB" | sed "s#^$SUB/##" | head -8 | paste -sd, - | sed 's/,/, /g')"
git commit -q -m "$SUB: автосинхронизация $(date '+%Y-%m-%d %H:%M')" -m "Изменено: $CHANGED"
if git pull -q --rebase && git push -q 2>/dev/null; then
    msg "Запушено на GitHub ($(git log -1 --format=%h)): $CHANGED"
else
    msg "GitHub-синхронизация: коммит создан, но пуш не прошёл — проверьте сеть/доступ и выполните git push в $REPO"
fi
