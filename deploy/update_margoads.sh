#!/usr/bin/env bash
# Обновление копии в /home/<user>/margoads (Google Cloud VM, systemd-сервис margoads).
#
# Заменяет прежний ~/update_margoads.sh с заменами через sed: датасет, логин и
# пароль больше не правятся в коде, они лежат в config/settings.json. Поэтому
# обновление сводится к «положить новые файлы, не тронув config/».
#
# Использование:
#   ./update_margoads.sh ~/code_update.tar.gz     # архив с кодом
#   ./update_margoads.sh ~/amazon-ads             # или распакованная папка
#
set -euo pipefail

SRC="${1:-}"
DEST="$HOME/margoads"
SERVICE="margoads"

if [ -z "$SRC" ]; then
  echo "Укажите архив или папку с новым кодом:"
  echo "  $0 ~/code_update.tar.gz"
  exit 1
fi
[ -d "$DEST" ] || { echo "Нет папки $DEST"; exit 1; }

# ── 1. Настройки этой копии должны существовать ДО обновления ──
# Новый код берёт датасет и доступ из config/settings.json. Без него установка
# работала бы с датасетом amazon_ads — то есть с базой основного аккаунта.
CFG="$DEST/config/settings.json"
if [ ! -f "$CFG" ]; then
  cat <<EOF
Нет $CFG.

Создайте его ДО обновления (датасет margoads, не amazon_ads):

cat > $CFG <<'JSON'
{
  "project_id": "amazon-ads-api-494412",
  "dataset":    "margoads",
  "site_name":  "Margo Ads",
  "auth": {"username": "Margo", "password": "<пароль>"}
}
JSON
EOF
  exit 1
fi
python3 -c "import json,sys; d=json.load(open('$CFG'));
assert d.get('dataset'), 'в settings.json не задан dataset';
print('  настройки: проект', d.get('project_id'), '· датасет', d['dataset'])" || exit 1

# ── 2. Резервная копия ключей и настроек ──────────────────
BACKUP="$HOME/margoads-config-$(date +%Y%m%d-%H%M%S).tar.gz"
tar czf "$BACKUP" -C "$DEST" config
echo "  копия config/: $BACKUP"

# ── 3. Распаковка источника ───────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -f "$SRC" ]; then
  tar xf "$SRC" -C "$TMP"
  # в архиве обычно одна папка верхнего уровня (amazon-ads/ или amazon-ads-<ветка>/)
  COUNT=$(find "$TMP" -maxdepth 1 -mindepth 1 | wc -l)
  if [ "$COUNT" = "1" ]; then NEW="$(find "$TMP" -maxdepth 1 -mindepth 1)"; else NEW="$TMP"; fi
else
  NEW="$SRC"
fi
[ -f "$NEW/app.py" ] || { echo "В $NEW нет app.py — это не код проекта"; exit 1; }

# ── 4. Перенос файлов: config, загрузки, логи и venv не трогаем ──
EXCL=(config uploads logs venv .git __pycache__)
if command -v rsync >/dev/null; then
  rsync -a --delete \
        --exclude 'config' --exclude 'uploads' --exclude 'logs' \
        --exclude 'venv' --exclude '.git' --exclude '__pycache__' \
        --exclude '*_log.json' \
        "$NEW/" "$DEST/"
else
  # без rsync: копируем поверх, но устаревшие файлы останутся — о них говорим вслух
  TAR_EXCL=()
  for e in "${EXCL[@]}"; do TAR_EXCL+=(--exclude="./$e"); done
  TAR_EXCL+=(--exclude='./*_log.json')
  tar -C "$NEW" -cf - "${TAR_EXCL[@]}" . | tar -C "$DEST" -xf -
  echo "  ВНИМАНИЕ: rsync не установлен — файлы скопированы поверх,"
  echo "  удалённые в новой версии файлы остались. Поставьте: sudo apt install -y rsync"
fi
echo "  код обновлён"

# ── 5. Зависимости ───────────────────────────────────────
if [ -x "$DEST/venv/bin/pip" ] && [ -f "$DEST/requirements.txt" ]; then
  "$DEST/venv/bin/pip" install -q -r "$DEST/requirements.txt"
  echo "  зависимости проверены"
fi

# ── 6. Проверка перед перезапуском ───────────────────────
PY="$DEST/venv/bin/python"; [ -x "$PY" ] || PY=python3
echo
cd "$DEST"
"$PY" scripts/check_install.py || {
  echo
  echo "Не перезапускаю: сначала исправьте настройки выше."
  echo "Старая версия продолжает работать. Ключи: $BACKUP"
  exit 1
}

# ── 7. Перезапуск ────────────────────────────────────────
sudo systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" \
  && echo "OK: обновлено и перезапущено" \
  || { echo "Сервис не поднялся: journalctl -u $SERVICE -n 50"; exit 1; }
