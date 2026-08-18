"""
pause_asins_routes.py — «Остановка ASIN без продаж».

Находит ASIN, которые тратят бюджет без результата, и позволяет одним
действием поставить в очередь паузу всех их групп объявлений. Раньше это
делалось вручную: отфильтровать на /analytics/products, потом открывать
каждый ASIN и останавливать группы по одной.

Endpoints:
  GET  /automation/pause-asins          — страница
  GET  /automation/pause-asins/data     — ASIN по критериям + число активных групп
  POST /automation/pause-asins/groups   — группы выбранных ASIN (превью и постановка)
  GET  /automation/pause-asins/detail   — кампании и группы одного ASIN (раскрытие строки)
"""

import decimal
import os

from flask import Blueprint, request, jsonify, send_from_directory

from bq_client import get_client

pause_asins_bp = Blueprint('pause_asins', __name__)

PAGE_DIR   = os.path.dirname(os.path.abspath(__file__))
BASE_DIR   = os.path.dirname(PAGE_DIR)
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


def _cvt(v):
    return float(v) if isinstance(v, decimal.Decimal) else v


def _rows(job):
    out = []
    for r in job.result():
        out.append({k: _cvt(v) for k, v in dict(r).items()})
    return out


def _q(s):
    """Экранировать строку для подстановки в SQL."""
    return str(s).replace("'", "''")


@pause_asins_bp.route('/automation/pause-asins')
def pause_asins_page():
    return send_from_directory(PAGE_DIR, 'pause_asins.html')


