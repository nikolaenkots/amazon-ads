"""
send.py — отправка одобренных изменений в Amazon Ads API

Читает pending_changes_merch/kdp со статусом APPROVED,
группирует по профилю и типу операции, отправляет пачками,
пишет результат в change_log_merch/kdp.

Использование:
  python3 send.py                          # все APPROVED изменения
  python3 send.py --account MERCH          # только Merch
  python3 send.py --marketplace US         # только US
  python3 send.py --dry-run                # показать что будет отправлено, не отправлять
"""

import os
import json
import uuid
import time
import argparse
import requests
from datetime import datetime, timezone
from google.cloud import bigquery

# ── Конфиг ───────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

KEY_FILE = os.path.join(BASE_DIR, "config", "bigquery_key.json")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_FILE

with open(os.path.join(BASE_DIR, "config", "amazon_secrets.json")) as f:
    _AMZ = json.load(f)

PROFILES = {p["type"] + "_" + p["marketplace"]: p for p in _AMZ["profiles"]}

PENDING_TABLES = {
    "MERCH": f"{PROJECT_ID}.{DATASET}.pending_changes_merch",
    "KDP":   f"{PROJECT_ID}.{DATASET}.pending_changes_kdp",
}
CHANGELOG_TABLES = {
    "MERCH": f"{PROJECT_ID}.{DATASET}.change_log_merch",
    "KDP":   f"{PROJECT_ID}.{DATASET}.change_log_kdp",
}
CAMPAIGNS_TABLES = {
    "MERCH": f"{PROJECT_ID}.{DATASET}.campaigns_merch",
    "KDP":   f"{PROJECT_ID}.{DATASET}.campaigns_kdp",
}

AD_PRODUCT = "SPONSORED_PRODUCTS"

# ── Auth ──────────────────────────────────────────────────
def get_token():
    r = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": _AMZ["refresh_token"],
            "client_id":     _AMZ["client_id"],
            "client_secret": _AMZ["client_secret"],
        }
    )
    r.raise_for_status()
    return r.json()["access_token"]


def amz_headers(token, profile_id):
    return {
        "Authorization":                   f"Bearer {token}",
        "Amazon-Advertising-API-ClientId":  _AMZ["client_id"],
        "Amazon-Advertising-API-Scope":     str(profile_id),
        "Content-Type":                     "application/json",
    }


def amz_post(endpoint, path, headers, body, retries=3):
    """POST с retry при 429"""
    for attempt in range(retries):
        resp = requests.post(f"{endpoint}{path}", headers=headers, json=body)
        if resp.status_code == 429:
            wait = 5 * (attempt + 1)
            print(f"  Rate limit, ждём {wait}s...")
            time.sleep(wait)
            continue
        return resp
    raise RuntimeError(f"Rate limit после {retries} попыток")


# ── BigQuery helpers ──────────────────────────────────────
def fetch_pending(bq, account_type, marketplace_filter=None):
    """Читает APPROVED изменения из pending_changes"""
    table = PENDING_TABLES[account_type]
    where = "WHERE status = 'APPROVED'"
    if marketplace_filter:
        where += f" AND marketplace = '{marketplace_filter}'"
    sql = f"""
    SELECT id, created_at, entity_type, entity_id, profile_id, marketplace,
           field_name, old_value, new_value, retry_count
    FROM `{table}`
    {where}
    ORDER BY created_at
    """
    rows = list(bq.query(sql).result())
    return [dict(r) for r in rows]


def mark_sending(bq, account_type, ids):
    if not ids: return
    table = PENDING_TABLES[account_type]
    id_list = ','.join(f"'{i}'" for i in ids)
    bq.query(f"UPDATE `{table}` SET status='SENDING' WHERE id IN ({id_list})").result()


def mark_done(bq, account_type, ids, status):
    if not ids: return
    table = PENDING_TABLES[account_type]
    id_list = ','.join(f"'{i}'" for i in ids)
    bq.query(f"UPDATE `{table}` SET status='{status}' WHERE id IN ({id_list})").result()


