#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автосбор рекламной статистики Amazon Ads.

Запускается ежедневной задачей (PythonAnywhere Scheduled Task):
    python3 /home/nikolaenkots/amazon-ads/auto_collect.py

Для всех профилей из config/amazon_secrets.json и всех типов отчётов
(spTargeting, spAdvertisedProduct, spSearchTerm, spCampaigns):
  1. создаёт отчёты за последние 14 дней (все сразу),
  2. ждёт готовности (общий поллинг),
  3. скачивает и загружает в BigQuery (DELETE за период + APPEND).

История пишется в auto_collect_log.json (последние записи сверху),
веб-страница /ads показывает последние 50 строк через /ads/auto_log.
"""

import gzip
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS",
                      os.path.join(BASE_DIR, "config", "bigquery_key.json"))

from ads_routes import REPORT_CONFIGS, _AMZ, _amz_headers, _amz_token, _get_table, _map_row
from bq_client import get_client

AUTO_LOG    = os.path.join(BASE_DIR, "auto_collect_log.json")
DAYS_BACK   = 14      # период отчёта: последние 14 дней (по вчера включительно)
POLL_EVERY  = 30      # секунд между проверками статусов
MAX_WAIT    = 120 * 60  # общий лимит ожидания готовности отчётов
BQ_CHUNK    = 50_000
LOAD_RETRIES = 3      # попыток скачать/загрузить готовый отчёт
LOG_KEEP    = 500     # сколько записей хранить в файле истории


# ── История ───────────────────────────────────────────────
def _read_log():
    try:
        with open(AUTO_LOG) as f:
            return json.load(f)
    except Exception:
        return []


def _write_log(entries):
    tmp = AUTO_LOG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries[:LOG_KEEP], f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, AUTO_LOG)


def log_add(entry):
    entries = _read_log()
    entries.insert(0, entry)
    _write_log(entries)


def log_update(entry_id, updates):
    entries = _read_log()
    for e in entries:
        if e.get("id") == entry_id:
            e.update(updates)
            break
    _write_log(entries)


def _now_iso():
    return datetime.now(tz=timezone.utc).isoformat()


# ── Amazon API ────────────────────────────────────────────
def create_report(token, profile, report_type, start_date, end_date):
    """Создать отчёт, с ретраями на 429/5xx. Возвращает report_id."""
    cfg      = REPORT_CONFIGS[report_type]
    endpoint = profile.get("api_endpoint", "https://advertising-api.amazon.com")
    headers  = {
        **_amz_headers(token, profile["id"]),
        "Content-Type": "application/vnd.createasyncreportrequest.v3+json",
    }
    body = {
        "name":      f"AUTO {report_type} {profile['type']} {profile['marketplace']} {start_date}→{end_date}",
        "startDate": start_date,
        "endDate":   end_date,
        "configuration": {
            "adProduct":    "SPONSORED_PRODUCTS",
            "reportTypeId": report_type,
            "groupBy":      cfg["groupBy"],
            "timeUnit":     "DAILY",
            "format":       "GZIP_JSON",
            "columns":      cfg["columns"],
        },
    }
    for attempt, pause in enumerate((0, 10, 30, 60)):
        if pause:
            time.sleep(pause)
        r = requests.post(f"{endpoint}/reporting/reports", headers=headers, json=body, timeout=60)
        if r.status_code == 425:  # duplicate request — Amazon вернёт существующий reportId
            try:
                dup = r.json().get("detail", "")
                # detail: "... duplicate of : <reportId>"
                rid = dup.rstrip(".").split(":")[-1].strip()
                if rid:
                    return rid
            except Exception:
                pass
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            continue
        r.raise_for_status()
        return r.json()["reportId"]
    raise Exception(f"create_report: превышены ретраи ({r.status_code})")


def check_report(token, profile, report_id):
    endpoint = profile.get("api_endpoint", "https://advertising-api.amazon.com")
    r = requests.get(f"{endpoint}/reporting/reports/{report_id}",
                     headers=_amz_headers(token, profile["id"]), timeout=60)
    r.raise_for_status()
    return r.json()


def download_rows(url):
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    return json.loads(gzip.decompress(r.content))


# ── BigQuery ──────────────────────────────────────────────
def load_to_bq(rows, profile, report_type, start_date, end_date):
    from google.cloud.bigquery import LoadJobConfig
    client     = get_client()
    table      = _get_table(profile["type"], report_type)
    profile_id = str(profile["id"])

    client.query(
        f"DELETE FROM `{table}` "
        f"WHERE date BETWEEN '{start_date}' AND '{end_date}' AND profile_id = '{profile_id}'"
    ).result()

    mapped   = [_map_row(r, profile_id, profile["marketplace"], report_type) for r in rows]
    inserted = 0
    for i in range(0, len(mapped), BQ_CHUNK):
        chunk = mapped[i:i + BQ_CHUNK]
        client.load_table_from_json(
            chunk, table,
            job_config=LoadJobConfig(write_disposition="WRITE_APPEND")
        ).result()
        inserted += len(chunk)
    return inserted


# ── Основной цикл ─────────────────────────────────────────
def main(days=DAYS_BACK, only_types=None, only_profile=None):
    run_id     = datetime.now().strftime("%Y%m%d%H%M%S")
    end_date   = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    profiles   = _AMZ.get("profiles", [])
    types      = [t for t in REPORT_CONFIGS if not only_types or t in only_types]
    if only_profile:  # ("MERCH", "US")
        acct, mkt = only_profile
        profiles = [p for p in profiles
                    if p["type"] == acct and (not mkt or p["marketplace"] == mkt)]
    if not profiles or not types:
        print("Нет профилей/типов под заданный фильтр")
        return

    print(f"=== Автосбор {start_date} → {end_date} | {len(profiles)} профилей × {len(types)} типов ===")
    token = _amz_token()

    # Фаза 1: создаём все отчёты
    tasks = []  # {entry_id, profile, report_type, report_id, status}
    for profile in profiles:
        for rt in types:
            entry_id = f"{run_id}_{profile['type']}_{profile['marketplace']}_{rt}"
            entry = {
                "id":           entry_id,
                "run_id":       run_id,
                "account_type": profile["type"],
                "marketplace":  profile["marketplace"],
                "profile_name": profile.get("name", f"{profile['type']} {profile['marketplace']}"),
                "report_type":  rt,
                "start_date":   start_date,
                "end_date":     end_date,
                "status":       "PENDING",
                "report_id":    None,
                "rows":         None,
                "inserted":     None,
                "error":        None,
                "created_at":   _now_iso(),
                "finished_at":  None,
                "duration_sec": None,
            }
            log_add(entry)
            try:
                report_id = create_report(token, profile, rt, start_date, end_date)
                log_update(entry_id, {"report_id": report_id})
                tasks.append({"entry_id": entry_id, "profile": profile, "report_type": rt,
                              "report_id": report_id, "t0": time.time()})
                print(f"  + {entry['profile_name']} {rt}: {report_id}")
            except Exception as e:
                log_update(entry_id, {"status": "FAILED", "error": f"create: {e}",
                                      "finished_at": _now_iso()})
                print(f"  ✗ {entry['profile_name']} {rt}: {e}")
            time.sleep(1)  # бережём rate limit

    # Фаза 2: поллинг + скачивание + загрузка
    waited = 0
    total_tasks = len(tasks)
    while tasks and waited < MAX_WAIT:
        time.sleep(POLL_EVERY)
        waited += POLL_EVERY
        print(f"  [{waited // 60}м {waited % 60:02d}с] ожидаем {len(tasks)}/{total_tasks} отчётов: "
              + ", ".join(f"{t['profile'].get('name')} {t['report_type']}" for t in tasks[:4])
              + ("..." if len(tasks) > 4 else ""), flush=True)
        if waited % 1800 == 0:
            token = _amz_token()  # токен живёт 60 мин — обновляем заранее
        for task in tasks[:]:
            try:
                d      = check_report(token, task["profile"], task["report_id"])
                status = d.get("status")
                if status == "COMPLETED":
                    name = f"{task['profile'].get('name')} {task['report_type']}"
                    print(f"  ↓ {name}: скачиваем...")
                    try:
                        rows     = download_rows(d["url"])
                        inserted = load_to_bq(rows, task["profile"], task["report_type"],
                                              start_date, end_date)
                    except Exception as e:
                        # скачивание/загрузка сорвались — оставляем задачу на повтор,
                        # после LOAD_RETRIES попыток закрываем её как ERROR
                        task["load_tries"] = task.get("load_tries", 0) + 1
                        if task["load_tries"] >= LOAD_RETRIES:
                            tasks.remove(task)
                            log_update(task["entry_id"], {
                                "status": "ERROR", "error": f"load: {e}",
                                "finished_at": _now_iso(),
                                "duration_sec": int(time.time() - task["t0"]),
                            })
                            print(f"  ✗ {name}: не удалось загрузить ({e})")
                        else:
                            log_update(task["entry_id"], {"error": f"load (попытка {task['load_tries']}): {e}"})
                            print(f"  ! {name}: {e} — повтор в следующем цикле")
                        continue
                    tasks.remove(task)
                    log_update(task["entry_id"], {
                        "status": "LOADED", "rows": len(rows), "inserted": inserted,
                        "error": None,
                        "finished_at": _now_iso(),
                        "duration_sec": int(time.time() - task["t0"]),
                    })
                    print(f"  ✓ {name}: {inserted} строк")
                elif status == "FAILED":
                    tasks.remove(task)
                    log_update(task["entry_id"], {
                        "status": "FAILED", "error": d.get("failureReason", "Unknown"),
                        "finished_at": _now_iso(),
                        "duration_sec": int(time.time() - task["t0"]),
                    })
                    print(f"  ✗ {task['profile'].get('name')} {task['report_type']}: FAILED")
            except Exception as e:
                # сетевые/временные ошибки — не снимаем задачу, попробуем в следующем цикле;
                # но фиксируем последнюю ошибку в логе
                log_update(task["entry_id"], {"error": str(e)})
                print(f"  ! {task['profile'].get('name')} {task['report_type']}: {e}")

    # Не дождались — помечаем таймаут
    for task in tasks:
        log_update(task["entry_id"], {
            "status": "TIMEOUT", "error": f"Отчёт не готов за {MAX_WAIT // 60} мин",
            "finished_at": _now_iso(),
            "duration_sec": int(time.time() - task["t0"]),
        })
        print(f"  ✗ {task['profile'].get('name')} {task['report_type']}: TIMEOUT")

    # Итог
    entries = [e for e in _read_log() if e.get("run_id") == run_id]
    ok      = sum(1 for e in entries if e["status"] == "LOADED")
    print(f"\n=== Итог: {ok}/{len(entries)} загружено ===")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Автосбор отчётов Amazon Ads")
    ap.add_argument("--test", action="store_true",
                    help="быстрый тест: 1 профиль (MERCH US) × spTargeting × 2 дня")
    ap.add_argument("--days", type=int, default=DAYS_BACK, help="дней назад (по умолчанию 14)")
    ap.add_argument("--type", dest="types", action="append",
                    choices=list(REPORT_CONFIGS.keys()), help="только этот тип (можно несколько раз)")
    ap.add_argument("--profile", nargs=2, metavar=("ACCT", "MKT"),
                    help="только этот профиль, напр.: --profile MERCH US")
    args = ap.parse_args()

    if args.test:
        main(days=2, only_types=["spTargeting"], only_profile=("MERCH", "US"))
    else:
        main(days=args.days, only_types=args.types,
             only_profile=tuple(args.profile) if args.profile else None)
