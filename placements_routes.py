"""
placements_routes.py — страница оптимизации плейсментов.

Показывает список кампаний, при раскрытии — плейсменты
(Top of search / Rest of search / Product pages / Off Amazon) со статистикой
за выбранный период и текущей корректировкой ставки (%).

Данные:
  • статистика  — placement_stats_{merch,kdp}  (отчёт spCampaigns / campaignPlacement)
  • корректировки + мета кампаний — campaigns_{merch,kdp}

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

    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mkt",   "STRING", marketplace),
        bigquery.ScalarQueryParameter("start", "DATE",   start),
        bigquery.ScalarQueryParameter("end",   "DATE",   end),
    ])
    cfg_mkt = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mkt", "STRING", marketplace),
    ])

    # ── 1. статистика по плейсментам ─────────────────────────
    stats_sql = f"""
        SELECT campaign_id,
               ANY_VALUE(campaign_name) AS campaign_name,
               ANY_VALUE(profile_id)    AS profile_id,
               placement,
               SUM(impressions)  AS impressions,
               SUM(clicks)       AS clicks,
               SUM(cost)         AS cost,
               SUM(purchases_7d) AS orders,
               SUM(sales_7d)     AS sales
        FROM `{stats_tbl}`
        WHERE marketplace = @mkt AND date BETWEEN @start AND @end
        GROUP BY campaign_id, placement
    """

    # ── 2. текущие корректировки плейсментов ─────────────────
    adj_sql = f"""
        SELECT campaign_id, placement, MAX(placement_percentage) AS pct
        FROM `{camp_tbl}`
        WHERE entity_type = 'bidding_adjustment' AND marketplace = @mkt
        GROUP BY campaign_id, placement
    """

    # ── 3. мета кампаний (статус, тип таргетинга, портфолио) ──
    meta_sql = f"""
        SELECT campaign_id,
               ANY_VALUE(campaign_name)   AS campaign_name,
               ANY_VALUE(campaign_state)  AS state,
               ANY_VALUE(targeting_type)  AS targeting_type,
               ANY_VALUE(bidding_strategy) AS strategy,
               ANY_VALUE(portfolio_id)    AS portfolio_id,
               ANY_VALUE(portfolio_name)  AS portfolio_name
        FROM `{camp_tbl}`
        WHERE entity_type = 'campaign' AND marketplace = @mkt
        GROUP BY campaign_id
    """

    try:
        stats_rows = list(client.query(stats_sql, job_config=cfg).result())
        adj_rows   = list(client.query(adj_sql,   job_config=cfg_mkt).result())
        meta_rows  = list(client.query(meta_sql,  job_config=cfg_mkt).result())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    meta = {}
    for r in meta_rows:
        meta[str(r["campaign_id"])] = {
            "campaign_name":  r["campaign_name"],
            "state":          r["state"],
            "targeting_type": (r["targeting_type"] or "").upper() or None,
            "strategy":       r["strategy"],
            "portfolio_id":   r["portfolio_id"],
            "portfolio_name": r["portfolio_name"],
        }

    camps = {}
    profile_id = None

    def _blank(code):
        return {"code": code, "label": LABELS[code], "editable": code in EDITABLE,
                "adjustment_pct": None,
                "impressions": 0, "clicks": 0, "cost": 0.0, "orders": 0, "sales": 0.0}

    def _ensure(cid, name=None):
        if cid not in camps:
            m = meta.get(cid, {})
            camps[cid] = {"campaign_id": cid,
                          "campaign_name": name or m.get("campaign_name"),
                          "state":          m.get("state"),
                          "strategy":       m.get("strategy"),
                          "targeting_type": m.get("targeting_type"),
                          "portfolio_id":   m.get("portfolio_id"),
                          "portfolio_name": m.get("portfolio_name"),
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
        if cid in camps and code in camps[cid]["placements"] and r["pct"] is not None:
            camps[cid]["placements"][code]["adjustment_pct"] = float(r["pct"])

    # финализация
    portfolios = {}
    result = []
    for c in camps.values():
        tot = {"impressions": 0, "clicks": 0, "cost": 0.0, "orders": 0, "sales": 0.0}
        pls = []
        for code in ORDER:
            pl = c["placements"][code]
            pl["ctr"]  = _pct(pl["clicks"], pl["impressions"])
            pl["cpc"]  = round(pl["cost"] / pl["clicks"], 2) if pl["clicks"] else None
            pl["acos"] = _pct(pl["cost"], pl["sales"])
            tot["impressions"] += pl["impressions"]
            tot["clicks"]      += pl["clicks"]
            tot["orders"]      += pl["orders"]
            tot["cost"]        += pl["cost"]
            tot["sales"]       += pl["sales"]
            pl["cost"]  = round(pl["cost"], 2)
            pl["sales"] = round(pl["sales"], 2)
            pls.append(pl)
        tot["ctr"]  = _pct(tot["clicks"], tot["impressions"])
        tot["cpc"]  = round(tot["cost"] / tot["clicks"], 2) if tot["clicks"] else None
        tot["acos"] = _pct(tot["cost"], tot["sales"])
        tot["cost"]  = round(tot["cost"], 2)
        tot["sales"] = round(tot["sales"], 2)
        if c["portfolio_id"]:
            portfolios[str(c["portfolio_id"])] = c["portfolio_name"] or str(c["portfolio_id"])
        result.append({
            "campaign_id":    c["campaign_id"],
            "campaign_name":  c["campaign_name"] or c["campaign_id"],
            "state":          c["state"],
            "strategy":       c["strategy"],
            "targeting_type": c["targeting_type"],
            "portfolio_id":   c["portfolio_id"],
            "portfolio_name": c["portfolio_name"],
            "totals":         tot,
            "placements":     pls,
        })

    result.sort(key=lambda x: x["totals"]["cost"], reverse=True)

    return jsonify({
        "account":     account,
        "marketplace": marketplace,
        "profile_id":  profile_id,
        "start":       start,
        "end":         end,
        "portfolios":  [{"id": k, "name": v} for k, v in sorted(portfolios.items(), key=lambda x: x[1])],
        "campaigns":   result,
        "total":       len(result),
    })