def mark_failed(bq, account_type, ids, error_msg):
    if not ids: return
    table = PENDING_TABLES[account_type]
    safe_err = error_msg.replace("'", "''")[:500]
    id_list = ','.join(f"'{i}'" for i in ids)
    bq.query(f"""
        UPDATE `{table}`
        SET status='FAILED', error_msg='{safe_err}',
            retry_count = COALESCE(retry_count, 0) + 1
        WHERE id IN ({id_list})
    """).result()


def write_changelog(bq, account_type, entries):
    if not entries: return
    table = CHANGELOG_TABLES[account_type]
    job = bq.load_table_from_json(
        entries, table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    )
    job.result()


def update_campaigns_bq(bq, account_type, marketplace, updates):
    """
    Применяет успешные изменения в campaigns_merch/kdp.
    updates: list of {entity_type, entity_id, field_name, new_value, campaign_id}
    """
    table = CAMPAIGNS_TABLES[account_type]
    for u in updates:
        et     = u["entity_type"]
        eid    = u["entity_id"]
        field  = u["field_name"]
        val    = u["new_value"]
        mkt    = marketplace

        # Определяем SQL UPDATE
        if et == "campaign" and field == "state":
            sql = f"UPDATE `{table}` SET campaign_state='{val}' WHERE campaign_id='{eid}' AND marketplace='{mkt}'"
        elif et == "campaign" and field == "name":
            safe_val = val.replace("'", "''")
            sql = f"UPDATE `{table}` SET campaign_name='{safe_val}' WHERE campaign_id='{eid}' AND marketplace='{mkt}'"
        elif et == "campaign" and field == "daily_budget":
            sql = f"UPDATE `{table}` SET daily_budget={float(val)} WHERE campaign_id='{eid}' AND marketplace='{mkt}'"
        elif et == "ad_group" and field == "state":
            sql = f"UPDATE `{table}` SET ad_group_state='{val}' WHERE ad_group_id='{eid}' AND marketplace='{mkt}'"
        elif et == "ad_group" and field == "name":
            safe_val = val.replace("'", "''")
            sql = f"UPDATE `{table}` SET ad_group_name='{safe_val}' WHERE ad_group_id='{eid}' AND marketplace='{mkt}'"
        elif et == "keyword" and field == "bid":
            sql = f"UPDATE `{table}` SET keyword_bid={float(val)} WHERE keyword_id='{eid}' AND marketplace='{mkt}'"
        elif et == "keyword" and field == "state":
            sql = f"UPDATE `{table}` SET keyword_state='{val}' WHERE keyword_id='{eid}' AND marketplace='{mkt}'"
        elif et == "campaign" and field == "portfolio_id":
            sql = f"UPDATE `{table}` SET portfolio_id='{val}' WHERE campaign_id='{eid}' AND marketplace='{mkt}'"
        elif et == "campaign" and field == "end_date":
            null_or_val = f"'{val}'" if val else "NULL"
            sql = f"UPDATE `{table}` SET end_date={null_or_val} WHERE campaign_id='{eid}' AND marketplace='{mkt}'"
        elif et == "ad_group" and field == "default_bid":
            sql = f"UPDATE `{table}` SET ad_group_default_bid={float(val)} WHERE ad_group_id='{eid}' AND marketplace='{mkt}'"
        elif et == "target" and field == "bid":
            sql = f"UPDATE `{table}` SET target_bid={float(val)} WHERE target_id='{eid}' AND marketplace='{mkt}'"
        elif et == "target" and field == "state":
            sql = f"UPDATE `{table}` SET target_state='{val}' WHERE target_id='{eid}' AND marketplace='{mkt}'"
        elif et == "product_ad" and field == "state":
            sql = f"UPDATE `{table}` SET ad_state='{val}' WHERE ad_id='{eid}' AND marketplace='{mkt}'"
        elif et in ("negative_delete",):
            sql = f"DELETE FROM `{table}` WHERE keyword_id='{eid}' AND marketplace='{mkt}' AND entity_type='negative_keyword'"
        else:
            continue  # keyword_add, negative_add — вставка, не обновление

        try:
            bq.query(sql).result()
        except Exception as e:
            print(f"  BQ update warning: {e}")


