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
    """Читает APPROVED и застрявшие SENDING из pending_changes.
    Исключает те, что уже есть в change_log с result=SUCCESS (идемпотентность).
    """
    table     = PENDING_TABLES[account_type]
    log_table = CHANGELOG_TABLES[account_type]
    mkt_filter = f"AND p.marketplace = '{marketplace_filter}'" if marketplace_filter else ""
    sql = f"""
    SELECT p.id, p.created_at, p.entity_type, p.entity_id, p.profile_id, p.marketplace,
           p.field_name, p.old_value, p.new_value, p.retry_count
    FROM `{table}` p
    WHERE p.status IN ('APPROVED', 'SENDING')
    {mkt_filter}
    AND p.id NOT IN (
        SELECT pending_id FROM `{log_table}` WHERE result = 'SUCCESS'
    )
    ORDER BY p.created_at
    """
    rows = list(bq.query(sql).result())
    return [dict(r) for r in rows]


def reset_stale_sending(bq, account_type):
    """Сбрасывает застрявшие SENDING → APPROVED если нет записи SUCCESS в логе.
    Вызывается в начале send_changes чтобы они попали в следующий запуск.
    """
    table     = PENDING_TABLES[account_type]
    log_table = CHANGELOG_TABLES[account_type]
    bq.query(f"""
        UPDATE `{table}`
        SET status = 'APPROVED'
        WHERE status = 'SENDING'
        AND id NOT IN (
            SELECT pending_id FROM `{log_table}` WHERE result = 'SUCCESS'
        )
    """).result()


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
        elif et == "campaign_delete":
            sql = f"DELETE FROM `{table}` WHERE campaign_id='{eid}' AND marketplace='{mkt}'"
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
        "update_campaigns":  [],
        "update_ad_groups":  [],
        "update_targets":    [],
        "create_targets":    [],
        "delete_targets":    [],
        "create_ad_groups":  [],
        "create_campaigns":  [],
        "delete_campaigns":  [],
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
        elif et in ("negative_add", "negative_product_add"):
            groups["create_targets"].append(c)
        elif et == "keyword_add":
            val = json.loads(c.get("new_value", "{}")) if c.get("new_value") else {}
            # Если есть ad_group_name но нет ad_group_id — ждём создания группы
            if val.get("ad_group_name") and not val.get("ad_group_id"):
                groups["create_ad_groups"].append(c)
            else:
                groups["create_targets"].append(c)
        elif et in ("ad_group_add", "product_ad_add"):
            groups["create_ad_groups"].append(c)
        elif et == "negative_delete":
            groups["delete_targets"].append(c)
        elif et == "campaign_create":
            groups["create_campaigns"].append(c)
        elif et == "campaign_delete":
            groups["delete_campaigns"].append(c)
        else:
            print(f"  Неизвестный тип: {et}/{fn}, пропускаем")
    return groups


