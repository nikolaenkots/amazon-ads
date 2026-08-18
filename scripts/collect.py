import json
import gzip
import time
import requests
import os
from datetime import datetime, timezone
from google.cloud import bigquery

# ── Конфиги ──────────────────────────────────────────────
BASE_DIR = "/home/nikolaenkots/amazon-ads"

with open(f"{BASE_DIR}/config/amazon_secrets.json") as f:
    AMZ = json.load(f)

PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"
CHUNK_SIZE = 1000

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f"{BASE_DIR}/config/bigquery_key.json"

# ── Получить профиль ──────────────────────────────────────
def get_profile(account_type="MERCH", marketplace="US"):
    for p in AMZ.get("profiles", []):
        if p["type"] == account_type and p["marketplace"] == marketplace:
            return p
    raise Exception(f"Профиль не найден: {account_type} / {marketplace}")

def get_table(account_type):
    if account_type == "KDP":
        return f"{PROJECT_ID}.{DATASET}.targets_stats_kdp"
    return f"{PROJECT_ID}.{DATASET}.targets_stats_merch"

# ── Amazon Auth ───────────────────────────────────────────
def get_access_token():
    resp = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": AMZ["refresh_token"],
            "client_id":     AMZ["client_id"],
            "client_secret": AMZ["client_secret"],
        }
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

# ── Создать отчёт ─────────────────────────────────────────
def create_report(token, profile, start_date, end_date):
    endpoint = profile.get("api_endpoint", "https://advertising-api.amazon.com")
    headers = {
        "Authorization":                   f"Bearer {token}",
        "Amazon-Advertising-API-ClientId":  AMZ["client_id"],
        "Amazon-Advertising-API-Scope":     str(profile["id"]),
        "Content-Type":                     "application/vnd.createasyncreportrequest.v3+json"
    }
    body = {
        "name":      f"SP targeting {start_date} {profile['type']} {profile['marketplace']}",
        "startDate": start_date,
        "endDate":   end_date,
        "configuration": {
            "adProduct":    "SPONSORED_PRODUCTS",
            "reportTypeId": "spTargeting",
            "groupBy":      ["targeting"],
            "timeUnit":     "DAILY",
            "format":       "GZIP_JSON",
            "columns": [
                "date",
                "campaignId", "adGroupId",
                "keywordId", "keyword", "keywordType", "targeting",
                "adKeywordStatus",
                "impressions", "clicks", "cost",
                "topOfSearchImpressionShare",
                "purchases1d", "purchases7d", "purchases14d",
                "sales1d",     "sales7d",     "sales14d",
                "unitsSoldClicks1d", "unitsSoldClicks7d", "unitsSoldClicks14d"
            ]
        }
    }
    resp = requests.post(
        f"{endpoint}/reporting/reports",
        headers=headers,
        json=body
    )
    resp.raise_for_status()
    return resp.json()["reportId"]

# ── Polling ───────────────────────────────────────────────
def wait_for_report(token, profile, report_id, max_wait=1800):
    endpoint = profile.get("api_endpoint", "https://advertising-api.amazon.com")
    headers = {
        "Authorization":                   f"Bearer {token}",
        "Amazon-Advertising-API-ClientId":  AMZ["client_id"],
        "Amazon-Advertising-API-Scope":     str(profile["id"]),
    }
    waited = 0
    while waited < max_wait:
        resp = requests.get(
            f"{endpoint}/reporting/reports/{report_id}",
            headers=headers
        )
        data   = resp.json()
        status = data.get("status")
        print(f"  [{waited}s] Status: {status}")

        if status == "COMPLETED":
            return data["url"]
        elif status == "FAILED":
            raise Exception(f"Report failed: {data.get('failureReason')}")

        time.sleep(30)
        waited += 30

    raise Exception("Report timeout")

# ── Скачать ───────────────────────────────────────────────
def download_report(url):
    resp = requests.get(url)
    return json.loads(gzip.decompress(resp.content))

# ── Маппинг ───────────────────────────────────────────────
def map_row(r, profile_id, marketplace):
    keyword_type = r.get("keywordType", "")
    is_keyword   = keyword_type in ("BROAD", "PHRASE", "EXACT")
    is_auto      = keyword_type in ("TARGETING_EXPRESSION_PREDEFINED", "TARGETING_EXPRESSION")

    return {
        "date":                           r.get("date"),
        "profile_id":                     str(profile_id),
        "marketplace":                    marketplace,
        "campaign_id":                    str(r.get("campaignId", "")),
        "ad_group_id":                    str(r.get("adGroupId", "")),
        "keyword_id":                     str(r["keywordId"]) if r.get("keywordId") else None,
        "keyword":                        r.get("keyword")   if is_keyword else None,
        "keyword_type":                   keyword_type       or None,
        "targeting":                      r.get("targeting") if is_auto    else None,
        "ad_keyword_status":              r.get("adKeywordStatus"),
        "impressions":                    r.get("impressions"),
        "clicks":                         r.get("clicks"),
        "cost":                           float(r["cost"])     if r.get("cost")     is not None else None,
        "top_of_search_impression_share": float(r["topOfSearchImpressionShare"]) if r.get("topOfSearchImpressionShare") is not None else None,
        "purchases_1d":                   r.get("purchases1d"),
        "purchases_7d":                   r.get("purchases7d"),
        "purchases_14d":                  r.get("purchases14d"),
        "sales_1d":                       float(r["sales1d"])  if r.get("sales1d")  is not None else None,
        "sales_7d":                       float(r["sales7d"])  if r.get("sales7d")  is not None else None,
        "sales_14d":                      float(r["sales14d"]) if r.get("sales14d") is not None else None,
        "units_1d":                       r.get("unitsSoldClicks1d"),
        "units_7d":                       r.get("unitsSoldClicks7d"),
        "units_14d":                      r.get("unitsSoldClicks14d"),
        "loaded_at":                      datetime.now(tz=timezone.utc).isoformat(),
    }