# ── Группировка изменений по API-операциям ────────────────
def group_changes(changes):
    """
    Возвращает dict: {
        'update_campaigns':  [changes...],
        'update_ad_groups':  [changes...],
        'update_targets':    [changes...],  # bid/state keyword
        'create_targets':    [changes...],  # keyword_add, negative_add
        'delete_targets':    [changes...],  # negative_delete
    }
    """
    groups = {
        "update_campaigns": [],
        "update_ad_groups": [],
        "update_targets":   [],
        "create_targets":   [],
        "delete_targets":   [],
    }
    for c in changes:
        et = c["entity_type"]
        fn = c.get("field_name", "")
        if et == "campaign" and fn in ("state", "name", "daily_budget", "portfolio_id", "end_date"):
            groups["update_campaigns"].append(c)
        elif et == "ad_group" and fn in ("state", "name", "default_bid"):
            groups["update_ad_groups"].append(c)
        elif et in ("keyword", "target") and fn in ("bid", "state"):
            groups["update_targets"].append(c)
        elif et == "product_ad" and fn == "state":
            groups["update_targets"].append(c)  # через update/ads
        elif et in ("keyword_add", "negative_add"):
            groups["create_targets"].append(c)
        elif et == "negative_delete":
            groups["delete_targets"].append(c)
        else:
            print(f"  Неизвестный тип: {et}/{fn}, пропускаем")
    return groups


# ── Отправка в Amazon ─────────────────────────────────────
def send_update_campaigns(endpoint, headers, changes, dry_run=False):
    """Обновить state/name/budget кампаний"""
    payloads = []
    for c in changes:
        fn  = c["field_name"]
        eid = c["entity_id"]
        val = c["new_value"]
        item = {"campaignId": eid}
        if fn == "state":
            item["state"] = val
        elif fn == "name":
            item["name"] = val
        elif fn == "daily_budget":
            item["budgets"] = [{"budgetValue": {"monetaryBudgetValue": {"monetaryBudget": {"value": float(val), "currencyCode": "USD"}}}}]
        elif fn == "portfolio_id":
            item["portfolioId"] = val
        elif fn == "end_date":
            # SP API v1 использует endDateTime в формате ISO 8601
            # val приходит как YYYY-MM-DD из HTML date input
            if val:
                item["endDateTime"] = val + "T23:59:59Z"
            else:
                item["endDateTime"] = None  # None = убрать дату
        payloads.append(item)

    if dry_run:
        print(f"  [DRY RUN] update/campaigns: {json.dumps(payloads, ensure_ascii=False)[:200]}")
        return {i: "SUCCESS" for i in range(len(changes))}

    resp = amz_post(endpoint, "/adsApi/v1/update/campaigns", headers, {"campaigns": payloads})
    return parse_multi_response(resp, "campaigns", len(changes))


def send_update_ad_groups(endpoint, headers, changes, dry_run=False):
    """Обновить state/name групп"""
    payloads = []
    for c in changes:
        fn  = c["field_name"]
        eid = c["entity_id"]
        val = c["new_value"]
        item = {"adGroupId": eid}
        if fn == "state":
            item["state"] = val
        elif fn == "name":
            item["name"] = val
        elif fn == "default_bid":
            item["bid"] = {"defaultBid": float(val)}
        payloads.append(item)

    if dry_run:
        print(f"  [DRY RUN] update/adGroups: {json.dumps(payloads, ensure_ascii=False)[:200]}")
        return {i: "SUCCESS" for i in range(len(changes))}

    resp = amz_post(endpoint, "/adsApi/v1/update/adGroups", headers, {"adGroups": payloads})
    return parse_multi_response(resp, "adGroups", len(changes))


