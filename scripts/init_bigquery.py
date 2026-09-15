#!/usr/bin/env python3
"""
init_bigquery.py — подготовить BigQuery для новой установки.

Вторая копия системы (например, margoads) работает на своём проекте Google, где
датасета и таблиц ещё нет. Схемы таблиц описаны не в коде, а живут в рабочем
проекте, поэтому скрипт их оттуда и копирует: создаёт датасет и пустые таблицы
с теми же полями. Данные не переносятся — новая установка наполняется своей
синхронизацией и загрузкой отчётов.

Запуск (из корня проекта):

    # что будет сделано, без изменений
    python3 scripts/init_bigquery.py --from amazon-ads-api-494412 --dry-run

    # создать датасет и таблицы в проекте из settings.py
    python3 scripts/init_bigquery.py --from amazon-ads-api-494412

    # перенести ещё и данные справочников (каталог, имена портфолио)
    python3 scripts/init_bigquery.py --from amazon-ads-api-494412 --copy catalog,portfolio_labels

Аккаунту, под которым запускаете, нужны права на чтение исходного проекта и на
запись в целевой.
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from google.cloud import bigquery                      # noqa: E402

from settings import PROJECT_ID, DATASET               # noqa: E402

# Таблицы, без которых интерфейс не работает. Остальные (если появятся в
# исходном датасете) тоже создаются — список нужен, чтобы проверить полноту.
REQUIRED = [
    "campaigns_merch", "campaigns_kdp",
    "asin_stats_merch", "asin_stats_kdp",
    "targets_stats_merch", "targets_stats_kdp",
    "search_terms_merch", "search_terms_kdp",
    "placement_stats_merch", "placement_stats_kdp",
    "pending_changes_merch", "pending_changes_kdp",
    "change_log_merch", "change_log_kdp",
    "catalog", "portfolio_labels",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='src', required=True,
                    help='проект-источник схем, например amazon-ads-api-494412')
    ap.add_argument('--src-dataset', default=DATASET, help='датасет в источнике')
    ap.add_argument('--location', default='US', help='регион датасета (по умолчанию US)')
    ap.add_argument('--copy', default='', help='таблицы, которые перенести с данными, через запятую')
    ap.add_argument('--dry-run', action='store_true', help='только показать план')
    args = ap.parse_args()

    if args.src == PROJECT_ID and args.src_dataset == DATASET:
        print("Источник и цель совпадают — нечего делать. "
              "Укажите в config/settings.json проект новой установки.")
        return 1

    client = bigquery.Client(project=PROJECT_ID)
    src_ds = bigquery.DatasetReference(args.src, args.src_dataset)

    print(f"Источник: {args.src}.{args.src_dataset}")
    print(f"Цель:     {PROJECT_ID}.{DATASET} ({args.location})")
    print()

    # 1. датасет
    ds_ref = bigquery.DatasetReference(PROJECT_ID, DATASET)
    try:
        client.get_dataset(ds_ref)
        print(f"Датасет {DATASET} уже есть")
    except Exception:
        if args.dry_run:
            print(f"[план] создать датасет {DATASET}")
        else:
            ds = bigquery.Dataset(ds_ref)
            ds.location = args.location
            client.create_dataset(ds)
            print(f"Создан датасет {DATASET}")

    # 2. таблицы по схемам источника
    tables = sorted(t.table_id for t in client.list_tables(src_ds))
    if not tables:
        print(f"В источнике нет таблиц — проверьте доступ к {args.src}")
        return 1

    existing = {t.table_id for t in client.list_tables(ds_ref)} if not args.dry_run else set()
    to_copy  = {t.strip() for t in args.copy.split(',') if t.strip()}

    created = skipped = copied = 0
    for name in tables:
        src_tbl = client.get_table(f"{args.src}.{args.src_dataset}.{name}")
        dst_id  = f"{PROJECT_ID}.{DATASET}.{name}"

        if name in existing:
            print(f"  = {name}: уже есть, пропуск")
            skipped += 1
        elif args.dry_run:
            print(f"  [план] {name}: {len(src_tbl.schema)} полей")
            created += 1
        else:
            dst = bigquery.Table(dst_id, schema=src_tbl.schema)
            if src_tbl.time_partitioning:
                dst.time_partitioning = src_tbl.time_partitioning
            if src_tbl.clustering_fields:
                dst.clustering_fields = src_tbl.clustering_fields
            client.create_table(dst)
            print(f"  + {name}: создана ({len(src_tbl.schema)} полей)")
            created += 1

        if name in to_copy and not args.dry_run:
            job = client.copy_table(f"{args.src}.{args.src_dataset}.{name}", dst_id,
                                    job_config=bigquery.CopyJobConfig(
                                        write_disposition="WRITE_TRUNCATE"))
            job.result()
            print(f"    данные перенесены: {client.get_table(dst_id).num_rows:,} строк"
                  .replace(',', ' '))
            copied += 1

    missing = [t for t in REQUIRED if t not in tables]
    print()
    print(f"Таблиц создано: {created}, пропущено: {skipped}, с данными: {copied}")
    if missing:
        print(f"ВНИМАНИЕ: в источнике не нашлось: {', '.join(missing)} — "
              f"часть страниц будет отдавать ошибку, пока таблицы не появятся")
    return 0


if __name__ == '__main__':
    sys.exit(main())
