from bq_client import get_client
import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory

sales_comparison_bp = Blueprint('sales_comparison', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

ALLOWED_SORT = {
    'asin', 'title', 'product_type', 'total_units', 'royalties', 'total_revenue',
    'clicks', 'ad_spend', 'ad_orders', 'ad_sales',
    'ad_share_pct', 'tacos', 'acos', 'cpc',
}

NUM_FIELDS = ['royalties', 'total_revenue', 'total_units', 'ad_spend', 'ad_sales', 'ad_orders',
              'clicks', 'cpc', 'tacos', 'acos', 'ad_share_pct']

OP_MAP = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'eq': '='}


def _build_num_where(args):
    parts = []
    for fld in NUM_FIELDS:
        op  = args.get(fld + '_op', '')
        val = args.get(fld + '_val', '')
        mn  = args.get(fld + '_min', '')
        mx  = args.get(fld + '_max', '')
        if op and val != '' and op in OP_MAP:
            try: parts.append(f'{fld} {OP_MAP[op]} {float(val)}')
            except ValueError: pass
        if mn != '':
            try: parts.append(f'{fld} >= {float(mn)}')
            except ValueError: pass
        if mx != '':
            try: parts.append(f'{fld} <= {float(mx)}')
            except ValueError: pass
    return ('WHERE ' + ' AND '.join(parts)) if parts else ''

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

