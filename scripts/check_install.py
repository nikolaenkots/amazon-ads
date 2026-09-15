#!/usr/bin/env python3
"""
check_install.py — куда именно смотрит эта установка.

Первое, что нужно проверить после переноса кода на другой сервер: приложение
работает со своим проектом BigQuery, а не с чужим. Раньше id проекта был вписан
в сам код, теперь он берётся из settings.py — если на сервере забыть
config/settings.json, установка молча начнёт писать в проект по умолчанию.

Ничего не меняет, только читает.

    python3 scripts/check_install.py
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import settings                                        # noqa: E402

DEFAULT_PROJECT = "amazon-ads-api-494412"

CORE_TABLES = ["campaigns_merch", "asin_stats_merch", "targets_stats_merch",
               "pending_changes_merch", "catalog"]


def main():
    cfg_exists = os.path.exists(settings.SETTINGS_FILE)
    env_project = os.environ.get("AMZADS_PROJECT_ID")

    print("Установка")
    print(f"  папка проекта : {BASE_DIR}")
    print(f"  название      : {settings.SITE_NAME}")
    print(f"  логин         : {settings.AUTH_USERNAME}")
    print()
    print("BigQuery")
    print(f"  проект        : {settings.PROJECT_ID}")
    print(f"  датасет       : {settings.DATASET}")
    src = ("переменная окружения" if env_project
           else "config/settings.json" if cfg_exists
           else "значение по умолчанию в settings.py")
    print(f"  откуда взято  : {src}")
    print()
    print("Файлы конфигурации")
    print(f"  settings.json : {'есть' if cfg_exists else 'НЕТ'}  ({settings.SETTINGS_FILE})")
    print(f"  ключи Amazon  : {'есть' if os.path.exists(settings.SECRETS_FILE) else 'НЕТ'}"
          f"  ({settings.SECRETS_FILE})")
    key = settings.KEY_FILE
    print(f"  ключ BigQuery : {'есть' if os.path.exists(key) else 'нет (на Google Cloud VM это нормально)'}")

    problems = []
    if not cfg_exists and not env_project and settings.PROJECT_ID == DEFAULT_PROJECT:
        problems.append(
            "Нет config/settings.json и нет AMZADS_PROJECT_ID — установка работает с проектом\n"
            f"    {DEFAULT_PROJECT}. Если это НЕ основной сервер, создайте config/settings.json\n"
            "    со своим project_id ДО запуска синхронизации, иначе данные уйдут в чужую базу.")

    # профили Amazon
    try:
        with open(settings.SECRETS_FILE, encoding='utf-8') as f:
            amz = json.load(f)
        profiles = amz.get('profiles', [])
        print(f"  профилей Amazon: {len(profiles)}"
              + (f" ({', '.join(sorted({p.get('type','?')+' '+p.get('marketplace','?') for p in profiles}))})"
                 if profiles else ""))
        if not profiles:
            problems.append("В amazon_secrets.json нет профилей — синхронизация ничего не соберёт.")
    except FileNotFoundError:
        problems.append(f"Не найден {settings.SECRETS_FILE} — без ключей Amazon ничего не синхронизируется.")
    except Exception as e:
        problems.append(f"amazon_secrets.json не читается: {e}")

    # доступность таблиц
    print()
    print("Таблицы")
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=settings.PROJECT_ID)
        have = {t.table_id for t in client.list_tables(
            bigquery.DatasetReference(settings.PROJECT_ID, settings.DATASET))}
        missing = [t for t in CORE_TABLES if t not in have]
        print(f"  всего в датасете: {len(have)}")
        if missing:
            problems.append("Не хватает таблиц: " + ", ".join(missing)
                            + "\n    Создать: python3 scripts/init_bigquery.py --from <проект-источник>")
        else:
            print("  ключевые таблицы на месте")
    except Exception as e:
        problems.append(f"BigQuery недоступна: {e}")

    print()
    if problems:
        print("ЧТО ИСПРАВИТЬ:")
        for p in problems:
            print(f"  • {p}")
        return 1
    print("Всё на месте: установка настроена на свой проект, ключи и таблицы доступны.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
