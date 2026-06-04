import json
import os
import time
import decimal
import threading
from collections import Counter
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_from_directory
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig
import requests as req_lib

campaigns_bp = Blueprint('campaigns', __name__)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID    = "amazon-ads-api-494412"
DATASET       = "amazon_ads"
CHUNK_SIZE    = 1000
AD_PRODUCT    = "SPONSORED_PRODUCTS"

AMZ_SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'amazon_secrets.json')
with open(AMZ_SECRETS_PATH) as _f:
    _AMZ = json.load(_f)

CAMPAIGNS_TABLE = {
    "MERCH": f"{PROJECT_ID}.{DATASET}.campaigns_merch",
    "KDP":   f"{PROJECT_ID}.{DATASET}.campaigns_kdp",
}

COLS = {
    "campaign":           ["campaign_id", "campaign_name", "targeting_type", "bidding_strategy", "daily_budget", "start_date", "campaign_state", "portfolio_id", "portfolio_name"],
    "bidding_adjustment": ["campaign_id", "campaign_name", "placement", "placement_percentage", "bidding_strategy", "campaign_state"],
    "ad_group":           ["ad_group_id", "ad_group_name", "campaign_id", "ad_group_default_bid", "ad_group_state"],
    "keyword":            ["keyword_id", "keyword_text", "match_type", "keyword_bid", "keyword_state", "campaign_id", "ad_group_id"],
    "negative_keyword":   ["keyword_id", "keyword_text", "match_type", "keyword_state", "campaign_id", "ad_group_id"],
    "product_targeting":  ["target_id", "targeting_expression", "target_bid", "target_state", "campaign_id", "ad_group_id"],
    "product_ad":         ["ad_id", "asin", "sku", "ad_state", "campaign_id", "ad_group_id"],
}

def _get_progress_store():
    import app
    return app.progress_store

def emit(job_id, event, data):
    ps = _get_progress_store()
    if job_id not in ps:
        ps[job_id] = []
    ps[job_id].append({"event": event, "data": data})

def _get_profile(account_type, marketplace):
    for p in _AMZ.get("profiles", []):
        if p["type"] == account_type and p["marketplace"] == marketplace:
            return p
    for p in _AMZ.get("profiles", []):
        if p["type"] == account_type:
            return p
    return None