KDP_DOMAIN_MAP = {
    'US': 'Amazon.com',
    'UK': 'Amazon.co.uk',
    'DE': 'Amazon.de',
    'FR': 'Amazon.fr',
    'ES': 'Amazon.es',
    'IT': 'Amazon.it',
    'JP': 'Amazon.co.jp',
    'CA': 'Amazon.ca',
    'AU': 'Amazon.com.au',
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
    product_type = args.get('product_types', args.get('product_type', '')).strip()
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
    # MERCH earnings uses suffix (.com), KDP uses full domain (Amazon.com)
    if account_type == 'KDP':
        earn_mkt = KDP_DOMAIN_MAP.get(marketplace, f'Amazon.{safe_mkt.lower()}').replace("'", "''")
    else:
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
        pts = [p.strip() for p in product_type.split(',') if p.strip()]
        if len(pts) == 1:
            spt = pts[0].replace("'", "''")
            pt_cond = f"AND UPPER(COALESCE(o.product_type, '')) LIKE UPPER('%{spt}%')"
        elif pts:
            quoted = ', '.join(f"'{p.replace(chr(39), chr(39)*2)}'" for p in pts)
            pt_cond = f"AND UPPER(COALESCE(o.product_type, '')) IN ({', '.join(f'UPPER({q})' for q in [repr(p) for p in pts])})"
            # use LIKE for each to be safe with case
            parts = [f"UPPER(COALESCE(o.product_type,'')) LIKE UPPER('%{p.replace(chr(39), chr(39)*2)}%')" for p in pts]
            pt_cond = f"AND ({' OR '.join(parts)})"

    ad_cond = ''
    if ad_filter == 'advertised':
        ad_cond = 'AND COALESCE(ads.ad_spend, 0) > 0'
    elif ad_filter == 'organic':
        ad_cond = 'AND COALESCE(ads.ad_spend, 0) = 0'

    num_where = _build_num_where(args)

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
                portfolio_cond = f"AND COALESCE(a.primary_asin, o.grp_key) IN (SELECT advertised_asin FROM portfolio_asins)"

        sql = f"""
WITH {portfolio_cte}
cat AS (
  SELECT asin, design_id, marketplace, title, image_url, status,
    CASE product_type
      WHEN 'STANDARD_TSHIRT'        THEN 'Standard t-shirt'
      WHEN 'HOODIE'                 THEN 'Pullover hoodie'
      WHEN 'STANDARD_PULLOVER_HOODIE' THEN 'Pullover hoodie'
      WHEN 'SWEATSHIRT'             THEN 'Sweatshirt'
      WHEN 'STANDARD_SWEATSHIRT'    THEN 'Sweatshirt'
      WHEN 'TANK_TOP'               THEN 'Tank top'
      WHEN 'LONG_SLEEVE_TEE'        THEN 'Long sleeve t-shirt'
      WHEN 'STANDARD_LONG_SLEEVE'   THEN 'Long sleeve t-shirt'
      WHEN 'V_NECK_TEE'             THEN 'V-neck t-shirt'
      WHEN 'VNECK'                  THEN 'V-neck t-shirt'
      WHEN 'ZIP_HOODIE'             THEN 'Zip hoodie'
      WHEN 'STANDARD_ZIP_HOODIE'    THEN 'Zip hoodie'
      WHEN 'POPSOCKET'              THEN 'PopSockets'
      WHEN 'IPHONE_CASE'            THEN 'iPhone cases'
      WHEN 'PREMIUM_TSHIRT'         THEN 'Premium t-shirt'
      WHEN 'RAGLAN'                 THEN 'Raglan'
      WHEN 'TANK_TOP'               THEN 'Tank top'
      ELSE product_type
    END AS product_type_norm,
    ROW_NUMBER() OVER (PARTITION BY asin, marketplace ORDER BY imported_at DESC) rn
  FROM `{cat_table}`
),
cat1 AS (SELECT * FROM cat WHERE rn = 1),
earn_raw AS (
  SELECT e.asin,
    SUM(e.purchased) AS total_units,
    ROUND(SUM(e.royalties), 2) AS royalties,
    ROUND(SUM(e.revenue), 2) AS total_revenue,
    MAX(e.product_type) AS earn_pt
  FROM `{earn_table}` e
  WHERE e.marketplace = '{earn_mkt}' {earn_date_cond}
  GROUP BY e.asin
),
earn_keyed AS (
  SELECT
    COALESCE(c.design_id, e.asin)            AS grp_key,
    COALESCE(c.product_type_norm, e.earn_pt) AS pt_key,
    '{safe_mkt}'                              AS marketplace,
    e.total_units, e.royalties, e.total_revenue,
    c.title, c.image_url, c.status
  FROM earn_raw e
  LEFT JOIN cat1 c ON c.asin = e.asin AND c.marketplace = '{safe_mkt}'
),
organic AS (
  SELECT grp_key, pt_key, marketplace,
    SUM(total_units)        AS total_units,
    ROUND(SUM(royalties),2) AS royalties,
    ROUND(SUM(total_revenue),2) AS total_revenue,
    MAX(title)     AS title,
    MAX(image_url) AS image_url,
    MAX(status)    AS status
  FROM earn_keyed
  GROUP BY grp_key, pt_key, marketplace
),
ads_raw AS (
  SELECT a.advertised_asin AS asin, a.marketplace,
    SUM(a.clicks)           AS clicks,
    ROUND(SUM(a.cost), 2)   AS ad_spend,
    SUM(a.purchases_14d)    AS ad_orders,
    ROUND(SUM(a.sales_14d), 2) AS ad_sales
  FROM `{asin_table}` a
  WHERE a.marketplace = '{safe_mkt}' {ads_date_cond}
  GROUP BY a.advertised_asin, a.marketplace
),
ads_keyed AS (
  SELECT
    COALESCE(c.design_id, a.asin) AS grp_key,
    COALESCE(c.product_type_norm, '') AS pt_key,
    a.clicks, a.ad_spend, a.ad_orders, a.ad_sales, a.marketplace,
    c.title, c.image_url, c.status,
    a.asin AS advertised_asin
  FROM ads_raw a
  LEFT JOIN cat1 c ON c.asin = a.asin AND c.marketplace = a.marketplace
),
ads AS (
  SELECT grp_key, pt_key, marketplace,
    SUM(clicks)            AS clicks,
    ROUND(SUM(ad_spend),2) AS ad_spend,
    SUM(ad_orders)         AS ad_orders,
    ROUND(SUM(ad_sales),2) AS ad_sales,
    MAX(title)              AS title,
    MAX(image_url)          AS image_url,
    MAX(status)             AS status,
    MIN(advertised_asin)    AS primary_asin
  FROM ads_keyed
  GROUP BY grp_key, pt_key, marketplace
),
base AS (
  SELECT
    COALESCE(o.grp_key, a.grp_key)       AS asin,
    COALESCE(o.marketplace, a.marketplace) AS marketplace,
    COALESCE(o.title, a.title, '')        AS title,
    COALESCE(o.pt_key, a.pt_key, '')      AS product_type,
    COALESCE(o.image_url, a.image_url)    AS image_url,
    COALESCE(o.status, a.status)          AS status,
    COALESCE(a.primary_asin, o.grp_key)  AS primary_asin,
    COALESCE(o.total_units, 0)  AS total_units,
    COALESCE(o.royalties, 0)    AS royalties,
    COALESCE(o.total_revenue, 0) AS total_revenue,
    COALESCE(a.clicks, 0)       AS clicks,
    COALESCE(a.ad_spend, 0)     AS ad_spend,
    COALESCE(a.ad_orders, 0)    AS ad_orders,
    COALESCE(a.ad_sales, 0)     AS ad_sales,
    CASE WHEN COALESCE(o.royalties,0) > 0
         THEN ROUND(COALESCE(a.ad_spend,0) / o.royalties * 100, 1)
         ELSE NULL END AS ad_share_pct,
    CASE WHEN COALESCE(o.total_revenue,0) > 0
         THEN ROUND(COALESCE(a.ad_spend,0) / o.total_revenue * 100, 1)
         ELSE NULL END AS tacos,
    CASE WHEN COALESCE(a.clicks,0) > 0
         THEN ROUND(COALESCE(a.ad_spend,0) / a.clicks, 2)
         ELSE NULL END AS cpc,
    CASE WHEN COALESCE(a.ad_sales,0) > 0
         THEN ROUND(COALESCE(a.ad_spend,0) / a.ad_sales * 100, 1)
         ELSE NULL END AS acos
  FROM organic o
  FULL OUTER JOIN ads a ON a.grp_key = o.grp_key AND a.pt_key = o.pt_key AND a.marketplace = o.marketplace
  WHERE 1=1 {name_cond} {pt_cond} {ad_cond} {portfolio_cond}
),
filtered AS (SELECT * FROM base {num_where})
SELECT *, COUNT(*) OVER() AS _total,
  ROUND(SUM(royalties) OVER(), 2)      AS _sum_royalties,
  ROUND(SUM(total_revenue) OVER(), 2)  AS _sum_total_revenue,
  ROUND(SUM(ad_spend) OVER(), 2)       AS _sum_spend,
  ROUND(SUM(ad_sales) OVER(), 2)       AS _sum_ad_sales,
  SUM(clicks) OVER()                   AS _sum_clicks,
  SUM(total_units) OVER()              AS _sum_units
FROM filtered
ORDER BY {sort_by} {sort_dir} NULLS LAST
LIMIT {per_page} OFFSET {offset}
"""
    else:
        earn_table = f"{PROJECT_ID}.{DATASET}.earnings_kdp"
        asin_table = f"{PROJECT_ID}.{DATASET}.asin_stats_kdp"

        sql = f"""
WITH organic AS (
  SELECT e.asin_isbn AS asin, '{safe_mkt}' AS marketplace,
    SUM(e.net_units_sold) AS total_units,
    ROUND(SUM(e.royalty), 2) AS royalties,
    ROUND(SUM(e.royalty), 2) AS total_revenue,
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
    SUM(a.purchases_14d) AS ad_orders,
    ROUND(SUM(a.sales_14d), 2) AS ad_sales
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
    COALESCE(o.total_units, 0) AS total_units,
    COALESCE(o.royalties, 0) AS royalties,
    COALESCE(o.total_revenue, 0) AS total_revenue,
    COALESCE(ads.clicks, 0) AS clicks,
    COALESCE(ads.ad_spend, 0) AS ad_spend,
    COALESCE(ads.ad_orders, 0) AS ad_orders,
    COALESCE(ads.ad_sales, 0) AS ad_sales,
    CASE WHEN COALESCE(o.royalties,0) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / o.royalties * 100, 1)
         ELSE NULL END AS ad_share_pct,
    CASE WHEN COALESCE(o.total_revenue,0) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / o.total_revenue * 100, 1)
         ELSE NULL END AS tacos,
    CASE WHEN COALESCE(ads.clicks,0) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / ads.clicks, 2)
         ELSE NULL END AS cpc,
    CASE WHEN COALESCE(ads.ad_sales,0) > 0
         THEN ROUND(COALESCE(ads.ad_spend,0) / ads.ad_sales * 100, 1)
         ELSE NULL END AS acos
  FROM organic o
  FULL OUTER JOIN ads ON ads.asin = o.asin AND ads.marketplace = o.marketplace
  WHERE 1=1 {name_cond} {pt_cond} {ad_cond}
),
filtered AS (SELECT * FROM base {num_where})
SELECT *, COUNT(*) OVER() AS _total,
  ROUND(SUM(royalties) OVER(), 2) AS _sum_royalties,
  ROUND(SUM(total_revenue) OVER(), 2) AS _sum_total_revenue,
  ROUND(SUM(ad_spend) OVER(), 2) AS _sum_spend,
  ROUND(SUM(ad_sales) OVER(), 2) AS _sum_ad_sales,
  SUM(clicks) OVER() AS _sum_clicks,
  SUM(total_units) OVER() AS _sum_units
FROM filtered
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
            'summary': {'sum_royalties': 0, 'sum_total_revenue': 0, 'sum_spend': 0,
                        'sum_ad_sales': 0, 'sum_clicks': 0, 'sum_units': 0}
        })

    total             = int(rows[0]['_total'])
    sum_royalties     = float(rows[0]['_sum_royalties'] or 0)
    sum_total_revenue = float(rows[0]['_sum_total_revenue'] or 0)
    sum_spend         = float(rows[0]['_sum_spend'] or 0)
    sum_ad_sales      = float(rows[0]['_sum_ad_sales'] or 0)
    sum_clicks        = int(rows[0]['_sum_clicks'] or 0)
    sum_units         = int(rows[0]['_sum_units'] or 0)

    skip = {'_total', '_sum_royalties', '_sum_total_revenue', '_sum_spend',
            '_sum_ad_sales', '_sum_clicks', '_sum_units'}
    result_rows = [{k: _cvt(v) for k, v in dict(r).items() if k not in skip} for r in rows]

    return jsonify({
        'rows': result_rows, 'total': total, 'page': page, 'per_page': per_page,
        'summary': {
            'sum_royalties': sum_royalties,
            'sum_total_revenue': sum_total_revenue,
            'sum_spend': sum_spend,
            'sum_ad_sales': sum_ad_sales,
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
    period       = args.get('period', 'week')  # 'week' or 'month'
    trunc_unit   = 'MONTH' if period == 'month' else 'WEEK(MONDAY)'

    if not asin:
        return jsonify({'weeks': []})

    safe_mkt  = marketplace.replace("'", "''")
    if account_type == 'KDP':
        earn_mkt = KDP_DOMAIN_MAP.get(marketplace, f'Amazon.{safe_mkt.lower()}').replace("'", "''")
    else:
        earn_mkt = MKT_DOMAIN_MAP.get(marketplace, safe_mkt).replace("'", "''")
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
    DATE_TRUNC(e.{earn_date_field}, {trunc_unit}) AS week,
    SUM(e.{earn_units_field}) AS total_units,
    ROUND(SUM(e.{earn_royalty_field}), 2) AS royalties
  FROM `{earn_table}` e
  WHERE e.{earn_asin_field} = '{safe_asin}' AND e.marketplace = '{earn_mkt}' {earn_date_cond}
  GROUP BY 1
),
ads_weekly AS (
  SELECT
    DATE_TRUNC(a.date, {trunc_unit}) AS week,
    SUM(a.clicks) AS clicks,
    ROUND(SUM(a.cost), 2) AS ad_spend,
    SUM(a.purchases_14d) AS ad_units,
    ROUND(SUM(a.sales_14d), 2) AS ad_sales
  FROM `{asin_table}` a
  WHERE a.advertised_asin = '{safe_asin}' AND a.marketplace = '{safe_mkt}' {ads_date_cond}
  GROUP BY 1
)
SELECT
  COALESCE(e.week, a.week) AS week,
  COALESCE(e.total_units, 0) AS total_units,
  COALESCE(a.ad_units, 0) AS ad_units,
  GREATEST(COALESCE(e.total_units, 0) - COALESCE(a.ad_units, 0), 0) AS organic_units,
  COALESCE(e.royalties, 0) AS royalties,
  COALESCE(a.clicks, 0) AS clicks,
  COALESCE(a.ad_spend, 0) AS ad_spend,
  COALESCE(a.ad_sales, 0) AS ad_sales
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
    ROUND(SUM(a.sales_14d), 2) AS ad_sales
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
  agg.ad_sales,
  CASE WHEN agg.ad_sales > 0
       THEN ROUND(agg.ad_spend / agg.ad_sales * 100, 1)
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
