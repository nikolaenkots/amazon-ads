"""
collect_placements.py — сбор статистики по плейсментам (spCampaigns / campaignPlacement).

Пишет в placement_stats_{merch,kdp}. Используется страницей /automation/placements.

Запуск:
    python3 collect_placements.py [days] [ACCOUNT]
      days     — сколько последних дней собрать (по умолчанию 14, максимум 31 — лимит Amazon)
      ACCOUNT  — MERCH | KDP (по умолчанию все профили из конфига)

Пример:
    python3 collect_placements.py 14 MERCH
    python3 collect_placements.py 14            # все профили
"""
import json, gzip, time, os, sys, requests
from datetime import date, timedelta, datetime, timezone
from google.cloud import bigquery

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

with open(f"{BASE_DIR}/config/amazon_secrets.json") as f:
    AMZ = json.load(f)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f"{BASE_DIR}/config/bigquery_key.json"


def token():
    r = requests.post("https://api.amazon.com/auth/o2/token", data={
        "grant_type":    "refresh_token",
        "refresh_token": AMZ["refresh_token"],
        "client_id":     AMZ["client_id"],
        "client_secret": AMZ["client_secret"],
    }, timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


def tbl_for(account_type):
    suffix = "kdp" if account_type == "KDP" else "merch"
    return f"{PROJECT_ID}.{DATASET}.placement_stats_{suffix}"


def create_report(tok, prof, start, end):
    ep = prof.get("api_endpoint", "https://advertising-api.amazon.com")
    headers = {
        "Authorization":                    f"Bearer {tok}",
        "Amazon-Advertising-API-ClientId":  AMZ["client_id"],
        "Amazon-Advertising-API-Scope":     str(prof["id"]),
        "Content-Type":                     "application/vnd.createasyncreportrequest.v3+json",
    }
    body = {
        "name":      f"placement {start}→{end} {prof['marketplace']}",
        "startDate": start, "endDate": end,
        "configuration": {
            "adProduct":    "SPONSORED_PRODUCTS",
            "reportTypeId": "spCampaigns",
            "groupBy":      ["campaignPlacement"],
            "timeUnit":     "DAILY",
            "format":       "GZIP_JSON",
            "columns": ["date", "campaignId", "campaignName", "placementClassification",
                        "impressions", "clicks", "cost", "purchases7d", "sales7d"],
        },
    }
    for attempt in range(6):
        r = requests.post(f"{ep}/reporting/reports", headers=headers, json=body, timeout=60)
        if r.status_code == 425:      # дубликат — отчёт уже запрошен, ждём и повторяем
            time.sleep(10)
            continue
        r.raise_for_status()
        return r.json()["reportId"]
    raise RuntimeError("Не удалось создать отчёт (425 после повторов)")


def wait_for(tok, prof, report_id, max_wait=1800):
    ep = prof.get("api_endpoint", "https://advertising-api.amazon.com")
    headers = {
        "Authorization":                   f"Bearer {tok}",
        "Amazon-Advertising-API-ClientId": AMZ["client_id"],
        "Amazon-Advertising-API-Scope":    str(prof["id"]),
    }
    waited = 0
    while waited < max_wait:
        d = requests.get(f"{ep}/reporting/reports/{report_id}", headers=headers, timeout=60).json()
        status = d.get("status")
        if status == "COMPLETED":
            return d["url"]
        if status == "FAILED":
            raise Exception(f"Report failed: {d.get('failureReason')}")
        time.sleep(30)
        waited += 30
    raise Exception("Report timeout")


def load(rows, prof, start, end):
    client = bigquery.Client(project=PROJECT_ID)
    tbl    = tbl_for(prof["type"])
    pid    = str(prof["id"])
    mkt    = prof["marketplace"]
    # удаляем прежние данные за период и профиль (идемпотентность)
    client.query(
        f"DELETE FROM `{tbl}` WHERE date BETWEEN '{start}' AND '{end}' AND profile_id='{pid}'"
    ).result()
    now = datetime.now(tz=timezone.utc).isoformat()
    mapped = [{
        "date":         r.get("date"),
        "profile_id":   pid,
        "marketplace":  mkt,
        "campaign_id":  str(r.get("campaignId", "")),
        "campaign_name": r.get("campaignName"),
        "placement":    r.get("placementClassification"),
        "impressions":  r.get("impressions"),
        "clicks":       r.get("clicks"),
        "cost":         float(r["cost"])   if r.get("cost")   is not None else None,
        "purchases_7d": r.get("purchases7d"),
        "sales_7d":     float(r["sales7d"]) if r.get("sales7d") is not None else None,
        "loaded_at":    now,
    } for r in rows]
    for i in range(0, len(mapped), 5000):
        client.load_table_from_json(
            mapped[i:i+5000], tbl,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"),
        ).result()
    return len(mapped)


def collect_one(prof, start, end):
    print(f"\n=== {prof['name']} | {start} → {end} ===", flush=True)
    tok = token()
    rid = create_report(tok, prof, start, end)
    print(f"  report: {rid}", flush=True)
    url = wait_for(tok, prof, rid)
    rows = json.loads(gzip.decompress(requests.get(url).content))
    print(f"  строк из отчёта: {len(rows)}", flush=True)
    n = load(rows, prof, start, end)
    print(f"  ✓ загружено {n}", flush=True)
    return n


if __name__ == "__main__":
    days    = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    account = sys.argv[2].upper() if len(sys.argv) > 2 else None
    days    = min(days, 31)   # лимит Amazon на диапазон отчёта
    end     = date.today() - timedelta(days=1)
    start   = end - timedelta(days=days - 1)
    s, e    = start.isoformat(), end.isoformat()
    profiles = [p for p in AMZ["profiles"] if (account is None or p["type"] == account)]
    ok = fail = 0
    for p in profiles:
        try:
            collect_one(p, s, e); ok += 1
        except Exception as ex:
            fail += 1
            print(f"  ✗ {p.get('name')}: {ex}", flush=True)
    print(f"\n=== Готово: успешно {ok}, ошибок {fail} ===", flush=True)
