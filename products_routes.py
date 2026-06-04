import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory
from google.cloud import bigquery

products_bp = Blueprint('products', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


# ── HTML страница ─────────────────────────────────────────
@products_bp.route('/analytics/products')
def analytics_products_page():
    return send_from_directory(BASE_DIR, 'products_analytics.html')


# ── Список ASIN со статистикой ────────────────────────────
@products_bp.route('/analytics/products/data')
def analytics_products_data():
    account_type  = request.args.get('account_type', 'MERCH').upper()
    date_from     = request.args.get('date_from', '')
    date_to       = request.args.get('date_to', '')
    marketplace   = request.args.get('marketplace', '')
    portfolio_ids = request.args.get('portfolio_ids', '')
    asin_filter   = request.args.get('asin', '').strip().upper()
    sort_by       = request.args.get('sort_by', 'clicks')
    sort_dir      = request.args.get('sort_dir', 'desc').upper()
    try:
        page     = max(1, int(request.args.get('page', 1)))
        per_page = min(100, max(1, int(request.args.get('per_page', 50))))
    except ValueError:
        page, per_page = 1, 50

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400

    ALLOWED_SORT = {'impressions','clicks','cost','sales_14d','purchases_14d','acos','ctr','asin','marketplace'}
    if sort_by not in ALLOWED_SORT:
        sort_by = 'clicks'
    if sort_dir not in ('ASC', 'DESC'):
        sort_dir = 'DESC'

    # Числовые фильтры (HAVING на with_metrics)
    NUM_FIELDS = ['impressions','clicks','cost','ctr','sales_14d','purchases_14d','acos']
    OP_MAP = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'eq': '='}
    having_parts = []
    for fld in NUM_FIELDS:
        op  = request.args.get(fld + '_op', '')
        val = request.args.get(fld + '_val', '')
        mn  = request.args.get(fld + '_min', '')
        mx  = request.args.get(fld + '_max', '')
        if op and val and op in OP_MAP:
            try: having_parts.append(f'{fld} {OP_MAP[op]} {float(val)}')
            except ValueError: pass
        if mn:
            try: having_parts.append(f'{fld} >= {float(mn)}')
            except ValueError: pass
        if mx:
            try: having_parts.append(f'{fld} <= {float(mx)}')
            except ValueError: pass
    having_clause = ('HAVING ' + ' AND '.join(having_parts)) if having_parts else ''
    where_clause  = ('WHERE ' + ' AND '.join(having_parts)) if having_parts else ''

    suffix     = account_type.lower()
    asin_table = f"{PROJECT_ID}.{DATASET}.asin_stats_{suffix}"
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    cat_table  = f"{PROJECT_ID}.{DATASET}.catalog"

    date_conds = []
    if date_from: date_conds.append(f"a.date >= '{date_from}'")
    if date_to:   date_conds.append(f"a.date <= '{date_to}'")
    date_where = ('AND ' + ' AND '.join(date_conds)) if date_conds else ''

    # Фильтры для CTE camp_filter — используем алиас camp (не c!)
    camp_conds = ["camp.entity_type = 'campaign'"]
    if marketplace:
        camp_conds.append(f"camp.marketplace = '{marketplace}'")
    if portfolio_ids:
        ids = [i.strip() for i in portfolio_ids.split(',') if i.strip()]
        safe_ids = ','.join(f"'{i}'" for i in ids)
        camp_conds.append(f"camp.portfolio_id IN ({safe_ids})")
    camp_where = 'WHERE ' + ' AND '.join(camp_conds)

    asin_cond = ''
    if asin_filter:
        safe_asin = asin_filter.replace("'", "''")
        asin_cond = f"AND a.advertised_asin LIKE '%{safe_asin}%'"

    sql = f"""
    WITH camp_filter AS (
        SELECT DISTINCT camp.campaign_id, camp.marketplace
        FROM `{camp_table}` camp
        {camp_where}
    ),
    stats AS (
        SELECT
            a.advertised_asin                   AS asin,
            a.marketplace,
            SUM(a.impressions)                  AS impressions,
            SUM(a.clicks)                       AS clicks,
            ROUND(SUM(a.cost), 2)               AS cost,
            ROUND(SUM(a.sales_14d), 2)          AS sales_14d,
            SUM(a.purchases_14d)                AS purchases_14d,
            COUNT(DISTINCT a.campaign_id)       AS campaign_count
        FROM `{asin_table}` a
        INNER JOIN camp_filter cf
            ON cf.campaign_id = a.campaign_id
            AND cf.marketplace = a.marketplace
        WHERE a.advertised_asin IS NOT NULL
          AND a.advertised_asin != ''
        {date_where}
        {asin_cond}
        GROUP BY a.advertised_asin, a.marketplace
    ),
    with_metrics AS (
        SELECT *,
            CASE WHEN impressions > 0 THEN ROUND(clicks / impressions * 100, 3) ELSE NULL END AS ctr,
            CASE WHEN sales_14d   > 0 THEN ROUND(cost / sales_14d * 100, 1)    ELSE NULL END AS acos
        FROM stats
    )
    SELECT
        s.*,
        cat.title,
        cat.image_url,
        cat.product_type,
        cat.price,
        cat.status
    FROM with_metrics s
    LEFT JOIN `{cat_table}` cat
        ON cat.asin = s.asin AND cat.marketplace = s.marketplace
    {where_clause}
    ORDER BY {sort_by} {sort_dir} NULLS LAST
    LIMIT {per_page} OFFSET {(page-1)*per_page}
    """

    count_sql = f"""
    WITH camp_filter AS (
        SELECT DISTINCT camp.campaign_id, camp.marketplace
        FROM `{camp_table}` camp
        {camp_where}
    )
    SELECT COUNT(*) AS total FROM (
        SELECT
            a.advertised_asin AS asin, a.marketplace,
            SUM(a.impressions) AS impressions, SUM(a.clicks) AS clicks,
            ROUND(SUM(a.cost),2) AS cost, ROUND(SUM(a.sales_14d),2) AS sales_14d,
            SUM(a.purchases_14d) AS purchases_14d,
            CASE WHEN SUM(a.impressions)>0 THEN ROUND(SUM(a.clicks)/SUM(a.impressions)*100,3) ELSE NULL END AS ctr,
            CASE WHEN SUM(a.sales_14d)>0 THEN ROUND(SUM(a.cost)/SUM(a.sales_14d)*100,1) ELSE NULL END AS acos
        FROM `{asin_table}` a
        INNER JOIN camp_filter cf
            ON cf.campaign_id = a.campaign_id AND cf.marketplace = a.marketplace
        WHERE a.advertised_asin IS NOT NULL AND a.advertised_asin != ''
        {date_where}
        {asin_cond}
        GROUP BY a.advertised_asin, a.marketplace
    ) t
    {where_clause}
    """

    summary_sql = f"""
    WITH camp_filter AS (
        SELECT DISTINCT camp.campaign_id, camp.marketplace
        FROM `{camp_table}` camp
        {camp_where}
    ),
    agg AS (
        SELECT
            a.advertised_asin AS asin,
            a.marketplace,
            SUM(a.impressions)   AS impressions,
            SUM(a.clicks)        AS clicks,
            ROUND(SUM(a.cost),2) AS cost,
            ROUND(SUM(a.sales_14d),2) AS sales_14d,
            SUM(a.purchases_14d) AS purchases_14d,
            CASE WHEN SUM(a.impressions)>0 THEN ROUND(SUM(a.clicks)/SUM(a.impressions)*100,3) ELSE NULL END AS ctr,
            CASE WHEN SUM(a.sales_14d)>0 THEN ROUND(SUM(a.cost)/SUM(a.sales_14d)*100,1) ELSE NULL END AS acos
        FROM `{asin_table}` a
        INNER JOIN camp_filter cf
            ON cf.campaign_id = a.campaign_id AND cf.marketplace = a.marketplace
        WHERE a.advertised_asin IS NOT NULL AND a.advertised_asin != ''
        {date_where}
        {asin_cond}
        GROUP BY a.advertised_asin, a.marketplace
    )
    SELECT
        COUNT(DISTINCT asin)   AS total_asins,
        SUM(impressions)       AS impressions,
        SUM(clicks)            AS clicks,
        ROUND(SUM(cost), 2)    AS cost,
        ROUND(SUM(sales_14d),2) AS sales_14d,
        SUM(purchases_14d)     AS purchases_14d
    FROM agg
    {where_clause}
    """

    try:
        client = bigquery.Client(project=PROJECT_ID)

        def cvt(v):
            return float(v) if isinstance(v, decimal.Decimal) else v

        rows_raw    = list(client.query(sql).result())
        count_raw   = list(client.query(count_sql).result())
        summary_raw = list(client.query(summary_sql).result())

        total   = int(count_raw[0].total) if count_raw else 0
        sum_row = dict(summary_raw[0]) if summary_raw else {}
        rows    = [{k: cvt(v) for k, v in dict(r).items()} for r in rows_raw]

        impr  = float(sum_row.get('impressions') or 0)
        clks  = float(sum_row.get('clicks') or 0)
        cost  = float(sum_row.get('cost') or 0)
        sales = float(sum_row.get('sales_14d') or 0)

        summary = {
            'total_asins':   int(sum_row.get('total_asins') or 0),
            'impressions':   int(impr),
            'clicks':        int(clks),
            'cost':          round(cost, 2),
            'sales_14d':     round(sales, 2),
            'purchases_14d': int(sum_row.get('purchases_14d') or 0),
            'acos': round(cost/sales*100, 1) if sales > 0 else None,
            'ctr':  round(clks/impr*100, 3) if impr > 0 else None,
        }

        return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page, 'summary': summary})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Кампании для конкретного ASIN ─────────────────────────
