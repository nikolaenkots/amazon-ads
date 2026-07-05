"""
placements_routes.py — страница оптимизации плейсментов.

Показывает список кампаний, при раскрытии — плейсменты
(Top of search / Rest of search / Product pages / Off Amazon) со статистикой
за выбранный период и текущей корректировкой ставки (%).

Данные:
  • статистика  — placement_stats_{merch,kdp}  (отчёт spCampaigns / campaignPlacement)
  • корректировки — campaigns_{merch,kdp}  (entity_type='bidding_adjustment')

Изменение % уходит в очередь (pending_changes, entity_type='bidding_adjustment')
через существующий /control/add.
"""
import os
from flask import Blueprint, request, jsonify, send_from_directory
from google.cloud import bigquery
from bq_client import get_client

placements_bp = Blueprint('placements', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

# placementClassification (из отчёта)  →  код плейсмента (в настройках/для API)
REPORT_TO_CODE = {
    "Top of Search on-Amazon": "TOP_OF_SEARCH",
    "Detail Page on-Amazon":   "PRODUCT_PAGE",
    "Other on-Amazon":         "REST_OF_SEARCH",
    "Off Amazon":              "OFF_AMAZON",
}
LABELS = {
    "TOP_OF_SEARCH":  "Top of search",
    "REST_OF_SEARCH": "Rest of search",
    "PRODUCT_PAGE":   "Product pages",
    "OFF_AMAZON":     "Off Amazon",
}
# порядок вывода + какие редактируемы (у Off Amazon корректировки нет)
ORDER    = ["TOP_OF_SEARCH", "REST_OF_SEARCH", "PRODUCT_PAGE", "OFF_AMAZON"]
EDITABLE = {"TOP_OF_SEARCH", "REST_OF_SEARCH", "PRODUCT_PAGE"}


def _suffix(account):
    return "kdp" if (account or "").upper() == "KDP" else "merch"


def _pct(part, whole):
    return round(part / whole * 100, 2) if whole else None


@placements_bp.route('/automation/placements')
def placements_page():
    return send_from_directory(BASE_DIR, 'placements.html')


@placements_bp.route('/automation/placements/data')
def placements_data():
    account     = (request.args.get('account') or 'MERCH').upper()
    marketplace = (request.args.get('marketplace') or 'US').upper()
    start       = request.args.get('start')
    end         = request.args.get('end')
    if not start or not end:
        return jsonify({"error": "Параметры start и end обязательны"}), 400

    suffix    = _suffix(account)
    stats_tbl = f"{PROJECT_ID}.{DATASET}.placement_stats_{suffix}"
    camp_tbl  = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    client    = get_client()

    params = [
        bigquery.ScalarQueryParameter("mkt",   "STRING", marketplace),
        bigquery.ScalarQueryParameter("start", "DATE",   start),
        bigquery.ScalarQueryParameter("end",   "DATE",   end),
    ]
    cfg = bigquery.QueryJobConfig(query_parameters=params)

    # ── 1. статистика по плейсментам ─────────────────────────
    stats_sql = f"""
        SELECT campaign_id,
               ANY_VALUE(campaign_name)     AS campaign_name,
               ANY_VALUE(profile_id)        AS profile_id,
               placement,
               SUM(impressions)             AS impressions,
               SUM(clicks)                  AS clicks,
               SUM(cost)                    AS cost,
               SUM(purchases_7d)            AS orders,
               SUM(sales_7d)                AS sales
        FROM `{stats_tbl}`
        WHERE marketplace = @mkt AND date BETWEEN @start AND @end
        GROUP BY campaign_id, placement
    """

    # ── 2. текущие корректировки (последний синк) ────────────
    adj_sql = f"""
        SELECT campaign_id,
               placement,
               MAX(placement_percentage)  AS pct,
               ANY_VALUE(campaign_name)   AS campaign_name,
               ANY_VALUE(campaign_state)  AS state,
               ANY_VALUE(bidding_strategy) AS strategy
        FROM `{camp_tbl}`
        WHERE entity_type = 'bidding_adjustment' AND marketplace = @mkt
        GROUP BY campaign_id, placement
    """

    try:
        stats_rows = list(client.query(stats_sql, job_config=cfg).result())
        adj_rows   = list(client.query(adj_sql,   job_config=cfg).result())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # campaign_id → структура
    camps = {}
    profile_id = None

    def _blank(code):
        return {"code": code, "label": LABELS[code], "editable": code in EDITABLE,
                "adjustment_pct": None,
                "impressions": 0, "clicks": 0, "cost": 0.0, "orders": 0, "sales": 0.0}

    def _ensure(cid, name=None):
        if cid not in camps:
            camps[cid] = {"campaign_id": cid, "campaign_name": name,
                          "state": None, "strategy": None,
                          "placements": {c: _blank(c) for c in ORDER}}
        elif name and not camps[cid]["campaign_name"]:
            camps[cid]["campaign_name"] = name
        return camps[cid]

    # статистика
    for r in stats_rows:
        cid  = str(r["campaign_id"])
        code = REPORT_TO_CODE.get(r["placement"])
        if not code:
            continue
        if profile_id is None and r["profile_id"]:
            profile_id = str(r["profile_id"])
        c  = _ensure(cid, r["campaign_name"])
        pl = c["placements"][code]
        pl["impressions"] += int(r["impressions"] or 0)
        pl["clicks"]      += int(r["clicks"] or 0)
        pl["cost"]        += float(r["cost"] or 0)
        pl["orders"]      += int(r["orders"] or 0)
        pl["sales"]       += float(r["sales"] or 0)

    # корректировки
    for r in adj_rows:
        cid  = str(r["campaign_id"])
        code = (r["placement"] or "").upper()
        c    = _ensure(cid, r["campaign_name"])
        if r["state"]:    c["state"]    = r["state"]
        if r["strategy"]: c["strategy"] = r["strategy"]
        if code in c["placements"] and r["pct"] is not None:
            c["placements"][code]["adjustment_pct"] = float(r["pct"])

    # финализируем: считаем производные метрики + totals + сортируем плейсменты
    result = []
    for c in camps.values():
        tot = {"impressions": 0, "clicks": 0, "cost": 0.0, "orders": 0, "sales": 0.0}
        pls = []
        for code in ORDER:
            pl = c["placements"][code]
            pl["ctr"]  = _pct(pl["clicks"], pl["impressions"])
            pl["cpc"]  = round(pl["cost"] / pl["clicks"], 2) if pl["clicks"] else None
            pl["acos"] = _pct(pl["cost"], pl["sales"])
            pl["cost"]  = round(pl["cost"], 2)
            pl["sales"] = round(pl["sales"], 2)
            for k in tot:
                tot[k] += c["placements"][code][k] if k in ("impressions", "clicks", "orders") else 0
            tot["cost"]  += pl["cost"]
            tot["sales"] += pl["sales"]
            pls.append(pl)
        tot["ctr"]  = _pct(tot["clicks"], tot["impressions"])
        tot["cpc"]  = round(tot["cost"] / tot["clicks"], 2) if tot["clicks"] else None
        tot["acos"] = _pct(tot["cost"], tot["sales"])
        tot["cost"]  = round(tot["cost"], 2)
        tot["sales"] = round(tot["sales"], 2)
        result.append({
            "campaign_id":   c["campaign_id"],
            "campaign_name": c["campaign_name"] or c["campaign_id"],
            "state":         c["state"],
            "strategy":      c["strategy"],
            "totals":        tot,
            "placements":    pls,
        })

    # сортировка по расходу
    result.sort(key=lambda x: x["totals"]["cost"], reverse=True)

    return jsonify({
        "account":     account,
        "marketplace": marketplace,
        "profile_id":  profile_id,
        "start":       start,
        "end":         end,
        "campaigns":   result,
        "total":       len(result),
    })