def send_update_targets(endpoint, headers, changes, dry_run=False):
    """Обновить bid/state ключевых слов"""
    payloads = []
    ad_payloads = []
    for c in changes:
        fn  = c["field_name"]
        eid = c["entity_id"]
        val = c["new_value"]
        et  = c["entity_type"]
        if et == "product_ad":
            ad_payloads.append({"adId": eid, "state": val})
        else:
            item = {"targetId": eid}
            if fn == "bid":
                item["bid"] = {"value": float(val), "currencyCode": "USD"}
            elif fn == "state":
                item["state"] = val
            payloads.append(item)

    # Отправить объявления отдельно
    if ad_payloads and not dry_run:
        resp_ads = amz_post(endpoint, "/adsApi/v1/update/ads", headers, {"ads": ad_payloads})
        ad_results = parse_multi_response(resp_ads, "ads", len(ad_payloads))
        # Добавим результаты обратно в общий results по индексу
        # Сначала отправим только target payloads ниже

    if dry_run:
        print(f"  [DRY RUN] update/targets: {json.dumps(payloads, ensure_ascii=False)[:200]}")
        return {i: "SUCCESS" for i in range(len(changes))}

    resp = amz_post(endpoint, "/adsApi/v1/update/targets", headers, {"targets": payloads})
    return parse_multi_response(resp, "targets", len(changes))


def send_create_targets(endpoint, headers, changes, dry_run=False):
    """Создать новые ключевые слова или минус слова"""
    payloads = []
    for c in changes:
        et  = c["entity_type"]
        val = json.loads(c["new_value"])  # {text, match_type, bid?, ad_group_id, campaign_id}
        ag_id = val.get("ad_group_id") or c["entity_id"]
        camp_id = val.get("campaign_id", "")

        if et == "keyword_add":
            item = {
                "adGroupId":   ag_id,
                "campaignId":  camp_id,
                "negative":    False,
                "state":       "ENABLED",
                "targetDetails": {
                    "keywordTarget": {
                        "matchType": val["match_type"],
                        "keyword":   val["text"],
                    }
                }
            }
            if val.get("bid"):
                item["bid"] = {"value": float(val["bid"]), "currencyCode": "USD"}
        elif et == "negative_add":
            item = {
                "adGroupId":  ag_id,
                "campaignId": camp_id,
                "negative":   True,
                "state":      "ENABLED",
                "targetDetails": {
                    "keywordTarget": {
                        "matchType": val.get("match_type", "NEGATIVE_EXACT"),
                        "keyword":   val["text"],
                    }
                }
            }
        else:
            continue
        payloads.append(item)

    if dry_run:
        print(f"  [DRY RUN] create/targets: {json.dumps(payloads, ensure_ascii=False)[:200]}")
        return {i: "SUCCESS" for i in range(len(changes))}

    resp = amz_post(endpoint, "/adsApi/v1/create/targets", headers, {"targets": payloads})
    return parse_multi_response(resp, "targets", len(changes))


def send_delete_targets(endpoint, headers, changes, dry_run=False):
    """Удалить минус слова"""
    payloads = [{"targetId": c["entity_id"]} for c in changes]

    if dry_run:
        print(f"  [DRY RUN] delete/targets: {[c['entity_id'] for c in changes]}")
        return {i: "SUCCESS" for i in range(len(changes))}

    resp = amz_post(endpoint, "/adsApi/v1/delete/targets", headers, {"targets": payloads})
    return parse_multi_response(resp, "targets", len(changes))


def parse_multi_response(resp, key, count):
    """
    Разбирает 207 Multi-Status ответ Amazon API.
    Возвращает dict: {index: "SUCCESS"|error_message}
    """
    if resp.status_code not in (200, 207):
        # Всё упало — помечаем все как failed
        return {i: f"HTTP {resp.status_code}: {resp.text[:200]}" for i in range(count)}

    results = {}
    data = resp.json()
    items = data.get(key, [])
    for item in items:
        idx  = item.get("index", 0)
        code = item.get("code", "")
        if code in ("SUCCESS", "") or not code:
            results[idx] = "SUCCESS"
        else:
            details = item.get("details", [{}])
            msg = details[0].get("message", code) if details else code
            results[idx] = f"{code}: {msg}"

    # Заполняем пропущенные индексы как SUCCESS (Amazon не всегда возвращает все)
    for i in range(count):
        if i not in results:
            results[i] = "SUCCESS"
    return results


