from bq_client import get_client
import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory

sales_comparison_bp = Blueprint('sales_comparison', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

ALLOWED_SORT = {
    'asin', 'title', 'product_type', 'organic_units', 'organic_royalties',
    'clicks', 'ad_spend', 'attributed_orders', 'attributed_sales',
    'ad_share_pct', 'tacos', 'acos', 'cpc',
}

# earnings table stores marketplace as domain suffix (from Merch CSV): .com, .co.uk, .de ...
MKT_DOMAIN_MAP = {
    'US': '.com',
    'DE': '.de',
    'UK': '.co.uk',
    'FR': '.fr',
    'ES': '.es',
    'IT': '.it',
    'JP': '.co.jp',
}


def _cvt(v):
    return float(v) if isinstance(v, decimal.Decimal) else v


@sales_comparison_bp.route('/sales-comparison')
def sales_comparison_page():
    return send_from_directory(BASE_DIR, 'sales_comparison.html')


@sales_comparison_bp.route('/sales-comparison/data')
def sales_comparison_data():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    date_from    = args.get('date_from', '')
    date_to      = args.get('date_to', '')
    marketplace  = args.get('marketplace', 'US').upper()
    name_filter  = args.get('name', '').strip()
    product_type = args.get('product_type', '').strip()
    ad_filter    = args.get('ad_filter', '')
    portfolio_ids_raw = args.get('portfolio_ids', '')
    sort_by      = args.get('sort_by', 'ad_spend')
    sort_dir     = 'DESC' if args.get('sort_dir', 'desc').lower() == 'desc' else 'ASC'
    page         = max(1, int(args.get('page', 1)))
    per_page     = min(200, max(10, int(args.get('per_page', 50))))
    offset       = (page - 1) * per_page

    if sort_by not in ALLOWED_SORT:
        sort_by = 'ad_spend'

    safe_mkt = marketplace.replace("'", "''")
    # earnings table stores marketplace as domain (e.g. amazon.com); map from code
    earn_mkt = MKT_DOMAIN_MAP.get(marketplace, safe_mkt).replace("'", "''")

    if account_type == 'MERCH':
        earn_date_field = 'sale_date'
    else:
        earn_date_field = 'royalty_date'

    earn_date_parts = []
    ads_date_parts  = []
    if date_from:
        earn_date_parts.append(f"e.{earn_date_field} >= '{date_from}'")
        ads_date_parts.append(f"a.date >= '{date_from}'")
    if date_to:
        earn_date_parts.append(f"e.{earn_date_field} <= '{date_to}'")
        ads_date_parts.append(f"a.date <= '{date_to}'")
    earn_date_cond = ('AND ' + ' AND '.join(earn_date_parts)) if earn_date_parts else ''
    ads_date_cond  = ('AND ' + ' AND '.join(ads_date_parts))  if ads_date_parts  else ''

    name_cond = ''
    if name_filter:
        sn = name_filter.replace("'", "''")
        name_cond = f"AND (LOWER(COALESCE(o.asin, ads.asin, '')) LIKE LOWER('%{sn}%') OR LOWER(COALESCE(o.title, '')) LIKE LOWER('%{sn}%'))"

    pt_cond = ''
    if product_type:
        spt = product_type.replace("'", "''")
        # earnings.product_type stores human values like "Standard T-Shirt"; use LIKE
        pt_cond = f"AND UPPER(COALESCE(o.product_type, '')) LIKE UPPER('%{spt}%')"

    ad_cond = ''
    if ad_filter == 'advertised':
        ad_cond = 'AND COALESCE(ads.ad_spend, 0) > 0'
    elif ad_filter == 'organic':
        ad_cond = 'AND COALESCE(ads.ad_spend, 0) = 0'

    if account_type == 'MERCH':
        earn_table = f"{PROJECT_ID}.{DATASET}.earnings"
        asin_table = f"{PROJECT_ID}.{DATASET}.asin_stats_merch"
        cat_table  = f"{PROJECT_ID}.{DATASET}.catalog"
        camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_merch"

        portfolio_cte  = ''
        portfolio_cond = ''
        if portfolio_ids_raw:
            pids = [p.strip() for p in portfolio_ids_raw.split(',') if p.strip()]
            if pids:
                quoted_pids = ','.join(f"'{p}'" for p in pids)
                portfolio_cte = f"""portfolio_asins AS (
  SELECT DISTINCT a.advertised_asin
  FROM `{asin_table}` a
  JOIN (
    SELECT campaign_id, marketplace, portfolio_id,
      ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
    FROM `{camp_table}` WHERE entity_type='campaign'
  ) c ON c.campaign_id = a.campaign_id AND c.marketplace = a.marketplace AND c.rn = 1
  WHERE c.portfolio_id IN ({quoted_pids}) AND a.marketplace = '{safe_mkt}'
),"""
                portfolio_cond = f"AND COALESCE(o.asin, ads.asin) IN (SELECT advertised_asin FROM portfolio_asins)"

        sql = f"""
WITH {portfolio_cte}
organic AS (
  SELECT e.asin, '{safe_mkt}' AS marketplace,
    SUM(e.purchased) AS organic_units,
    ROUND(SUM(e.royalties), 2) AS organic_royalties,
    MAX(e.title) AS title,
    MAX(e.product_type) AS product_type
  FROM `{earn_table}` e
  WHERE e.marketplace = '{earn_mkt}' {earn_date_cond}
  GROUP BY e.asin
),
ads AS (
  SELECT a.advertised_asin AS asin, a.marketplace,
    SUM(a.clicks) AS clicks,
    ROUND(SUM(a.cost), 2) AS ad_spend,
    SUM(a.purchases_14d) AS attributed_orders,
    ROUND(SUM(a.sales_14d), 2) AS attributed_sales
  FROM `{asin_table}` a
  WHERE a.marketplace = '{safe_mkt}' {ads_date_cond}
  GROUP BY a.advertised_asin, a.marketplace
),
cat AS (
  SELECT asin, marketplace, image_url, status,
    ROW_NUMBER() OVER (PARTITION BY asin, marketplace ORDER BY imported_at DESC) rn
  FROM `{cat_table}`
),
base AS (
  SELECT
    COALESCE(o.asin, ads.asin) AS asin,
    COALESCE(o.marketplace, ads.marketplace) AS marketplace,
    COALESCE(o.title, c.title, '') AS title,
    COALESCE(o.product_type, c.product_type, '') AS product_type,
    c.image_url, c.status,
    COALESCE(o.organic_units, 0) AS organic_units,
    COALESCE(o.organic_royalties, 0) AS organic_royalties,
    COALESCE(ads.clicks, 0) AS clicks,
    COALESCE(ads.ad_spend, 0) AS ad_spend,
    COALESCE(ads.attributed_orders, 0) AS attributed_orders,
    COALESCE(ads.attributed_sales, 0) AS attributed_sales,
    CASE WHEN (COALESCE(o.organic_royalties,0) + COALESCE(ads.attributed_sales,0)) > 0
         THEN ROUND(COALESCE(ads.attributed_sales,0) / (COALESCE(o.organic_royalties,0) + COALESCE(ads.attributed_sales,0)) * 100, 1)
         ELSE NULL END AS ad_share_pct,
    CASE WHEN (COALESCE(o.organic_royalties,0) + COALESCE(ads.attributed_sales,0)) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / (COALESCE(o.organic_royalties,0) + COALESCE(ads.attributed_sales,0)) * 100, 1)
         ELSE NULL END AS tacos,
    CASE WHEN COALESCE(ads.clicks,0) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / ads.clicks, 2)
         ELSE NULL END AS cpc,
    CASE WHEN COALESCE(ads.attributed_sales,0) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / ads.attributed_sales * 100, 1)
         ELSE NULL END AS acos
  FROM organic o
  FULL OUTER JOIN ads ON ads.asin = o.asin AND ads.marketplace = o.marketplace
  LEFT JOIN cat c ON c.asin = COALESCE(o.asin, ads.asin) AND c.marketplace = COALESCE(o.marketplace, ads.marketplace) AND c.rn = 1
  WHERE 1=1 {name_cond} {pt_cond} {ad_cond} {portfolio_cond}
)
SELECT *, COUNT(*) OVER() AS _total,
  ROUND(SUM(organic_royalties) OVER(), 2) AS _sum_royalties,
  ROUND(SUM(ad_spend) OVER(), 2) AS _sum_spend,
  ROUND(SUM(attributed_sales) OVER(), 2) AS _sum_attr_sales,
  SUM(clicks) OVER() AS _sum_clicks,
  SUM(organic_units) OVER() AS _sum_units
FROM base
ORDER BY {sort_by} {sort_dir} NULLS LAST
LIMIT {per_page} OFFSET {offset}
"""
    else:
        earn_table = f"{PROJECT_ID}.{DATASET}.earnings_kdp"
        asin_table = f"{PROJECT_ID}.{DATASET}.asin_stats_kdp"

        sql = f"""
WITH organic AS (
  SELECT e.asin_isbn AS asin, '{safe_mkt}' AS marketplace,
    SUM(e.net_units_sold) AS organic_units,
    ROUND(SUM(e.royalty), 2) AS organic_royalties,
    MAX(e.title) AS title,
    MAX(e.transaction_type) AS product_type
  FROM `{earn_table}` e
  WHERE e.marketplace = '{earn_mkt}' {earn_date_cond}
  GROUP BY e.asin_isbn
),
ads AS (
  SELECT a.advertised_asin AS asin, a.marketplace,
    SUM(a.clicks) AS clicks,
    ROUND(SUM(a.cost), 2) AS ad_spend,
    SUM(a.purchases_14d) AS attributed_orders,
    ROUND(SUM(a.sales_14d), 2) AS attributed_sales
  FROM `{asin_table}` a
  WHERE a.marketplace = '{safe_mkt}' {ads_date_cond}
  GROUP BY a.advertised_asin, a.marketplace
),
base AS (
  SELECT
    COALESCE(o.asin, ads.asin) AS asin,
    COALESCE(o.marketplace, ads.marketplace) AS marketplace,
    COALESCE(o.title, '') AS title,
    COALESCE(o.product_type, '') AS product_type,
    CAST(NULL AS STRING) AS image_url,
    CAST(NULL AS STRING) AS status,
    COALESCE(o.organic_units, 0) AS organic_units,
    COALESCE(o.organic_royalties, 0) AS organic_royalties,
    COALESCE(ads.clicks, 0) AS clicks,
    COALESCE(ads.ad_spend, 0) AS ad_spend,
    COALESCE(ads.attributed_orders, 0) AS attributed_orders,
    COALESCE(ads.attributed_sales, 0) AS attributed_sales,
    CASE WHEN (COALESCE(o.organic_royalties,0) + COALESCE(ads.attributed_sales,0)) > 0
         THEN ROUND(COALESCE(ads.attributed_sales,0) / (COALESCE(o.organic_royalties,0) + COALESCE(ads.attributed_sales,0)) * 100, 1)
         ELSE NULL END AS ad_share_pct,
    CASE WHEN (COALESCE(o.organic_royalties,0) + COALESCE(ads.attributed_sales,0)) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / (COALESCE(o.organic_royalties,0) + COALESCE(ads.attributed_sales,0)) * 100, 1)
         ELSE NULL END AS tacos,
    CASE WHEN COALESCE(ads.clicks,0) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / ads.clicks, 2)
         ELSE NULL END AS cpc,
    CASE WHEN COALESCE(ads.attributed_sales,0) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / ads.attributed_sales * 100, 1)
         ELSE NULL END AS acos
  FROM organic o
  FULL OUTER JOIN ads ON ads.asin = o.asin AND ads.marketplace = o.marketplace
  WHERE 1=1 {name_cond} {pt_cond} {ad_cond}
)
SELECT *, COUNT(*) OVER() AS _total,
  ROUND(SUM(organic_royalties) OVER(), 2) AS _sum_royalties,
  ROUND(SUM(ad_spend) OVER(), 2) AS _sum_spend,
  ROUND(SUM(attributed_sales) OVER(), 2) AS _sum_attr_sales,
  SUM(clicks) OVER() AS _sum_clicks,
  SUM(organic_units) OVER() AS _sum_units
FROM base
ORDER BY {sort_by} {sort_dir} NULLS LAST
LIMIT {per_page} OFFSET {offset}
"""

    try:
        client = get_client()
        rows = list(client.query(sql).result())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    if not rows:
        return jsonify({
            'rows': [], 'total': 0, 'page': page, 'per_page': per_page,
            'summary': {'sum_royalties': 0, 'sum_spend': 0, 'sum_attr_sales': 0,
                        'sum_clicks': 0, 'sum_units': 0}
        })

    total          = int(rows[0]['_total'])
    sum_royalties  = float(rows[0]['_sum_royalties'] or 0)
    sum_spend      = float(rows[0]['_sum_spend'] or 0)
    sum_attr_sales = float(rows[0]['_sum_attr_sales'] or 0)
    sum_clicks     = int(rows[0]['_sum_clicks'] or 0)
    sum_units      = int(rows[0]['_sum_units'] or 0)

    skip = {'_total', '_sum_royalties', '_sum_spend', '_sum_attr_sales', '_sum_clicks', '_sum_units'}
    result_rows = [{k: _cvt(v) for k, v in dict(r).items() if k not in skip} for r in rows]

    return jsonify({
        'rows': result_rows,
        'total': total,
        'page': page,
        'per_page': per_page,
        'summary': {
            'sum_royalties': sum_royalties,
            'sum_spend': sum_spend,
            'sum_attr_sales': sum_attr_sales,
            'sum_clicks': sum_clicks,
            'sum_units': sum_units,
        }
    })


@sales_comparison_bp.route('/sales-comparison/weekly')
def sales_comparison_weekly():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    asin         = args.get('asin', '').strip()
    marketplace  = args.get('marketplace', 'US').upper()
    date_from    = args.get('date_from', '')
    date_to      = args.get('date_to', '')

    if not asin:
        return jsonify({'weeks': []})

    safe_mkt  = marketplace.replace("'", "''")
    # both earnings and earnings_kdp store marketplace as domain (amazon.com etc.)
    earn_mkt  = MKT_DOMAIN_MAP.get(marketplace, safe_mkt).replace("'", "''")
    safe_asin = asin.replace("'", "''")

    if account_type == 'MERCH':
        earn_table         = f"{PROJECT_ID}.{DATASET}.earnings"
        asin_table         = f"{PROJECT_ID}.{DATASET}.asin_stats_merch"
        earn_asin_field    = 'asin'
        earn_date_field    = 'sale_date'
        earn_royalty_field = 'royalties'
        earn_units_field   = 'purchased'
    else:
        earn_table         = f"{PROJECT_ID}.{DATASET}.earnings_kdp"
        asin_table         = f"{PROJECT_ID}.{DATASET}.asin_stats_kdp"
        earn_asin_field    = 'asin_isbn'
        earn_date_field    = 'royalty_date'
        earn_royalty_field = 'royalty'
        earn_units_field   = 'net_units_sold'

    earn_date_parts = []
    ads_date_parts  = []
    if date_from:
        earn_date_parts.append(f"e.{earn_date_field} >= '{date_from}'")
        ads_date_parts.append(f"a.date >= '{date_from}'")
    if date_to:
        earn_date_parts.append(f"e.{earn_date_field} <= '{date_to}'")
        ads_date_parts.append(f"a.date <= '{date_to}'")
    earn_date_cond = ('AND ' + ' AND '.join(earn_date_parts)) if earn_date_parts else ''
    ads_date_cond  = ('AND ' + ' AND '.join(ads_date_parts))  if ads_date_parts  else ''

    sql = f"""
WITH earn_weekly AS (
  SELECT
    DATE_TRUNC(e.{earn_date_field}, WEEK(MONDAY)) AS week,
    SUM(e.{earn_units_field}) AS organic_units,
    ROUND(SUM(e.{earn_royalty_field}), 2) AS organic_royalties
  FROM `{earn_table}` e
  WHERE e.{earn_asin_field} = '{safe_asin}' AND e.marketplace = '{earn_mkt}' {earn_date_cond}
  GROUP BY 1
),
ads_weekly AS (
  SELECT
    DATE_TRUNC(a.date, WEEK(MONDAY)) AS week,
    SUM(a.clicks) AS clicks,
    ROUND(SUM(a.cost), 2) AS ad_spend,
    ROUND(SUM(a.sales_14d), 2) AS attributed_sales
  FROM `{asin_table}` a
  WHERE a.advertised_asin = '{safe_asin}' AND a.marketplace = '{safe_mkt}' {ads_date_cond}
  GROUP BY 1
)
SELECT
  COALESCE(e.week, a.week) AS week,
  COALESCE(e.organic_units, 0) AS organic_units,
  COALESCE(e.organic_royalties, 0) AS organic_royalties,
  COALESCE(a.clicks, 0) AS clicks,
  COALESCE(a.ad_spend, 0) AS ad_spend,
  COALESCE(a.attributed_sales, 0) AS attributed_sales
FROM earn_weekly e
FULL OUTER JOIN ads_weekly a ON a.week = e.week
ORDER BY 1
"""

    try:
        client = get_client()
        rows = list(client.query(sql).result())
        weeks = []
        for r in rows:
            d = dict(r)
            d['week'] = d['week'].isoformat() if d['week'] else None
            d = {k: _cvt(v) for k, v in d.items()}
            weeks.append(d)
        return jsonify({'weeks': weeks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@sales_comparison_bp.route('/sales-comparison/campaigns')
def sales_comparison_campaigns():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    asin         = args.get('asin', '').strip()
    marketplace  = args.get('marketplace', 'US').upper()
    date_from    = args.get('date_from', '')
    date_to      = args.get('date_to', '')

    if not asin:
        return jsonify({'campaigns': []})

    safe_mkt  = marketplace.replace("'", "''")
    safe_asin = asin.replace("'", "''")
    suffix    = account_type.lower()

    asin_table = f"{PROJECT_ID}.{DATASET}.asin_stats_{suffix}"
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"

    ads_date_parts = []
    if date_from:
        ads_date_parts.append(f"a.date >= '{date_from}'")
    if date_to:
        ads_date_parts.append(f"a.date <= '{date_to}'")
    ads_date_cond = ('AND ' + ' AND '.join(ads_date_parts)) if ads_date_parts else ''

    sql = f"""
WITH agg AS (
  SELECT
    a.campaign_id,
    a.marketplace,
    SUM(a.clicks) AS clicks,
    ROUND(SUM(a.cost), 2) AS ad_spend,
    ROUND(SUM(a.sales_14d), 2) AS attributed_sales
  FROM `{asin_table}` a
  WHERE a.advertised_asin = '{safe_asin}' AND a.marketplace = '{safe_mkt}' {ads_date_cond}
  GROUP BY a.campaign_id, a.marketplace
),
c_raw AS (
  SELECT campaign_id, campaign_name, campaign_state, marketplace,
    ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
  FROM `{camp_table}` WHERE entity_type = 'campaign'
),
c AS (SELECT * FROM c_raw WHERE rn = 1)
SELECT
  c.campaign_name,
  c.campaign_state,
  agg.clicks,
  agg.ad_spend,
  agg.attributed_sales,
  CASE WHEN agg.attributed_sales > 0
       THEN ROUND(agg.ad_spend / agg.attributed_sales * 100, 1)
       ELSE NULL END AS acos
FROM agg
JOIN c ON c.campaign_id = agg.campaign_id AND c.marketplace = agg.marketplace
ORDER BY agg.ad_spend DESC
LIMIT 50
"""

    try:
        client = get_client()
        rows = list(client.query(sql).result())
        campaigns = [{k: _cvt(v) for k, v in dict(r).items()} for r in rows]
        return jsonify({'campaigns': campaigns})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