@products_bp.route('/analytics/products/campaigns')
def analytics_product_campaigns():
    asin         = request.args.get('asin', '')
    marketplace  = request.args.get('marketplace', '')
    account_type = request.args.get('account_type', 'MERCH').upper()
    date_from    = request.args.get('date_from', '')
    date_to      = request.args.get('date_to', '')

    if not asin or account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверные параметры"}), 400

    suffix     = account_type.lower()
    asin_table = f"{PROJECT_ID}.{DATASET}.asin_stats_{suffix}"
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    pf_table   = f"{PROJECT_ID}.{DATASET}.portfolio_labels"

    date_conds = []
    if date_from: date_conds.append(f"a.date >= '{date_from}'")
    if date_to:   date_conds.append(f"a.date <= '{date_to}'")
    date_where = ('AND ' + ' AND '.join(date_conds)) if date_conds else ''
    mkt_cond   = f"AND a.marketplace = '{marketplace}'" if marketplace else ''

    sql = f"""
    SELECT
        a.campaign_id,
        MAX(camp.campaign_name)    AS campaign_name,
        MAX(camp.campaign_state)   AS campaign_state,
        MAX(camp.targeting_type)   AS targeting_type,
        MAX(camp.portfolio_id)     AS portfolio_id,
        COALESCE(MAX(pl.portfolio_name), MAX(camp.portfolio_name)) AS portfolio_name,
        MAX(camp.daily_budget)     AS daily_budget,
        MAX(camp.end_date)         AS campaign_end_date,
        a.marketplace,
        SUM(a.impressions)           AS impressions,
        SUM(a.clicks)                AS clicks,
        ROUND(SUM(a.cost), 2)        AS cost,
        ROUND(SUM(a.sales_14d), 2)   AS sales_14d,
        SUM(a.purchases_14d)         AS purchases_14d
    FROM `{asin_table}` a
    LEFT JOIN `{camp_table}` camp
        ON camp.campaign_id = a.campaign_id
        AND camp.marketplace = a.marketplace
        AND camp.entity_type = 'campaign'
    LEFT JOIN `{pf_table}` pl
        ON pl.portfolio_id   = camp.portfolio_id
        AND pl.marketplace   = a.marketplace
        AND pl.account_type  = '{account_type}'
    WHERE a.advertised_asin = '{asin}'
    {mkt_cond}
    {date_where}
    GROUP BY a.campaign_id, a.marketplace
    ORDER BY clicks DESC
    LIMIT 100
    """

    try:
        client = bigquery.Client(project=PROJECT_ID)

        def cvt(v):
            return float(v) if isinstance(v, decimal.Decimal) else v

        rows = []
        for r in list(client.query(sql).result()):
            d = {k: cvt(v) for k, v in dict(r).items()}
            impr  = float(d.get('impressions') or 0)
            clks  = float(d.get('clicks') or 0)
            cost  = float(d.get('cost') or 0)
            sales = float(d.get('sales_14d') or 0)
            d['ctr']  = round(clks/impr*100, 3) if impr > 0 else None
            d['acos'] = round(cost/sales*100, 1) if sales > 0 else None
            rows.append(d)

        return jsonify({'campaigns': rows})

    except Exception as e:
        return jsonify({"error": str(e)}), 500