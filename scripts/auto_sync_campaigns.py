#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автосинхронизация структуры кампаний из Amazon SP API.

Запускается ежедневной задачей (PythonAnywhere Scheduled Task):
    python3 /home/nikolaenkots/amazon-ads/scripts/auto_sync_campaigns.py

Для каждого профиля из config/amazon_secrets.json тянет кампании, группы,
таргеты, минус-слова, product ads и портфолио, затем перезаписывает свой
маркетплейс в campaigns_merch / campaigns_kdp.

Профили обрабатываются последовательно: структура крупного аккаунта занимает
гигабайты, параллельный обход упёрся бы в лимит памяти PythonAnywhere.

История пишется в campaigns_sync_log.json (source: "auto") — тот же файл,
что и у ручных синхронизаций со страницы /campaigns.
"""

import os
import sys
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS",
                      os.path.join(BASE_DIR, "config", "bigquery_key.json"))

from data_import.campaigns_routes import _AMZ, _read_sync_log, _run_campaigns_sync


def main(only_profile=None):
    profiles = _AMZ.get("profiles", [])
    if only_profile:  # ("MERCH", "US")
        acct, mkt = only_profile
        profiles = [p for p in profiles
                    if p["type"] == acct and (not mkt or p["marketplace"] == mkt)]
    if not profiles:
        print("Нет профилей под заданный фильтр")
        return

    started = datetime.now(tz=timezone.utc).isoformat()
    print(f"=== Синхронизация кампаний: {len(profiles)} профилей ===", flush=True)

    results = []
    for p in profiles:
        name = p.get("name") or f"{p['type']} {p['marketplace']}"
        print(f"\n→ {name}", flush=True)
        t0 = time.time()
        # job_id=None — прогресс печатается в консоль, а не в progress_store
        entry = _run_campaigns_sync(p["type"], p["marketplace"], None, source="auto") or {}
        status = entry.get("status", "ERROR")
        if status == "OK":
            c = entry.get("counts") or {}
            print(f"  ✓ {name}: {entry.get('total')} строк "
                  f"({c.get('campaign', 0)} кампаний, {c.get('ad_group', 0)} групп, "
                  f"{c.get('keyword', 0)} kw) за {int(time.time() - t0)}с", flush=True)
        elif status == "EMPTY":
            print(f"  ○ {name}: {entry.get('note')}", flush=True)
        else:
            print(f"  ✗ {name}: {entry.get('error')}", flush=True)
        results.append((name, status, entry))

    ok    = sum(1 for _, s, _ in results if s == "OK")
    empty = sum(1 for _, s, _ in results if s == "EMPTY")
    bad   = [(n, e) for n, s, e in results if s not in ("OK", "EMPTY")]
    print(f"\n=== Итог: {ok} синхронизировано, {empty} пустых, "
          f"{len(bad)} с ошибкой (всего {len(results)}) ===", flush=True)
    for n, e in bad:
        print(f"  ✗ {n}: {e.get('error')}", flush=True)
    return started


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Автосинхронизация кампаний Amazon Ads")
    ap.add_argument("--test", action="store_true", help="только MERCH US")
    ap.add_argument("--profile", nargs=2, metavar=("ACCT", "MKT"),
                    help="только этот профиль, напр.: --profile KDP UK")
    args = ap.parse_args()

    if args.test:
        main(only_profile=("MERCH", "US"))
    else:
        main(only_profile=tuple(args.profile) if args.profile else None)
