"""
settings.py — единственное место, где заданы проект BigQuery, датасет,
пути к ключам и доступ к веб-интерфейсу.

Раньше `PROJECT_ID = "amazon-ads-api-494412"` был продублирован почти в
тридцати файлах, поэтому вторую копию системы (другой аккаунт, другой проект
Google) нельзя было поднять без правки кода. Теперь значения читаются так,
в порядке убывания приоритета:

  1. переменные окружения  (AMZADS_PROJECT_ID, AMZADS_DATASET, ...)
  2. config/settings.json  (не в git — свой на каждом сервере)
  3. значения по умолчанию ниже — текущий рабочий проект

Пример config/settings.json для второй установки:

    {
      "project_id": "margoads-ads-api",
      "dataset": "amazon_ads",
      "auth": {"username": "Margo", "password": "..."},
      "site_name": "Margo Ads"
    }
"""

import json
import os

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
SETTINGS_FILE = os.path.join(CONFIG_DIR, 'settings.json')

_DEFAULTS = {
    "project_id": "amazon-ads-api-494412",
    "dataset":    "amazon_ads",
    "key_file":   os.path.join(CONFIG_DIR, "bigquery_key.json"),
    "secrets_file": os.path.join(CONFIG_DIR, "amazon_secrets.json"),
    "site_name":  "Amazon Ads Automation",
    "auth": {"username": "Artem", "password": "KjubcN*123"},
}


def _load_file():
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:                      # битый конфиг лучше заметить сразу
        raise RuntimeError(f"Не читается {SETTINGS_FILE}: {e}")


_file = _load_file()


def _get(name, env, default=None):
    val = os.environ.get(env)
    if val not in (None, ''):
        return val
    if name in _file and _file[name] not in (None, ''):
        return _file[name]
    return _DEFAULTS.get(name) if default is None else default


PROJECT_ID   = _get("project_id",   "AMZADS_PROJECT_ID")
DATASET      = _get("dataset",      "AMZADS_DATASET")
KEY_FILE     = _get("key_file",     "AMZADS_KEY_FILE")
SECRETS_FILE = _get("secrets_file", "AMZADS_SECRETS_FILE")
SITE_NAME    = _get("site_name",    "AMZADS_SITE_NAME")

_auth = dict(_DEFAULTS["auth"])
_auth.update(_file.get("auth") or {})
AUTH_USERNAME = os.environ.get("AMZADS_USER") or _auth["username"]
AUTH_PASSWORD = os.environ.get("AMZADS_PASSWORD") or _auth["password"]

# Ключ сервис-аккаунта: библиотеки Google читают его из переменной окружения.
# На Google Cloud VM ключа может не быть вовсе — там работает сервис-аккаунт
# самой машины, поэтому переменную ставим только если файл реально есть.
if os.path.exists(KEY_FILE):
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", KEY_FILE)


def table(name):
    """Полное имя таблицы: table('campaigns_merch')."""
    return f"{PROJECT_ID}.{DATASET}.{name}"