# ── Загрузка в BigQuery ───────────────────────────────────
def load_to_bigquery(rows, profile, start_date, end_date):
    client    = bigquery.Client(project=PROJECT_ID)
    table_ref = get_table(profile["type"])
    profile_id = str(profile["id"])
    marketplace = profile["marketplace"]

    # Удаляем старые данные за период и профиль
    client.query(
        f"DELETE FROM `{table_ref}` "
        f"WHERE date BETWEEN '{start_date}' AND '{end_date}' "
        f"AND profile_id = '{profile_id}'"
    ).result()
    print(f"  Удалены старые данные за {start_date}→{end_date} [{profile['name']}]")

    # Загружаем новые
    mapped   = [map_row(r, profile_id, marketplace) for r in rows]
    inserted = 0
    for i in range(0, len(mapped), CHUNK_SIZE):
        chunk = mapped[i:i+CHUNK_SIZE]
        job   = client.load_table_from_json(
            chunk, table_ref,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        )
        job.result()
        inserted += len(chunk)
        print(f"  Загружено: {inserted}/{len(mapped)}")

    return inserted

# ── Сбор одного профиля ───────────────────────────────────
def collect(start_date, end_date=None, account_type="MERCH", marketplace="US"):
    if end_date is None:
        end_date = start_date

    profile = get_profile(account_type, marketplace)
    print(f"\n=== {profile['name']} | {start_date} → {end_date} ===")

    print("1. Получаем токен...")
    token = get_access_token()

    print("2. Создаём отчёт...")
    report_id = create_report(token, profile, start_date, end_date)
    print(f"   Report ID: {report_id}")

    print("3. Ждём готовности...")
    url = wait_for_report(token, profile, report_id)

    print("4. Скачиваем...")
    rows = download_report(url)
    print(f"   Получено строк: {len(rows)}")

    print("5. Загружаем в BigQuery...")
    inserted = load_to_bigquery(rows, profile, start_date, end_date)

    print(f"\n✓ Готово. Загружено {inserted} строк [{profile['name']}]")
    return inserted

# ── Сбор всех профилей сразу ─────────────────────────────
def collect_all(start_date, end_date=None):
    """Запустить сбор для всех активных профилей."""
    if end_date is None:
        end_date = start_date

    results = []
    for profile in AMZ.get("profiles", []):
        try:
            inserted = collect(
                start_date, end_date,
                account_type=profile["type"],
                marketplace=profile["marketplace"]
            )
            results.append({"profile": profile["name"], "inserted": inserted, "status": "ok"})
        except Exception as e:
            print(f"  ✗ Ошибка [{profile['name']}]: {e}")
            results.append({"profile": profile["name"], "error": str(e), "status": "error"})

    print("\n=== ИТОГ ===")
    for r in results:
        status = "✓" if r["status"] == "ok" else "✗"
        detail = f"{r.get('inserted', 0)} строк" if r["status"] == "ok" else r.get("error", "")
        print(f"  {status} {r['profile']}: {detail}")

    return results

# ── Запуск ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # Использование:
    # python3 collect.py 2026-04-20                        → Merch US за день
    # python3 collect.py 2026-04-20 2026-04-27             → Merch US за период
    # python3 collect.py 2026-04-20 2026-04-27 MERCH US    → явно указать профиль
    # python3 collect.py 2026-04-20 2026-04-27 KDP UK      → KDP UK
    # python3 collect.py 2026-04-20 all                    → все профили

    if len(sys.argv) < 2:
        print("Использование: python3 collect.py <start_date> [end_date|all] [account_type] [marketplace]")
        sys.exit(1)

    start = sys.argv[1]
    second = sys.argv[2] if len(sys.argv) > 2 else None

    if second == "all":
        collect_all(start)
    elif second and second not in ("MERCH", "KDP") and not second.isupper():
        # второй аргумент — end_date
        end          = second
        account_type = sys.argv[3] if len(sys.argv) > 3 else "MERCH"
        marketplace  = sys.argv[4] if len(sys.argv) > 4 else "US"
        collect(start, end, account_type, marketplace)
    else:
        account_type = second if second in ("MERCH", "KDP") else "MERCH"
        marketplace  = sys.argv[3] if len(sys.argv) > 3 else "US"
        collect(start, None, account_type, marketplace)