@pause_asins_bp.route('/automation/pause-asins/data')
def pause_asins_data():
    """ASIN, тратящие бюджет без продаж, с числом активных групп."""
    account_type  = request.args.get('account_type', 'MERCH').upper()
    date_from     = request.args.get('date_from', '')
    date_to       = request.args.get('date_to', '')
    marketplace   = request.args.get('marketplace', '').upper()
    portfolio_ids = request.args.get('portfolio_ids', '')
    ttype         = request.args.get('ttype', '').upper()   # AUTO | MANUAL | '' (все)
    try:
        min_clicks = float(request.args.get('min_clicks', 10))
        min_cost   = float(request.args.get('min_cost', 0))
        max_orders = float(request.args.get('max_orders', 0))
        max_sales  = float(request.args.get('max_sales', 0))
        # сколько ASIN отдавать: по умолчанию 200, но список можно расширить
        limit      = min(5000, max(1, int(request.args.get('limit', 200))))
    except ValueError:
        return jsonify({"error": "Неверные числовые параметры"}), 400

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400

    suffix     = account_type.lower()
    asin_table = f"{PROJECT_ID}.{DATASET}.asin_stats_{suffix}"
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    cat_table  = f"{PROJECT_ID}.{DATASET}.catalog"

    date_conds = []
    if date_from: date_conds.append(f"a.date >= '{_q(date_from)}'")
    if date_to:   date_conds.append(f"a.date <= '{_q(date_to)}'")
    date_where = ('AND ' + ' AND '.join(date_conds)) if date_conds else ''

    camp_conds = ["camp.entity_type = 'campaign'"]
    if marketplace:
        camp_conds.append(f"camp.marketplace = '{_q(marketplace)}'")
    if portfolio_ids:
        ids = [f"'{_q(i.strip())}'" for i in portfolio_ids.split(',') if i.strip()]
        if ids:
            camp_conds.append(f"camp.portfolio_id IN ({','.join(ids)})")
    camp_where = ' AND '.join(camp_conds)

    mkt_cond = f"AND marketplace = '{_q(marketplace)}'" if marketplace else ''
    # фильтр по типу кампании: только авто, только ручные или все
    ttype_cond = (f"AND ct.targeting_type = '{_q(ttype)}'"
                  if ttype in ('AUTO', 'MANUAL') else '')

    sql = f"""
    WITH camp_filter AS (
      SELECT DISTINCT camp.campaign_id, camp.marketplace
      FROM `{camp_table}` camp
      WHERE {camp_where}
    ),
    -- тип кампании (AUTO/MANUAL) по последнему состоянию
    camp_type AS (
      SELECT campaign_id, marketplace, targeting_type FROM (
        SELECT campaign_id, marketplace, targeting_type,
               ROW_NUMBER() OVER (PARTITION BY campaign_id ORDER BY synced_at DESC) rn
        FROM `{camp_table}`
        WHERE entity_type = 'campaign' {mkt_cond}
      ) WHERE rn = 1
    ),
    stats AS (
      SELECT a.advertised_asin AS asin, a.marketplace,
             SUM(a.impressions)   AS impressions,
             SUM(a.clicks)        AS clicks,
             ROUND(SUM(a.cost), 2)      AS cost,
             ROUND(SUM(a.sales_14d), 2) AS sales_14d,
             SUM(a.purchases_14d) AS purchases_14d
      FROM `{asin_table}` a
      JOIN camp_filter cf
        ON cf.campaign_id = a.campaign_id AND cf.marketplace = a.marketplace
      WHERE a.advertised_asin IS NOT NULL AND a.advertised_asin != '' {date_where}
      GROUP BY asin, a.marketplace
    ),
    -- активные группы, где рекламируется ASIN (по последнему состоянию сущностей)
    ads AS (
      SELECT asin, marketplace, ad_group_id, campaign_id FROM (
        SELECT asin, marketplace, ad_group_id, campaign_id,
               ROW_NUMBER() OVER (PARTITION BY ad_id ORDER BY synced_at DESC) rn,
               ad_state
        FROM `{camp_table}`
        WHERE entity_type = 'product_ad' AND asin IS NOT NULL
      ) WHERE rn = 1 AND ad_state = 'ENABLED'
    ),
    -- grps, а не groups: GROUPS — зарезервированное слово BigQuery
    grps AS (
      SELECT ad_group_id, marketplace FROM (
        SELECT ad_group_id, marketplace, ad_group_state,
               ROW_NUMBER() OVER (PARTITION BY ad_group_id ORDER BY synced_at DESC) rn
        FROM `{camp_table}`
        WHERE entity_type = 'ad_group' {mkt_cond}
      ) WHERE rn = 1 AND ad_group_state = 'ENABLED'
    ),
    grp_cnt AS (
      SELECT ads.asin, ads.marketplace,
             COUNT(DISTINCT ads.ad_group_id) AS active_groups,
             COUNT(DISTINCT IF(ct.targeting_type = 'AUTO',   ads.ad_group_id, NULL)) AS auto_groups,
             COUNT(DISTINCT IF(ct.targeting_type = 'MANUAL', ads.ad_group_id, NULL)) AS manual_groups
      FROM ads
      JOIN grps g ON g.ad_group_id = ads.ad_group_id AND g.marketplace = ads.marketplace
      LEFT JOIN camp_type ct
        ON ct.campaign_id = ads.campaign_id AND ct.marketplace = ads.marketplace
      WHERE TRUE {ttype_cond}
      GROUP BY ads.asin, ads.marketplace
    )
    SELECT s.asin, s.marketplace, s.impressions, s.clicks, s.cost,
           s.sales_14d, s.purchases_14d,
           IFNULL(gc.active_groups, 0)  AS active_groups,
           IFNULL(gc.auto_groups, 0)    AS auto_groups,
           IFNULL(gc.manual_groups, 0)  AS manual_groups,
           cat.title, cat.image_url,
           ROUND(SAFE_DIVIDE(s.cost, NULLIF(s.sales_14d, 0)) * 100, 1) AS acos
    FROM stats s
    JOIN grp_cnt gc ON gc.asin = s.asin AND gc.marketplace = s.marketplace
    LEFT JOIN `{cat_table}` cat ON cat.asin = s.asin
    WHERE s.clicks        >= {min_clicks}
      AND s.cost          >= {min_cost}
      AND s.purchases_14d <= {max_orders}
      AND s.sales_14d     <= {max_sales}
      AND IFNULL(gc.active_groups, 0) > 0
    ORDER BY s.cost DESC
    LIMIT {limit}
    """
    try:
        rows = _rows(get_client().query(sql))
        return jsonify({
            "rows":  rows,
            "total": len(rows),
            "limit": limit,
            # список упёрся в лимит — значит подходящих ASIN может быть больше
            "truncated": len(rows) >= limit,
            "summary": {
                "asins":  len(rows),
                "cost":   round(sum(r.get("cost") or 0 for r in rows), 2),
                "clicks": sum(r.get("clicks") or 0 for r in rows),
                "groups": sum(r.get("active_groups") or 0 for r in rows),
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pause_asins_bp.route('/automation/pause-asins/groups', methods=['POST'])
def pause_asins_groups():
    """Активные группы выбранных ASIN — для предпросмотра и постановки в очередь.

    Для каждой группы считается, сколько всего активных ASIN в ней рекламируется:
    если больше одного, остановка группы затронет и чужие ASIN — страница это
    показывает отдельным предупреждением.
    """
    data         = request.get_json() or {}
    account_type = (data.get('account_type') or 'MERCH').upper()
    marketplace  = (data.get('marketplace') or '').upper()
    ttype        = (data.get('ttype') or '').upper()   # AUTO | MANUAL | '' (все)
    asins        = [str(a).strip().upper() for a in (data.get('asins') or []) if str(a).strip()]

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400
    if not asins:
        return jsonify({"error": "Не выбрано ни одного ASIN"}), 400
    if len(asins) > 500:
        return jsonify({"error": "Максимум 500 ASIN за раз"}), 400

    suffix     = account_type.lower()
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    asin_list  = ",".join(f"'{_q(a)}'" for a in asins)
    mkt_cond   = f"AND marketplace = '{_q(marketplace)}'" if marketplace else ''
    ttype_cond = (f"AND c.targeting_type = '{_q(ttype)}'"
                  if ttype in ('AUTO', 'MANUAL') else '')

    sql = f"""
    WITH ads AS (
      SELECT asin, marketplace, ad_group_id, campaign_id FROM (
        SELECT asin, marketplace, ad_group_id, campaign_id, ad_state,
               ROW_NUMBER() OVER (PARTITION BY ad_id ORDER BY synced_at DESC) rn
        FROM `{camp_table}`
        WHERE entity_type = 'product_ad' AND asin IS NOT NULL {mkt_cond}
      ) WHERE rn = 1 AND ad_state = 'ENABLED'
    ),
    -- grps, а не groups: GROUPS — зарезервированное слово BigQuery
    grps AS (
      SELECT ad_group_id, marketplace, ad_group_name, campaign_id, profile_id FROM (
        SELECT ad_group_id, marketplace, ad_group_name, campaign_id, profile_id,
               ad_group_state,
               ROW_NUMBER() OVER (PARTITION BY ad_group_id ORDER BY synced_at DESC) rn
        FROM `{camp_table}`
        WHERE entity_type = 'ad_group' {mkt_cond}
      ) WHERE rn = 1 AND ad_group_state = 'ENABLED'
    ),
    camps AS (
      SELECT campaign_id, marketplace, campaign_name, targeting_type FROM (
        SELECT campaign_id, marketplace, campaign_name, targeting_type,
               ROW_NUMBER() OVER (PARTITION BY campaign_id ORDER BY synced_at DESC) rn
        FROM `{camp_table}`
        WHERE entity_type = 'campaign' {mkt_cond}
      ) WHERE rn = 1
    ),
    -- сколько всего активных ASIN в каждой группе
    grp_total AS (
      SELECT ad_group_id, marketplace, COUNT(DISTINCT asin) AS asins_total
      FROM ads GROUP BY ad_group_id, marketplace
    )
    SELECT g.ad_group_id, g.ad_group_name, g.campaign_id, g.marketplace,
           g.profile_id, c.campaign_name, c.targeting_type,
           gt.asins_total,
           COUNT(DISTINCT a.asin) AS asins_selected
    FROM ads a
    JOIN grps g      ON g.ad_group_id = a.ad_group_id AND g.marketplace = a.marketplace
    JOIN grp_total gt ON gt.ad_group_id = g.ad_group_id AND gt.marketplace = g.marketplace
    LEFT JOIN camps c ON c.campaign_id = g.campaign_id AND c.marketplace = g.marketplace
    WHERE a.asin IN ({asin_list}) {ttype_cond}
    GROUP BY g.ad_group_id, g.ad_group_name, g.campaign_id, g.marketplace,
             g.profile_id, c.campaign_name, c.targeting_type, gt.asins_total
    ORDER BY c.campaign_name, g.ad_group_name
    """
    try:
        rows = _rows(get_client().query(sql))
        for r in rows:
            # в группе есть ASIN, которых пользователь не выбирал
            r["has_other_asins"] = (r.get("asins_total") or 0) > (r.get("asins_selected") or 0)
        return jsonify({
            "groups":     rows,
            "total":      len(rows),
            "with_other": sum(1 for r in rows if r["has_other_asins"]),
            "auto":       sum(1 for r in rows if (r.get("targeting_type") or '') == 'AUTO'),
            "manual":     sum(1 for r in rows if (r.get("targeting_type") or '') == 'MANUAL'),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pause_asins_bp.route('/automation/pause-asins/detail')
def pause_asins_detail():
    """Кампании и группы одного ASIN — раскрытие строки таблицы.

    Показывает то же, что страница «Аналитика товаров»: по каким кампаниям и
    группам ASIN тратил бюджет за выбранный период, в каком они состоянии и
    какого типа. Нужно, чтобы перед остановкой видеть, что именно встанет.
    """
    account_type = request.args.get('account_type', 'MERCH').upper()
    asin         = request.args.get('asin', '').strip().upper()
    marketplace  = request.args.get('marketplace', '').upper()
    date_from    = request.args.get('date_from', '')
    date_to      = request.args.get('date_to', '')
    ttype        = request.args.get('ttype', '').upper()

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400
    if not asin:
        return jsonify({"error": "Не указан ASIN"}), 400

    suffix     = account_type.lower()
    asin_table = f"{PROJECT_ID}.{DATASET}.asin_stats_{suffix}"
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"

    conds = [f"a.advertised_asin = '{_q(asin)}'"]
    if marketplace: conds.append(f"a.marketplace = '{_q(marketplace)}'")
    if date_from:   conds.append(f"a.date >= '{_q(date_from)}'")
    if date_to:     conds.append(f"a.date <= '{_q(date_to)}'")
    where = ' AND '.join(conds)

    mkt_cond   = f"AND marketplace = '{_q(marketplace)}'" if marketplace else ''
    ttype_cond = (f"AND c.targeting_type = '{_q(ttype)}'"
                  if ttype in ('AUTO', 'MANUAL') else '')

    sql = f"""
    WITH camps AS (
      SELECT campaign_id, marketplace, campaign_name, campaign_state, targeting_type FROM (
        SELECT campaign_id, marketplace, campaign_name, campaign_state, targeting_type,
               ROW_NUMBER() OVER (PARTITION BY campaign_id ORDER BY synced_at DESC) rn
        FROM `{camp_table}`
        WHERE entity_type = 'campaign' {mkt_cond}
      ) WHERE rn = 1
    ),
    -- grps, а не groups: GROUPS — зарезервированное слово BigQuery
    grps AS (
      SELECT ad_group_id, marketplace, ad_group_name, ad_group_state FROM (
        SELECT ad_group_id, marketplace, ad_group_name, ad_group_state,
               ROW_NUMBER() OVER (PARTITION BY ad_group_id ORDER BY synced_at DESC) rn
        FROM `{camp_table}`
        WHERE entity_type = 'ad_group' {mkt_cond}
      ) WHERE rn = 1
    ),
    st AS (
      SELECT a.campaign_id, a.ad_group_id, a.marketplace,
             SUM(a.impressions)         AS impressions,
             SUM(a.clicks)              AS clicks,
             ROUND(SUM(a.cost), 2)      AS cost,
             ROUND(SUM(a.sales_14d), 2) AS sales_14d,
             SUM(a.purchases_14d)       AS purchases_14d
      FROM `{asin_table}` a
      WHERE {where}
      GROUP BY a.campaign_id, a.ad_group_id, a.marketplace
    )
    SELECT st.campaign_id, st.ad_group_id, st.marketplace,
           c.campaign_name, c.campaign_state, c.targeting_type,
           g.ad_group_name, g.ad_group_state,
           st.impressions, st.clicks, st.cost, st.sales_14d, st.purchases_14d
    FROM st
    LEFT JOIN camps c ON c.campaign_id = st.campaign_id AND c.marketplace = st.marketplace
    LEFT JOIN grps  g ON g.ad_group_id = st.ad_group_id AND g.marketplace = st.marketplace
    WHERE TRUE {ttype_cond}
    ORDER BY st.cost DESC
    LIMIT 500
    """
    try:
        rows = _rows(get_client().query(sql))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # свернуть плоский список в кампании с вложенными группами
    camps, order = {}, []
    for r in rows:
        cid = r.get('campaign_id')
        c = camps.get(cid)
        if c is None:
            c = camps[cid] = {
                "campaign_id":    cid,
                "campaign_name":  r.get('campaign_name'),
                "campaign_state": r.get('campaign_state'),
                "targeting_type": r.get('targeting_type'),
                "marketplace":    r.get('marketplace'),
                "impressions": 0, "clicks": 0, "cost": 0.0,
                "sales_14d": 0.0, "purchases_14d": 0,
                "groups": [],
            }
            order.append(cid)
        c["groups"].append({
            "ad_group_id":    r.get('ad_group_id'),
            "ad_group_name":  r.get('ad_group_name'),
            "ad_group_state": r.get('ad_group_state'),
            "impressions":    r.get('impressions') or 0,
            "clicks":         r.get('clicks') or 0,
            "cost":           r.get('cost') or 0,
            "sales_14d":      r.get('sales_14d') or 0,
            "purchases_14d":  r.get('purchases_14d') or 0,
        })
        for k in ("impressions", "clicks", "cost", "sales_14d", "purchases_14d"):
            c[k] += r.get(k) or 0

    out = []
    for cid in order:
        c = camps[cid]
        c["cost"]      = round(c["cost"], 2)
        c["sales_14d"] = round(c["sales_14d"], 2)
        c["groups"].sort(key=lambda g: -(g["cost"] or 0))
        out.append(c)
    out.sort(key=lambda c: -(c["cost"] or 0))

    return jsonify({
        "campaigns": out,
        "total":     len(out),
        "groups":    sum(len(c["groups"]) for c in out),
    })