# ── Отправка в Amazon ─────────────────────────────────────
def send_update_campaigns(endpoint, headers, changes, dry_run=False):
    """Обновить state/name/budget кампаний.

    Мержим несколько изменений одной кампании в один payload —
    иначе Amazon возвращает DUPLICATE_RESOURCE_ID_FOUND.
    Для завершённых кампаний end_date обязательно идёт первым полем.
    """
    # Группируем по campaign_id, сохраняя порядок (end_date → state → budget → ...)
    merged = {}   # campaign_id → {payload_dict, [change_indices]}
    order  = []   # порядок campaign_id для итогового маппинга результат → индекс

    FIELD_PRIORITY = {"end_date": 0, "state": 1, "daily_budget": 2,
                      "portfolio_id": 3, "name": 4}

    for orig_idx, change in enumerate(changes):
        fn  = change["field_name"]
        eid = change["entity_id"]
        val = change["new_value"]
        mkt_code = change.get("marketplace", "US").upper()

        if eid not in merged:
            merged[eid] = {"item": {"campaignId": eid}, "indices": [], "mkt": mkt_code}
            order.append(eid)
        merged[eid]["indices"].append(orig_idx)

        item = merged[eid]["item"]
        if fn == "state":
            item["state"] = val
        elif fn == "name":
            item["name"] = val
        elif fn == "daily_budget":
            item["budgets"] = [{
                "budgetType": "MONETARY",
                "recurrenceTimePeriod": "DAILY",
                "budgetValue": {
                    "monetaryBudgetValue": {
                        "monetaryBudget": {"value": float(val)},
                        "marketplaceSettings": [
                            {"marketplace": mkt_code, "monetaryBudget": {"value": float(val)}}
                        ]
                    }
                }
            }]
        elif fn == "portfolio_id":
            item["portfolioId"] = val
        elif fn == "end_date":
            if val:
                # mkt_code уже определён выше из change.get("marketplace")
                MKT_OFFSET = {
                    "US":-5,"CA":-5,"MX":-6,"UK":0,"GB":0,
                    "DE":1,"FR":1,"IT":1,"ES":1,"NL":1,"BE":1,"PL":1,"SE":1,
                    "TR":3,"AU":10,"JP":9,"IN":5,"SG":8,"AE":4,"SA":3,"BR":-3,
                }
                offset = MKT_OFFSET.get(mkt_code, 0)
                sign = "+" if offset >= 0 else "-"
                tz_str = f"{sign}{abs(offset):02d}:00"
                item["endDateTime"] = f"{val}T23:59:59{tz_str}"
            else:
                item["endDateTime"] = None

    payloads = [merged[eid]["item"] for eid in order]
    # Map: merged payload index → list of original change indices
    idx_map  = {i: merged[eid]["indices"] for i, eid in enumerate(order)}

    if dry_run:
        print(f"  [DRY RUN] update/campaigns ({len(payloads)} merged): "
              f"{json.dumps(payloads, ensure_ascii=False)[:300]}")
        return {orig_i: "SUCCESS" for batch in idx_map.values() for orig_i in batch}

    resp = amz_post(endpoint, "/adsApi/v1/update/campaigns", headers, {"campaigns": payloads})
    print(f"  [DEBUG] update/campaigns status={resp.status_code}")
    try:
        rj = resp.json()
        print(f"  [DEBUG] response: {json.dumps(rj, ensure_ascii=False)[:600]}")
    except Exception:
        print(f"  [DEBUG] raw: {resp.text[:400]}")

    # Parse merged results and expand back to original indices
    merged_results = parse_multi_response(resp, "campaigns", len(payloads))
    results = {}
    for batch_idx, orig_indices in idx_map.items():
        result = merged_results.get(batch_idx, "SUCCESS")
        for orig_i in orig_indices:
            results[orig_i] = result
    return results



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
    """Обновить bid/state ключевых слов. Мёрджит несколько изменений одного targetId в один payload."""
    MKT_CURRENCY = {
        "US":"USD","CA":"CAD","UK":"GBP","GB":"GBP",
        "DE":"EUR","FR":"EUR","IT":"EUR","ES":"EUR","NL":"EUR",
        "AU":"AUD","JP":"JPY","IN":"INR","MX":"MXN","BR":"BRL",
        "SE":"SEK","PL":"PLN","BE":"EUR","TR":"TRY","SG":"SGD",
    }

    ad_payloads = []
    ad_indices  = []

    merged  = {}   # targetId → {"item": {...}, "indices": [...]}
    order   = []   # сохраняем порядок первого появления targetId

    for i, c in enumerate(changes):
        fn  = c["field_name"]
        eid = c["entity_id"]
        val = c["new_value"]
        et  = c["entity_type"]

        if et == "product_ad":
            ad_payloads.append({"adId": eid, "state": val})
            ad_indices.append(i)
            continue

        if eid not in merged:
            merged[eid] = {"item": {"targetId": eid}, "indices": []}
            order.append(eid)
        merged[eid]["indices"].append(i)

        item = merged[eid]["item"]
        if fn == "bid":
            mkt_code = c.get("marketplace", "US").upper()
            currency = MKT_CURRENCY.get(mkt_code, "USD")
            item["bid"] = {"bid": float(val), "currencyCode": currency}
        elif fn == "state":
            item["state"] = val

    payloads = [merged[eid]["item"] for eid in order]
    idx_map  = {i: merged[eid]["indices"] for i, eid in enumerate(order)}

    results = {}

    # Отправить объявления отдельно
    if ad_payloads and not dry_run:
        resp_ads = amz_post(endpoint, "/adsApi/v1/update/ads", headers, {"ads": ad_payloads})
        ad_res = parse_multi_response(resp_ads, "ads", len(ad_payloads))
        for j, orig_i in enumerate(ad_indices):
            results[orig_i] = ad_res.get(j, "SUCCESS")

    if dry_run:
        print(f"  [DRY RUN] update/targets ({len(payloads)} merged): "
              f"{json.dumps(payloads, ensure_ascii=False)[:300]}")
        return {i: "SUCCESS" for i in range(len(changes))}

    if payloads:
        resp = amz_post(endpoint, "/adsApi/v1/update/targets", headers, {"targets": payloads})
        print(f"  [DEBUG] update/targets status={resp.status_code}")
        try:
            rj = resp.json()
            print(f"  [DEBUG] response: {json.dumps(rj, ensure_ascii=False)[:600]}")
        except Exception:
            print(f"  [DEBUG] raw: {resp.text[:400]}")

        merged_results = parse_multi_response(resp, "targets", len(payloads))
        for batch_idx, orig_indices in idx_map.items():
            result = merged_results.get(batch_idx, "SUCCESS")
            for orig_i in orig_indices:
                results[orig_i] = result

    return results


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
                "adProduct":   "SPONSORED_PRODUCTS",
                "negative":    False,
                "state":       "ENABLED",
                "targetType":  "KEYWORD",
                "targetDetails": {
                    "keywordTarget": {
                        "matchType": val["match_type"],
                        "keyword":   val["text"],
                    }
                }
            }
            if val.get("bid"):
                mkt_code = c.get("marketplace", "US").upper()
                MKT_CURRENCY = {
                    "US":"USD","CA":"CAD","UK":"GBP","GB":"GBP",
                    "DE":"EUR","FR":"EUR","IT":"EUR","ES":"EUR","NL":"EUR",
                    "AU":"AUD","JP":"JPY","IN":"INR","MX":"MXN","BR":"BRL",
                }
                currency = MKT_CURRENCY.get(mkt_code, "USD")
                item["bid"] = {"bid": float(val["bid"]), "currencyCode": currency}
        elif et == "negative_add":
            # matchType без префикса NEGATIVE_ (API принимает EXACT/PHRASE/BROAD)
            raw_mt = val.get("match_type", "NEGATIVE_EXACT")
            mt = raw_mt.replace("NEGATIVE_", "")  # NEGATIVE_EXACT → EXACT
            item = {
                "adGroupId":  ag_id,
                "campaignId": camp_id,
                "adProduct":  "SPONSORED_PRODUCTS",
                "negative":   True,
                "state":      "ENABLED",
                "targetType": "KEYWORD",
                "targetDetails": {
                    "keywordTarget": {
                        "matchType": mt,
                        "keyword":   val["text"],
                    }
                }
            }
        elif et == "negative_product_add":
            item = {
                "adGroupId":  ag_id,
                "campaignId": camp_id,
                "adProduct":  "SPONSORED_PRODUCTS",
                "negative":   True,
                "state":      "ENABLED",
                "targetType": "PRODUCT",
                "targetDetails": {
                    "productTarget": {
                        "matchType":     "PRODUCT_EXACT",
                        "productIdType": "ASIN",
                        "product": {
                            "productId":     val["asin"],
                            "productIdType": "ASIN",
                        }
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
    print(f"  [DEBUG] create/targets status={resp.status_code}")
    try:
        rj = resp.json()
        print(f"  [DEBUG] response: {json.dumps(rj, ensure_ascii=False)[:800]}")
    except Exception:
        print(f"  [DEBUG] raw: {resp.text[:400]}")
    return parse_multi_response(resp, "targets", len(changes))


def send_delete_targets(endpoint, headers, changes, dry_run=False):
    """Удалить минус слова"""
    payloads = [{"targetId": c["entity_id"]} for c in changes]

    if dry_run:
        print(f"  [DRY RUN] delete/targets: {[c['entity_id'] for c in changes]}")
        return {i: "SUCCESS" for i in range(len(changes))}

    resp = amz_post(endpoint, "/adsApi/v1/delete/targets", headers, {"targets": payloads})
    return parse_multi_response(resp, "targets", len(changes))


def send_delete_campaigns(endpoint, headers, changes, dry_run=False):
    """Удалить кампании целиком (POST /adsApi/v1/delete/campaigns, до 1000 за раз)"""
    campaign_ids = [c["entity_id"] for c in changes]

    if dry_run:
        print(f"  [DRY RUN] delete/campaigns: {campaign_ids}")
        return {i: "SUCCESS" for i in range(len(changes))}

    resp = amz_post(endpoint, "/adsApi/v1/delete/campaigns", headers, {"campaignIds": campaign_ids})
    print(f"  [DEBUG] delete/campaigns status={resp.status_code}")
    try:
        rj = resp.json()
        print(f"  [DEBUG] response: {json.dumps(rj, ensure_ascii=False)[:600]}")
    except Exception:
        print(f"  [DEBUG] raw: {resp.text[:400]}")

    return parse_multi_response(resp, "campaigns", len(changes))


def send_create_campaigns(endpoint, headers, changes, dry_run=False):
    """
    Создаёт полные кампании из campaign_create записей pending_changes.
    new_value = JSON {type, name, budget, bidadj, portfolio, start, end,
                      groups:[{name, asin, bid, keywords:[{text,mt,bid}]}]}
    Последовательность:
      1. create/campaigns
      2. (bidAdjustments included inline in campaign payload via optimizations.bidSettings.bidAdjustments.placementBidAdjustments)
      3. create/adGroups
      4. create/ads
      5. create/targets (ключи для MANUAL)
    """
    MKT_CURRENCY = {
        "US":"USD","CA":"CAD","UK":"GBP","GB":"GBP",
        "DE":"EUR","FR":"EUR","IT":"EUR","ES":"EUR","NL":"EUR",
        "AU":"AUD","JP":"JPY","IN":"INR","MX":"MXN","SG":"SGD",
        "SE":"SEK","PL":"PLN","TR":"TRY","BE":"EUR",
    }
    MKT_OFFSET = {"US":-5,"CA":-5,"UK":0,"GB":0,"DE":1,"FR":1,"IT":1,"ES":1,"AU":10,"JP":9}

    results = {i: "SUCCESS" for i in range(len(changes))}

    camp_data = []
    for i, ch in enumerate(changes):
        try:
            val = json.loads(ch.get("new_value", "{}"))
            val["_idx"] = i
            val["_mkt"] = ch.get("marketplace", "US").upper()
            camp_data.append(val)
        except Exception as e:
            results[i] = f"JSON parse error: {e}"

    if not camp_data:
        return results

    mkt      = camp_data[0]["_mkt"]
    currency = MKT_CURRENCY.get(mkt, "USD")
    offset   = MKT_OFFSET.get(mkt, 0)
    sign     = "+" if offset >= 0 else "-"

    # 1. create/campaigns
    camp_payloads = []
    for c in camp_data:
        budget = float(c.get("budget") or 0)
        start  = c.get("start", "")
        end    = c.get("end", "")
        BID_STRATEGY_MAP = {
            "Dynamic bids - down only":   "SALES_DOWN_ONLY",
            "Dynamic bids - up and down": "SALES_UP_AND_DOWN",
            "Fixed bid":                  "MANUAL",
        }
        strategy = BID_STRATEGY_MAP.get(c.get("bidStrategy"), "SALES_DOWN_ONLY")
        payload = {
            "adProduct": "SPONSORED_PRODUCTS",
            "name":      c["name"],
            "state":     "ENABLED",
            "marketplaceScope": "SINGLE_MARKETPLACE",
            "marketplaces": [mkt],
            "optimizations": {"bidSettings": {"bidStrategy": strategy}},
            "budgets": [{
                "budgetType": "MONETARY",
                "recurrenceTimePeriod": "DAILY",
                "budgetValue": {"monetaryBudgetValue": {
                    "monetaryBudget": {"value": budget},
                    "marketplaceSettings": [{"marketplace": mkt, "monetaryBudget": {"value": budget}}]
                }}
            }],
        }
        payload["autoCreationSettings"] = {
            "autoCreateTargets": (c.get("type") == "auto")
        }
        bidadj = int(c.get("bidadj") or 0)
        if bidadj > 0:
            payload["optimizations"]["bidSettings"]["bidAdjustments"] = {
                "placementBidAdjustments": [
                    {"placement": "TOP_OF_SEARCH", "percentage": bidadj}
                ]
            }
        if start:
            payload["startDateTime"] = f"{start}T00:00:00Z"
        if end:
            payload["endDateTime"] = f"{end}T23:59:59{sign}{abs(offset):02d}:00"
        if c.get("portfolio"):
            payload["portfolioId"] = c["portfolio"]
        camp_payloads.append(payload)

    if dry_run:
        print(f"  [DRY RUN] create/campaigns: {len(camp_payloads)} шт.")
        for c in camp_data:
            print(f"    {c.get('type','?').upper()} — {c['name']}")
        return results

    resp = amz_post(endpoint, "/adsApi/v1/create/campaigns", headers, {"campaigns": camp_payloads})
    print(f"  [DEBUG] create/campaigns status={resp.status_code}")
    try:
        rj = resp.json()
        print(f"  [DEBUG] {json.dumps(rj, ensure_ascii=False)[:400]}")
    except Exception:
        for i in range(len(changes)):
            results[i] = f"HTTP {resp.status_code}"
        return results

    idx_to_camp_id = {}
    success_items = rj.get("success", []) + rj.get("partialSuccess", [])
    for n, item in enumerate(success_items):
        idx = item.get("index", -1)
        if idx == -1 and len(camp_payloads) == 1:
            idx = 0
        cid = item.get("campaignId") or (item.get("campaign") or {}).get("campaignId")
        if 0 <= idx < len(camp_payloads) and cid:
            idx_to_camp_id[idx] = cid
            print(f"    ✓ Campaign: {camp_payloads[idx]['name']} → {cid}")
    for item in rj.get("error", []):
        idx = item.get("index", -1)
        if 0 <= idx < len(camp_data):
            results[camp_data[idx]["_idx"]] = item.get("errorMessage", "ERROR")
            print(f"    ✗ Campaign error: {item.get('errorMessage','?')}")

    # 3. create/adGroups
    ag_payloads, ag_meta = [], []
    for ci, c in enumerate(camp_data):
        cid = idx_to_camp_id.get(ci)
        if not cid: continue
        for g in c.get("groups", []):
            ag_payloads.append({
                "adProduct": "SPONSORED_PRODUCTS", "campaignId": cid,
                "name": g["name"], "state": "ENABLED",
                "bid": {"defaultBid": float(g.get("bid") or 0)},
            })
            ag_meta.append((ci, cid, g))

    idx_to_ag_id = {}
    if ag_payloads:
        ra = amz_post(endpoint, "/adsApi/v1/create/adGroups", headers, {"adGroups": ag_payloads})
        print(f"  [DEBUG] create/adGroups status={ra.status_code}")
        print(f"  [DEBUG] payload: {json.dumps(ag_payloads, ensure_ascii=False)[:400]}")
        try:
            rja = ra.json()
            print(f"  [DEBUG] response: {json.dumps(rja, ensure_ascii=False)[:600]}")
            for item in rja.get("success", []) + rja.get("partialSuccess", []):
                idx = item.get("index", -1)
                aid = item.get("adGroupId") or (item.get("adGroup") or {}).get("adGroupId")
                if 0 <= idx < len(ag_payloads) and aid:
                    idx_to_ag_id[idx] = aid
                    print(f"    ✓ AdGroup: {ag_payloads[idx]['name']} → {aid}")
            for item in rja.get("error", []):
                print(f"    ✗ AdGroup: {item.get('errorMessage','?')}")
        except Exception: pass

    # 4. create/ads
    ad_payloads = []
    for ag_idx, (ci, cid, g) in enumerate(ag_meta):
        ag_id = idx_to_ag_id.get(ag_idx)
        if not ag_id or not g.get("asin"): continue
        ad_payloads.append({
            "adProduct": "SPONSORED_PRODUCTS", "adType": "PRODUCT_AD",
            "adGroupId": ag_id, "state": "ENABLED",
            "creative": {"productCreative": {"productCreativeSettings": {
                "advertisedProduct": {"productId": g["asin"], "productIdType": "ASIN"}
            }}}
        })
    if ad_payloads:
        print(f"  [DEBUG] ads payload: {json.dumps(ad_payloads, ensure_ascii=False)[:400]}")
        rad = amz_post(endpoint, "/adsApi/v1/create/ads", headers, {"ads": ad_payloads})
        print(f"  [DEBUG] create/ads status={rad.status_code}")
        try:
            rjad = rad.json()
            print(f"  [DEBUG] ads response: {json.dumps(rjad, ensure_ascii=False)[:800]}")
            ok = len(rjad.get("success",[])); err = len(rjad.get("error",[]))
            print(f"    Ads: {ok} OK, {err} ошибок")
            for item in rjad.get("error",[]):
                errs = item.get("errors") or []
                msgs = "; ".join(e.get("message","") for e in errs) or item.get("errorMessage","?")
                print(f"    ✗ Ad: {msgs}")
        except Exception as e:
            print(f"  [DEBUG] ads parse error: {e}, raw: {rad.text[:400]}")

    # 5. create/targets (MANUAL keywords)
    kw_payloads = []
    for ag_idx, (ci, cid, g) in enumerate(ag_meta):
        ag_id = idx_to_ag_id.get(ag_idx)
        if not ag_id: continue
        c = camp_data[ci]
        if c.get("type") != "manual": continue
        for kw in g.get("keywords", []):
            if isinstance(kw, dict):
                kw_text = kw.get("text", "")
                kw_mt   = kw.get("mt", g.get("matchType", "broad"))
                kw_bid  = kw.get("bid")
            else:
                kw_text = str(kw)
                kw_mt   = g.get("matchType", "broad")
                kw_bid  = None
            kw_text = kw_text.strip()
            if not kw_text: continue
            kw_payloads.append({
                "adGroupId": ag_id,
                "adProduct": "SPONSORED_PRODUCTS", "negative": False, "state": "ENABLED",
                "targetType": "KEYWORD",
                "targetDetails": {"keywordTarget": {
                    "matchType": (kw_mt or "broad").upper(), "keyword": kw_text
                }},
                "bid": {"bid": float(kw_bid or g.get("bid") or 0), "currencyCode": currency},
            })
    if kw_payloads:
        rkw = amz_post(endpoint, "/adsApi/v1/create/targets", headers, {"targets": kw_payloads})
        print(f"  [DEBUG] create/targets (kw) status={rkw.status_code}")
        try:
            rjkw = rkw.json()
            ok = len(rjkw.get("success",[])); err = len(rjkw.get("error",[]))
            print(f"    Keywords: {ok} OK, {err} ошибок")
            for item in rjkw.get("error",[]): print(f"    ✗ KW: {item.get('errorMessage','?')}")
        except Exception: pass

    return results


def send_create_ad_groups(endpoint, headers, changes, dry_run=False):
    """
    Создать группы объявлений + связанные keyword_add / product_ad_add.

    Логика как в Amazon Bulk Sheet:
      1. Создаём все ad_group_add батчем
      2. Из ответа берём adGroupId для каждой созданной группы (по имени)
      3. Подставляем adGroupId в keyword_add / product_ad_add с тем же ad_group_name
      4. Отправляем их
    """
    # Разделяем по типам
    ag_changes  = [(i, change) for i, change in enumerate(changes)
                   if change["entity_type"] == "ad_group_add"]
    kw_changes  = [(i, change) for i, change in enumerate(changes)
                   if change["entity_type"] == "keyword_add"]
    ad_changes  = [(i, change) for i, change in enumerate(changes)
                   if change["entity_type"] == "product_ad_add"]

    results = {}

    # ── Шаг 1: создать группы ────────────────────────────
    # name → adGroupId (заполняется после ответа API)
    ag_name_to_id = {}   # "GroupName" → "adGroupId"
    ag_camp_id    = {}   # "GroupName" → "campaignId"

    ag_payloads = []
    seen_ag_keys = set()  # deduplicate by (name, campaign_id)
    for _, change in ag_changes:
        val = json.loads(change["new_value"])
        camp_id = val.get("campaign_id") or change["entity_id"]
        ag_key = (val["name"], camp_id)
        if ag_key in seen_ag_keys:
            continue
        seen_ag_keys.add(ag_key)
        ag_payloads.append({
            "campaignId": camp_id,
            "adProduct":  "SPONSORED_PRODUCTS",
            "name":       val["name"],
            "state":      "ENABLED",
            "bid":        {"defaultBid": float(val.get("default_bid", 0.5))},
        })
        ag_camp_id[(val["name"], camp_id)] = camp_id

    if ag_payloads:
        if dry_run:
            print(f"  [DRY RUN] create/adGroups: {json.dumps(ag_payloads, ensure_ascii=False)[:300]}")
            for i, (orig_i, _) in enumerate(ag_changes):
                results[orig_i] = "SUCCESS"
                # Имитируем ID для dry-run
                ag_name_to_id[ag_payloads[i]["name"]] = f"DRY_RUN_{i}"
        else:
            resp = amz_post(endpoint, "/adsApi/v1/create/adGroups",
                            headers, {"adGroups": ag_payloads})
            print(f"  [DEBUG] create/adGroups status={resp.status_code}")
            try:
                rj = resp.json()
                print(f"  [DEBUG] adGroups response: {json.dumps(rj, ensure_ascii=False)[:400]}")
                # Извлекаем adGroupId из success ответов
                for item in rj.get("success", []):
                    ag      = item.get("adGroup", {})
                    ag_id   = ag.get("adGroupId")
                    ag_name = ag.get("name")
                    idx     = item.get("index", -1)
                    if ag_id and ag_name:
                        # Use index to get exact campaignId from ag_payloads
                        if 0 <= idx < len(ag_payloads):
                            camp_id_for_ag = ag_payloads[idx]["campaignId"]
                        else:
                            camp_id_for_ag = next(
                                (cid for (n, cid) in ag_camp_id if n == ag_name), None
                            )
                        ag_name_to_id[(ag_name, camp_id_for_ag)] = ag_id
                        ag_name_to_id[ag_name] = ag_id  # fallback
                        print(f"    Группа создана: {ag_name} → {ag_id} (campaign: {camp_id_for_ag})")
            except Exception as e:
                print(f"  [WARN] parse adGroups response: {e}")
            r = parse_multi_response(resp, "adGroups", len(ag_payloads))
            for batch_i, (orig_i, _) in enumerate(ag_changes):
                results[orig_i] = r.get(batch_i, "SUCCESS")

    # ── Шаг 2: создать ключевые слова ────────────────────
    if kw_changes:
        kw_payloads  = []
        kw_orig_idxs = []
        for orig_i, change in kw_changes:
            val = json.loads(change["new_value"])
            ag_name = val.get("ad_group_name", "")
            camp_id = val.get("campaign_id") or change["entity_id"]
            # Prefer (name, camp_id) key to avoid cross-campaign confusion
            ag_id   = (ag_name_to_id.get((ag_name, camp_id))
                       or ag_name_to_id.get(ag_name)
                       or val.get("ad_group_id", ""))
            if not ag_id:
                print(f"  [WARN] keyword_add: не найден adGroupId для группы '{ag_name}'")
                results[orig_i] = "SKIP: adGroupId not resolved"
                continue
            mkt_code = change.get("marketplace", "US").upper()
            MKT_CURRENCY = {"US":"USD","CA":"CAD","UK":"GBP","GB":"GBP",
                            "DE":"EUR","FR":"EUR","IT":"EUR","ES":"EUR","NL":"EUR",
                            "AU":"AUD","JP":"JPY","IN":"INR","MX":"MXN","BR":"BRL"}
            currency = MKT_CURRENCY.get(mkt_code, "USD")
            item = {
                "adGroupId":  ag_id,
                "campaignId": camp_id,
                "adProduct":  "SPONSORED_PRODUCTS",
                "negative":   False,
                "state":      "ENABLED",
                "targetType": "KEYWORD",
                "targetDetails": {
                    "keywordTarget": {
                        "matchType": val["match_type"],
                        "keyword":   val["text"],
                    }
                }
            }
            if val.get("bid"):
                item["bid"] = {"bid": float(val["bid"]), "currencyCode": currency}
            kw_payloads.append(item)
            kw_orig_idxs.append(orig_i)

        if kw_payloads:
            if dry_run:
                print(f"  [DRY RUN] create/targets (kw): {json.dumps(kw_payloads, ensure_ascii=False)[:300]}")
                for i in kw_orig_idxs: results[i] = "SUCCESS"
            else:
                resp = amz_post(endpoint, "/adsApi/v1/create/targets",
                                headers, {"targets": kw_payloads})
                print(f"  [DEBUG] create/targets (kw) status={resp.status_code}: {resp.text[:300]}")
                r = parse_multi_response(resp, "targets", len(kw_payloads))
                for batch_i, orig_i in enumerate(kw_orig_idxs):
                    results[orig_i] = r.get(batch_i, "SUCCESS")

    # ── Шаг 3: создать объявления (product ads) ──────────
    if ad_changes:
        ad_payloads  = []
        ad_orig_idxs = []
        for orig_i, change in ad_changes:
            val = json.loads(change["new_value"])
            ag_name = val.get("ad_group_name", "")
            camp_id = val.get("campaign_id") or change["entity_id"]
            ag_id   = (ag_name_to_id.get((ag_name, camp_id))
                       or ag_name_to_id.get(ag_name)
                       or val.get("ad_group_id", ""))
            if not ag_id:
                print(f"  [WARN] product_ad_add: не найден adGroupId для группы '{ag_name}'")
                results[orig_i] = "SKIP: adGroupId not resolved"
                continue
            ad_payloads.append({
                "adGroupId": ag_id,
                "adProduct": "SPONSORED_PRODUCTS",
                "adType":    "PRODUCT_AD",
                "state":     "ENABLED",
                "creative": {
                    "productCreative": {
                        "productCreativeSettings": {
                            "advertisedProduct": {
                                "productId":     val["asin"],
                                "productIdType": "ASIN",
                            }
                        }
                    }
                },
            })
            ad_orig_idxs.append(orig_i)

        if ad_payloads:
            if dry_run:
                print(f"  [DRY RUN] create/ads: {json.dumps(ad_payloads, ensure_ascii=False)[:300]}")
                for i in ad_orig_idxs: results[i] = "SUCCESS"
            else:
                resp = amz_post(endpoint, "/adsApi/v1/create/ads",
                                headers, {"ads": ad_payloads})
                print(f"  [DEBUG] create/ads status={resp.status_code}: {resp.text[:300]}")
                r = parse_multi_response(resp, "ads", len(ad_payloads))
                for batch_i, orig_i in enumerate(ad_orig_idxs):
                    results[orig_i] = r.get(batch_i, "SUCCESS")

    for idx in range(len(changes)):
        if idx not in results:
            results[idx] = "SUCCESS"
    return results


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

    # SP API v1 returns: {"success": [...], "error": [...], "partialSuccess": [...]}
    # success items: {"index": N, "target"/"campaign"/etc: {...}}
    # error items:   {"index": N, "errors": [{"code": "...", "message": "..."}]}

    for item in data.get("success", []):
        results[item.get("index", 0)] = "SUCCESS"

    for item in data.get("partialSuccess", []):
        results[item.get("index", 0)] = "SUCCESS"

    for item in data.get("error", []):
        idx = item.get("index", 0)
        errs = item.get("errors", [{}])
        msg = "; ".join(f"{e.get('code','')}: {e.get('message','')}" for e in errs)
        results[idx] = msg or "UNKNOWN_ERROR"

    # Fallback: старый формат с полем key (campaigns/targets/etc)
    for item in data.get(key, []):
        idx  = item.get("index", 0)
        if idx in results:
            continue
        code = item.get("code", "")
        if code in ("SUCCESS", "") or not code:
            results[idx] = "SUCCESS"
        else:
            details = item.get("details", [{}])
            msg = details[0].get("message", code) if details else code
            results[idx] = f"{code}: {msg}"

    # Заполняем пропущенные индексы как SUCCESS
    for i in range(count):
        if i not in results:
            results[i] = "SUCCESS"
    return results


# ── Основной цикл ─────────────────────────────────────────
def send_changes(account_type="MERCH", marketplace_filter=None, dry_run=False):
    bq      = bigquery.Client(project=PROJECT_ID)
    sent_at = datetime.now(tz=timezone.utc).isoformat()

    # Сбрасываем застрявшие SENDING → APPROVED (зависшие прошлые запуски)
    reset_stale_sending(bq, account_type)

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

    total_success = 0
    total_failed  = 0

    token = get_token()

    for mkt, mkt_changes in by_profile.items():
        if marketplace_filter and mkt != marketplace_filter:
            continue

        profile_key = f"{account_type}_{mkt}"
        profile = PROFILES.get(profile_key)
        if not profile:
            print(f"  Профиль {profile_key} не найден, пропускаем {len(mkt_changes)} изменений")
            if not dry_run:
                mark_failed(bq, account_type, [c["id"] for c in mkt_changes], "Profile not found")
            total_failed += len(mkt_changes)
            continue

        endpoint   = profile.get("api_endpoint", "https://advertising-api.amazon.com")
        profile_id = profile["id"]
        headers    = amz_headers(token, profile_id)

        print(f"\n  Marketplace: {mkt} ({len(mkt_changes)} изменений)")

        # Помечаем как SENDING перед отправкой — видно что «в работе»
        if not dry_run:
            mark_sending(bq, account_type, [c["id"] for c in mkt_changes])

        grouped = group_changes(mkt_changes)

        # Функции отправки по типу
        send_funcs = [
            ("update_campaigns",  send_update_campaigns),
            ("update_ad_groups",  send_update_ad_groups),
            ("update_targets",    send_update_targets),
            ("create_targets",    send_create_targets),
            ("delete_targets",    send_delete_targets),
            ("create_ad_groups",  send_create_ad_groups),
            ("create_campaigns",  send_create_campaigns),
            ("delete_campaigns",  send_delete_campaigns),
        ]

        mkt_success   = []
        mkt_failed    = []
        mkt_changelog = []
        bq_updates    = []

        for group_key, send_fn in send_funcs:
            batch = grouped[group_key]
            if not batch:
                continue

            print(f"    {group_key}: {len(batch)} шт.")
            results = send_fn(endpoint, headers, batch, dry_run=dry_run)

            batch_success   = []
            batch_failed    = []
            batch_changelog = []

            for idx, change in enumerate(batch):
                result = results.get(idx, "SUCCESS")
                success = result == "SUCCESS"

                batch_changelog.append({
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
                    batch_success.append(change["id"])
                    bq_updates.append(change)
                    print(f"      ✓ {change['entity_type']}/{change.get('field_name','')} → {change['new_value'][:50]}")
                else:
                    batch_failed.append(change["id"])
                    print(f"      ✗ {change['entity_type']}/{change.get('field_name','')} — {result[:100]}")

            # ── Записываем результаты сразу после каждого батча ──────────────
            # Это гарантирует что лог и статусы сохранятся даже если скрипт
            # упадёт или зависнет на следующем батче.
            if not dry_run:
                write_changelog(bq, account_type, batch_changelog)
                if batch_success:
                    mark_done(bq, account_type, batch_success, "SENT")
                if batch_failed:
                    mark_failed(bq, account_type, batch_failed, f"{group_key} failed")

            mkt_success.extend(batch_success)
            mkt_failed.extend(batch_failed)
            mkt_changelog.extend(batch_changelog)

        # Применяем успешные изменения в BigQuery (локальный кэш campaigns_merch)
        if not dry_run and bq_updates:
            update_campaigns_bq(bq, account_type, mkt, bq_updates)

        total_success += len(mkt_success)
        total_failed  += len(mkt_failed)

    print(f"\n✓ Готово: {total_success} успешно, {total_failed} с ошибками")


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