def _amz_token():
    r = req_lib.post(
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

def _paginate(token, endpoint, client_id, profile_id, path, body_base, result_key, emit_fn, job_id):
    results    = []
    next_token = None
    while True:
        body = {**body_base, "maxResults": 1000}
        if next_token:
            body["nextToken"] = next_token
        headers = {
            "Authorization":                   f"Bearer {token}",
            "Amazon-Advertising-API-ClientId":  client_id,
            "Amazon-Advertising-API-Scope":     str(profile_id),
            "Content-Type":                     "application/json",
        }
        resp = req_lib.post(f"{endpoint}{path}", headers=headers, json=body)
        if resp.status_code == 429:
            time.sleep(5)
            continue
        resp.raise_for_status()
        data  = resp.json()
        batch = data.get(result_key, [])
        results.extend(batch)
        next_token = data.get("nextToken")
        if not next_token:
            break
    return results

def _dt_to_date(dt_str, marketplace=None):
    """
    Конвертирует ISO datetime → дату в локальном времени маркетплейса.
    Amazon Console показывает даты в local time, API хранит в UTC.
    Например: "2026-07-01T04:59:59Z" для US → 2026-06-30 (EST = UTC-5).
    """
    if not dt_str:
        return None
    MKT_OFFSET = {
        "US":-5,"CA":-5,"MX":-6,"UK":0,"GB":0,
        "DE":1,"FR":1,"IT":1,"ES":1,"NL":1,"BE":1,"PL":1,"SE":1,
        "TR":3,"AU":10,"JP":9,"IN":5,"SG":8,"AE":4,"SA":3,"BR":-3,
    }
    offset_h = MKT_OFFSET.get((marketplace or "US").upper(), 0)
    try:
        from datetime import datetime, timedelta
        s = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        local_dt = dt + timedelta(hours=offset_h)
        return local_dt.strftime("%Y-%m-%d")
    except Exception:
        return dt_str[:10]

def _fetch_portfolios(token, endpoint, client_id, profile_id):
    """Получает все портфолио профиля → dict {portfolio_id: portfolio_name}."""
    headers = {
        "Authorization":                   f"Bearer {token}",
        "Amazon-Advertising-API-ClientId":  client_id,
        "Amazon-Advertising-API-Scope":     str(profile_id),
        "Content-Type":                     "application/json",
    }
    result = {}
    next_token = None
    while True:
        body = {"maxResults": 1000}
        if next_token:
            body["nextToken"] = next_token
        resp = req_lib.post(
            f"{endpoint}/adsApi/v1/query/portfolios",
            headers=headers, json=body,
        )
        if resp.status_code == 429:
            time.sleep(5)
            continue
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        data = resp.json()
        for p in data.get("portfolios", []):
            pid  = p.get("portfolioId")
            name = p.get("name")
            if pid and name:
                result[str(pid)] = name
        next_token = data.get("nextToken")
        if not next_token:
            break
    return result

def _build_rows(campaigns, ad_groups, targets, ads, profile_id, marketplace, synced_at, portfolio_map=None):
    rows = []

    for c in campaigns:
        budgets  = c.get("budgets", [{}])
        budget   = budgets[0] if budgets else {}
        bv       = budget.get("budgetValue", {}).get("monetaryBudgetValue", {}).get("monetaryBudget", {})
        bid_cfg  = c.get("optimizations", {}).get("bidSettings", {})
        auto_cfg = c.get("autoCreationSettings", {})
        pid      = c.get("portfolioId")

        rows.append({
            "entity_type": "campaign",
            "profile_id": str(profile_id), "marketplace": marketplace,
            "campaign_id": c.get("campaignId"), "campaign_name": c.get("name"),
            "targeting_type": "AUTO" if auto_cfg.get("autoCreateTargets") else "MANUAL",
            "bidding_strategy": bid_cfg.get("bidStrategy"),
            "daily_budget": bv.get("value"),
            "start_date": _dt_to_date(c.get("startDateTime"), marketplace),
            "end_date":   _dt_to_date(c.get("endDateTime"), marketplace),
            "campaign_state": c.get("state"),
            "portfolio_id": pid,
            "portfolio_name": (portfolio_map or {}).get(str(pid)) if pid else None,
            "placement": None, "placement_percentage": None,
            "ad_group_id": None, "ad_group_name": None, "ad_group_default_bid": None,
            "ad_group_state": None, "keyword_id": None, "keyword_text": None,
            "match_type": None, "keyword_bid": None, "keyword_state": None,
            "target_id": None, "targeting_expression": None, "target_bid": None,
            "target_state": None, "ad_id": None, "sku": None, "asin": None,
            "ad_state": None, "synced_at": synced_at,
        })

        for adj in (bid_cfg.get("bidAdjustments", {}).get("placementBidAdjustments", [])):
            rows.append({
                "entity_type": "bidding_adjustment",
                "profile_id": str(profile_id), "marketplace": marketplace,
                "campaign_id": c.get("campaignId"), "campaign_name": c.get("name"),
                "targeting_type": None,
                "bidding_strategy": bid_cfg.get("bidStrategy"),
                "daily_budget": None, "start_date": None, "end_date": None,
                "campaign_state": c.get("state"),
                "portfolio_id": pid,
                "portfolio_name": (portfolio_map or {}).get(str(pid)) if pid else None,
                "placement": adj.get("placement"),
                "placement_percentage": adj.get("percentage"),
                "ad_group_id": None, "ad_group_name": None, "ad_group_default_bid": None,
                "ad_group_state": None, "keyword_id": None, "keyword_text": None,
                "match_type": None, "keyword_bid": None, "keyword_state": None,
                "target_id": None, "targeting_expression": None, "target_bid": None,
                "target_state": None, "ad_id": None, "sku": None, "asin": None,
                "ad_state": None, "synced_at": synced_at,
            })

    for g in ad_groups:
        bid = g.get("bid", {})
        rows.append({
            "entity_type": "ad_group",
            "profile_id": str(profile_id), "marketplace": marketplace,
            "campaign_id": g.get("campaignId"), "campaign_name": None,
            "targeting_type": None, "bidding_strategy": None,
            "daily_budget": None, "start_date": None, "end_date": None,
            "campaign_state": None, "portfolio_id": None, "portfolio_name": None,
            "placement": None, "placement_percentage": None,
            "ad_group_id": g.get("adGroupId"), "ad_group_name": g.get("name"),
            "ad_group_default_bid": bid.get("defaultBid"),
            "ad_group_state": g.get("state"),
            "keyword_id": None, "keyword_text": None, "match_type": None,
            "keyword_bid": None, "keyword_state": None,
            "target_id": None, "targeting_expression": None,
            "target_bid": None, "target_state": None,
            "ad_id": None, "sku": None, "asin": None,
            "ad_state": None, "synced_at": synced_at,
        })

    for t in targets:
        target_type = t.get("targetType")
        is_negative = t.get("negative", False)
        details     = t.get("targetDetails", {})
        bid_val     = t.get("bid", {}).get("bid")
        kw          = details.get("keywordTarget", {})
        pt          = (details.get("productTarget") or details.get("productCategoryTarget")
                       or details.get("themeTarget") or {})

        if target_type == "KEYWORD" and is_negative:
            entity = "negative_keyword"
        elif target_type == "KEYWORD":
            entity = "keyword"
        elif is_negative:
            entity = "negative_product_targeting"
        else:
            entity = "product_targeting"

        if is_negative:
            # Для негативных product таргетов ASIN хранится в product.productId
            # структура: {"productTarget": {"matchType": "PRODUCT_EXACT", "product": {"productId": "B09X..."}, "productIdType": "ASIN"}}
            asin_from_product = pt.get("product", {}).get("productId")
            expr = (asin_from_product or pt.get("productId") or
                    pt.get("categoryId") or pt.get("matchType") or
                    (str(pt) if pt else None))
        else:
            expr = (pt.get("matchType") or pt.get("productId") or
                    pt.get("product", {}).get("productId") or
                    pt.get("categoryId") or (str(pt) if pt else None))

        rows.append({
            "entity_type": entity,
            "profile_id": str(profile_id), "marketplace": marketplace,
            "campaign_id": t.get("campaignId"), "campaign_name": None,
            "targeting_type": target_type, "bidding_strategy": None,
            "daily_budget": None, "start_date": None, "end_date": None,
            "campaign_state": None, "portfolio_id": None, "portfolio_name": None,
            "placement": None, "placement_percentage": None,
            "ad_group_id": t.get("adGroupId"), "ad_group_name": None,
            "ad_group_default_bid": None, "ad_group_state": None,
            "keyword_id":    t.get("targetId") if entity in ("keyword", "negative_keyword") else None,
            "keyword_text":  kw.get("keyword"),
            "match_type":    kw.get("matchType"),
            "keyword_bid":   bid_val if entity in ("keyword", "negative_keyword") else None,
            "keyword_state": t.get("state") if entity in ("keyword", "negative_keyword") else None,
            "target_id":     t.get("targetId") if entity in ("product_targeting", "negative_product_targeting") else None,
            "targeting_expression": expr,
            "target_bid":    bid_val if entity == "product_targeting" else None,
            "target_state":  t.get("state") if entity in ("product_targeting", "negative_product_targeting") else None,
            "ad_id": None, "sku": None, "asin": None,
            "ad_state": None, "synced_at": synced_at,
        })

    for a in ads:
        adv = (a.get("advertisedProducts") or [{}])[0]
        rows.append({
            "entity_type": "product_ad",
            "profile_id": str(profile_id), "marketplace": marketplace,
            "campaign_id": a.get("campaignId"), "campaign_name": None,
            "targeting_type": None, "bidding_strategy": None,
            "daily_budget": None, "start_date": None, "end_date": None,
            "campaign_state": None, "portfolio_id": None, "portfolio_name": None,
            "placement": None, "placement_percentage": None,
            "ad_group_id": a.get("adGroupId"), "ad_group_name": None,
            "ad_group_default_bid": None, "ad_group_state": None,
            "keyword_id": None, "keyword_text": None, "match_type": None,
            "keyword_bid": None, "keyword_state": None,
            "target_id": None, "targeting_expression": None,
            "target_bid": None, "target_state": None,
            "ad_id":  a.get("adId"),
            "sku":    adv.get("sku"),
            "asin":   adv.get("resolvedProductId") or adv.get("productId"),
            "ad_state": a.get("state"),
            "synced_at": synced_at,
        })

    return rows


def _run_campaigns_sync(account_type, marketplace, job_id):
    try:
        profile    = _get_profile(account_type, marketplace)
        if not profile:
            raise Exception(f"Профиль не найден: {account_type} / {marketplace}")
        profile_id = profile["id"]
        endpoint   = profile.get("api_endpoint", "https://advertising-api.amazon.com")
        table_ref  = CAMPAIGNS_TABLE[account_type]
        synced_at  = datetime.now(tz=timezone.utc).isoformat()

        state_filter = {"include": ["ENABLED", "PAUSED"]}
        body_base    = {"adProductFilter": {"include": [AD_PRODUCT]}, "stateFilter": state_filter}

        emit(job_id, "step", {"key": "auth", "step": 1, "pct": 5, "msg": "Авторизация в Amazon API..."})
        token = _amz_token()
        emit(job_id, "count", {"key": "campaigns", "pct": 10, "msg": "Запрашиваем кампании...", "count": 0})

        emit(job_id, "step", {"key": "campaigns", "step": 2, "pct": 12, "msg": "Загружаем кампании..."})
        campaigns = _paginate(token, endpoint, _AMZ["client_id"], profile_id,
                              "/adsApi/v1/query/campaigns", body_base, "campaigns", emit, job_id)
        emit(job_id, "count", {"key": "campaigns", "pct": 25, "msg": f"Кампании получены: {len(campaigns)}", "count": len(campaigns)})

        emit(job_id, "step", {"key": "ad_groups", "step": 3, "pct": 28, "msg": "Загружаем группы объявлений..."})
        ad_groups = _paginate(token, endpoint, _AMZ["client_id"], profile_id,
                              "/adsApi/v1/query/adGroups", body_base, "adGroups", emit, job_id)
        emit(job_id, "count", {"key": "ad_groups", "pct": 45, "msg": f"Групп получено: {len(ad_groups)}", "count": len(ad_groups)})

        emit(job_id, "step", {"key": "targets", "step": 4, "pct": 48, "msg": "Загружаем таргеты..."})
        targets = _paginate(token, endpoint, _AMZ["client_id"], profile_id,
                            "/adsApi/v1/query/targets", body_base, "targets", emit, job_id)
        emit(job_id, "count", {"key": "targets", "pct": 65, "msg": f"Таргетов получено: {len(targets)}", "count": len(targets)})

        emit(job_id, "step", {"key": "ads", "step": 5, "pct": 68, "msg": "Загружаем product ads..."})
        ads = _paginate(token, endpoint, _AMZ["client_id"], profile_id,
                        "/adsApi/v1/query/ads", body_base, "ads", emit, job_id)
        emit(job_id, "count", {"key": "ads", "pct": 75, "msg": f"Ads получено: {len(ads)}", "count": len(ads)})

        # Portfolios
        emit(job_id, "progress", {"msg": "Загружаем портфолио...", "pct": 76})
        try:
            portfolio_map = _fetch_portfolios(token, endpoint, _AMZ["client_id"], profile_id)
            emit(job_id, "progress", {"msg": f"Портфолио получено: {len(portfolio_map)}", "pct": 78})
        except Exception as pe:
            portfolio_map = {}
            emit(job_id, "progress", {"msg": f"Портфолио недоступны: {pe}", "pct": 78})

        emit(job_id, "step", {"key": "bq", "step": 6, "pct": 78, "msg": "Формируем строки для BigQuery..."})
        all_rows = _build_rows(campaigns, ad_groups, targets, ads,
                               profile_id, marketplace, synced_at, portfolio_map)

        counts = dict(Counter(r["entity_type"] for r in all_rows))

        # ── ИСПРАВЛЕНО: DELETE по маркетплейсу вместо TRUNCATE ──
        emit(job_id, "step", {"key": "bq", "step": 6, "pct": 80, "msg": f"Очищаем {marketplace} в таблице..."})
        client = bigquery.Client(project=PROJECT_ID)
        client.query(f"DELETE FROM `{table_ref}` WHERE marketplace = '{marketplace}'").result()

        total    = len(all_rows)
        uploaded = 0
        for i in range(0, total, CHUNK_SIZE):
            chunk = all_rows[i:i + CHUNK_SIZE]
            job   = client.load_table_from_json(
                chunk, table_ref,
                job_config=LoadJobConfig(write_disposition="WRITE_APPEND")
            )
            job.result()
            if job.errors:
                raise RuntimeError(f"BQ ошибки: {job.errors}")
            uploaded += len(chunk)
            pct = 80 + int(uploaded / total * 18)
            emit(job_id, "progress", {"uploaded": uploaded, "total": total, "pct": pct})

        emit(job_id, "count", {"key": "bq", "pct": 99, "msg": f"Загружено {total} строк", "count": total})
        emit(job_id, "done",  {"total": total, "counts": counts, "synced_at": synced_at})

    except Exception as e:
        emit(job_id, "error", {"msg": str(e)})


@campaigns_bp.route('/campaigns')
def campaigns_page():
    return send_from_directory(BASE_DIR, 'campaigns.html')

@campaigns_bp.route('/campaigns/sync', methods=['POST'])
def campaigns_sync():
    data         = request.get_json() or {}
    account_type = data.get('account_type', 'MERCH').upper()
    marketplace  = data.get('marketplace', 'US').upper()
    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400
    job_id = datetime.now().strftime('%Y%m%d%H%M%S%f')
    ps = _get_progress_store()
    ps[job_id] = []
    threading.Thread(target=_run_campaigns_sync, args=(account_type, marketplace, job_id), daemon=True).start()
    return jsonify({"job_id": job_id})

@campaigns_bp.route('/campaigns/progress/<job_id>')
def campaigns_progress(job_id):
    ps = _get_progress_store()
    if job_id not in ps:
        return jsonify([])
    msgs = list(ps[job_id])
    ps[job_id] = []
    return jsonify(msgs)

@campaigns_bp.route('/campaigns/preview')
def campaigns_preview():
    account_type = request.args.get('account_type', 'MERCH').upper()
    marketplace  = request.args.get('marketplace', 'US').upper()
    entity       = request.args.get('entity', 'campaign')
    table_ref    = CAMPAIGNS_TABLE.get(account_type)
    if not table_ref:
        return jsonify({"error": "Неверный account_type"})
    cols = COLS.get(entity, ["campaign_id", "campaign_name"])
    try:
        client   = bigquery.Client(project=PROJECT_ID)
        cols_sql = ", ".join(cols)
        total    = list(client.query(
            f"SELECT COUNT(*) as cnt FROM `{table_ref}` WHERE entity_type = '{entity}' AND marketplace = '{marketplace}'"
        ).result())[0].cnt
        rows = [dict(row) for row in client.query(
            f"SELECT {cols_sql} FROM `{table_ref}` WHERE entity_type = '{entity}' AND marketplace = '{marketplace}' LIMIT 50"
        ).result()]
        for row in rows:
            for k, v in row.items():
                if isinstance(v, decimal.Decimal): row[k] = float(v)
                elif hasattr(v, 'isoformat'): row[k] = v.isoformat()
        return jsonify({"rows": rows, "columns": cols, "total": total})
    except Exception as e:
        return jsonify({"error": str(e)})