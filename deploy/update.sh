#!/usr/bin/env bash
# Обновление установки новой версией кода.
#
# Данные в BigQuery и папка config/ (ключи Amazon, settings.json) не трогаются:
# код обновляется из git, config/ в репозитории нет вовсе. Перед обновлением
# делается резервная копия config/, а после — проверка, что установка по-прежнему
# смотрит в свой проект.
#
#   cd /opt/amazon-ads && ./deploy/update.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "Проект: $ROOT"

# ── 1. Резервная копия настроек ──────────────────────────
BACKUP="$ROOT/../amazon-ads-config-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
if [ -d config ]; then
  tar czf "$BACKUP" config
  echo "Копия настроек: $BACKUP"
else
  echo "ВНИМАНИЕ: папки config/ нет — проверьте, где лежат ключи"
fi

# ── 2. Код ───────────────────────────────────────────────
if [ -d .git ]; then
  # Локальные правки (например, старый способ — вписанный в код id проекта)
  # мешают обновлению: откладываем их, чтобы ничего не потерялось.
  if ! git diff --quiet || ! git diff --cached --quiet; then
    STASH="update-$(date +%Y%m%d-%H%M%S)"
    git stash push -u -m "$STASH" -- ':!config' >/dev/null
    echo "Локальные правки отложены в git stash ($STASH), вернуть: git stash list"
  fi
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  echo "Ветка: $BRANCH"
  git pull --ff-only origin "$BRANCH"
else
  echo "Это не git-клон. Обновите файлы вручную, сохранив config/, logs/, uploads/:"
  echo "  rsync -a --delete --exclude config --exclude uploads --exclude logs \\"
  echo "        --exclude '*_log.json' ИСТОЧНИК/ $ROOT/"
  exit 1
fi

# ── 3. Зависимости ───────────────────────────────────────
if [ -x venv/bin/pip ] && [ -f requirements.txt ]; then
  venv/bin/pip install -q -r requirements.txt
  echo "Зависимости обновлены"
fi

# ── 4. Проверка: свой проект, свои ключи, таблицы на месте ─
PY="venv/bin/python"; [ -x "$PY" ] || PY="python3"
echo
"$PY" scripts/check_install.py || {
  echo
  echo "Обновление остановлено: сначала исправьте настройки выше."
  echo "Сервис не перезапускался, старая версия продолжает работать."
  exit 1
}

# ── 5. Перезапуск ────────────────────────────────────────
if systemctl list-units --type=service --all 2>/dev/null | grep -q amazon-ads.service; then
  sudo systemctl restart amazon-ads
  sleep 2
  systemctl is-active --quiet amazon-ads && echo "Сервис перезапущен" \
    || { echo "Сервис не поднялся, смотрите: journalctl -u amazon-ads -n 50"; exit 1; }
else
  echo "systemd-сервиса нет — перезапустите приложение так, как оно запущено у вас"
fi

echo "Готово."