# ── Основной цикл ─────────────────────────────────────────
def send_changes(account_type="MERCH", marketplace_filter=None, dry_run=False):
    bq      = bigquery.Client(project=PROJECT_ID)
    sent_at = datetime.now(tz=timezone.utc).isoformat()

    changes = fetch_pending(bq, account_type, marketplace_filter)
    if not changes:
        print(f"[{account_type}] Нет APPROVED изменений.")
        return

    print(f"[{account_type}] Найдено {len(changes)} изменений.")

    # Группируем по профилю (marketplace)
    by_profile = {}
    for c in changes:
        mkt = c["marketplace"]
        by_profile.setdefault(mkt, []).append(c)

    all_changelog = []
    all_success   = []
    all_failed    = []

    token = get_token()

    for mkt, mkt_changes in by_profile.items():
        if marketplace_filter and mkt != marketplace_filter:
            continue

        profile_key = f"{account_type}_{mkt}"
        profile = PROFILES.get(profile_key)
        if not profile:
            print(f"  Профиль {profile_key} не найден, пропускаем {len(mkt_changes)} изменений")
            for c in mkt_changes:
                all_failed.append(c["id"])
            continue

        endpoint   = profile.get("api_endpoint", "https://advertising-api.amazon.com")
        profile_id = profile["id"]
        headers    = amz_headers(token, profile_id)

        print(f"\n  Marketplace: {mkt} ({len(mkt_changes)} изменений)")

        # Помечаем как SENDING
        if not dry_run:
            mark_sending(bq, account_type, [c["id"] for c in mkt_changes])

        grouped = group_changes(mkt_changes)

        # Функции отправки по типу
        send_funcs = [
            ("update_campaigns", send_update_campaigns),
            ("update_ad_groups", send_update_ad_groups),
            ("update_targets",   send_update_targets),
            ("create_targets",   send_create_targets),
            ("delete_targets",   send_delete_targets),
        ]

        bq_updates = []

        for group_key, send_fn in send_funcs:
            batch = grouped[group_key]
            if not batch:
                continue

            print(f"    {group_key}: {len(batch)} шт.")
            results = send_fn(endpoint, headers, batch, dry_run=dry_run)

            for idx, change in enumerate(batch):
                result = results.get(idx, "SUCCESS")
                success = result == "SUCCESS"

                all_changelog.append({
                    "id":           str(uuid.uuid4()),
                    "pending_id":   change["id"],
                    "sent_at":      sent_at,
                    "entity_type":  change["entity_type"],
                    "entity_id":    change["entity_id"],
                    "profile_id":   str(change["profile_id"]),
                    "marketplace":  mkt,
                    "field_name":   change.get("field_name", ""),
                    "old_value":    change.get("old_value", ""),
                    "new_value":    change["new_value"],
                    "result":       "SUCCESS" if success else "FAILED",
                    "error_msg":    "" if success else result,
                })

                if success:
                    all_success.append(change["id"])
                    bq_updates.append(change)
                    print(f"      ✓ {change['entity_type']}/{change.get('field_name','')} → {change['new_value'][:50]}")
                else:
                    all_failed.append(change["id"])
                    print(f"      ✗ {change['entity_type']}/{change.get('field_name','')} — {result[:100]}")

        # Применяем успешные изменения в BigQuery
        if not dry_run and bq_updates:
            update_campaigns_bq(bq, account_type, mkt, bq_updates)

    # Финализируем статусы и пишем лог
    if not dry_run:
        if all_success:
            mark_done(bq, account_type, all_success, "SENT")
        if all_failed:
            mark_failed(bq, account_type, all_failed, "Last batch failed")
        if all_changelog:
            write_changelog(bq, account_type, all_changelog)

    print(f"\n✓ Готово: {len(all_success)} успешно, {len(all_failed)} с ошибками")


# ── CLI ───────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Отправка изменений в Amazon Ads API")
    parser.add_argument("--account",     default="MERCH", help="MERCH или KDP")
    parser.add_argument("--marketplace", default=None,    help="US, UK, DE...")
    parser.add_argument("--all",         action="store_true", help="Все аккаунты")
    parser.add_argument("--dry-run",     action="store_true", help="Показать без отправки")
    args = parser.parse_args()

    if args.all:
        for acct in ("MERCH", "KDP"):
            send_changes(acct, args.marketplace, args.dry_run)
    else:
        send_changes(args.account.upper(), args.marketplace, args.dry_run)