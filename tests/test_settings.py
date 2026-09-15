# -*- coding: utf-8 -*-
"""Настройки установки: одно место вместо хардкода в тридцати файлах.

Проверяет то, ради чего это делалось: вторую копию системы (свой проект Google,
свой аккаунт) можно поднять, не трогая код — только config/settings.json или
переменные окружения. И что без конфига ничего не меняется для текущего сервера.
"""
import importlib
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

CFG = os.path.join(BASE, 'config', 'settings.json')
saved = open(CFG).read() if os.path.exists(CFG) else None

try:
    # ── 1. Значения из config/settings.json ───────────────
    with open(CFG, 'w', encoding='utf-8') as f:
        json.dump({"project_id": "margoads-ads", "dataset": "ads2",
                   "site_name": "Margo Ads",
                   "auth": {"username": "Margo", "password": "pw"}}, f)
    import settings
    importlib.reload(settings)
    assert settings.PROJECT_ID == 'margoads-ads' and settings.DATASET == 'ads2'
    assert settings.AUTH_USERNAME == 'Margo' and settings.AUTH_PASSWORD == 'pw'
    assert settings.table('campaigns_merch') == 'margoads-ads.ads2.campaigns_merch'
    print("  ✓ вторая установка настраивается одним файлом: проект, датасет, доступ, название")

    # ── 2. Переменные окружения важнее файла ──────────────
    os.environ['AMZADS_PROJECT_ID'] = 'from-env'
    os.environ['AMZADS_PASSWORD']   = 'env-pw'
    importlib.reload(settings)
    assert settings.PROJECT_ID == 'from-env' and settings.AUTH_PASSWORD == 'env-pw'
    del os.environ['AMZADS_PROJECT_ID'], os.environ['AMZADS_PASSWORD']
    print("  ✓ переменные окружения перекрывают файл (удобно для systemd)")

    # ── 3. Без конфига — прежний рабочий проект ───────────
    os.remove(CFG)
    importlib.reload(settings)
    assert settings.PROJECT_ID == 'amazon-ads-api-494412'
    assert settings.DATASET == 'amazon_ads' and settings.AUTH_USERNAME == 'Artem'
    print("  ✓ без конфига поведение прежнее — текущий сервер не сломается")

finally:
    if saved is not None:
        open(CFG, 'w', encoding='utf-8').write(saved)
    elif os.path.exists(CFG):
        os.remove(CFG)


# ── 4. Хардкода проекта в коде больше нет ─────────────────
out = subprocess.run(['grep', '-rl', 'amazon-ads-api-494412', '--include=*.py', '.'],
                     capture_output=True, text=True).stdout.split()
# settings.py — единственное место со значением по умолчанию;
# init_bigquery.py упоминает старый проект только как пример в справке
left = [f for f in out if not f.startswith('./tests/')
        and f not in ('./settings.py', './scripts/init_bigquery.py')]
assert not left, f"проект всё ещё зашит в: {left}"
print(f"  ✓ id проекта остался только в settings.py — в коде страниц и скриптов его нет")


# ── 5. Приложение поднимается и отдаёт страницы ───────────
import bq_client


class J:
    errors = None
    def result(self): return []


bq_client._client = type('F', (), {'query': lambda s, q: J()})()
import base64
import app as A

c = A.app.test_client()
tok = base64.b64encode(f"{A.AUTH_USERNAME}:{A.AUTH_PASSWORD}".encode()).decode()
r = c.get('/', headers={'Authorization': f'Basic {tok}'})
assert r.status_code == 200 and 'Сводка по портфолио' in r.get_data(as_text=True)
print("  ✓ приложение стартует с настройками из settings.py")

print("\n=== ВСЕ ПРОВЕРКИ ПРОШЛИ ===")
