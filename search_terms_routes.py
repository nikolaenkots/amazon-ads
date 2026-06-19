from bq_client import get_client
import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory

search_terms_bp = Blueprint('search_terms', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

OP_MAP = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'eq': '='}
NUM_FIELDS = ['impressions', 'clicks', 'cost', 'ctr', 'sales_14d', 'purchases_14d', 'acos']

ALLOWED_SORT = {
    'search_term', 'keyword', 'keyword_type', 'match_type',
    'ad_group_name', 'campaign_name', 'impressions', 'clicks',
    'cost', 'ctr', 'sales_14d', 'purchases_14d', 'acos',
}

KW_TYPES_MANUAL  = "('BROAD','PHRASE','EXACT')"
KW_TYPES_AUTO    = "('TARGETING_EXPRESSION_PREDEFINED')"
KW_TYPES_PRODUCT = "('TARGETING_EXPRESSION')"
KW_TYPES_ALL     = "('BROAD','PHRASE','EXACT','TARGETING_EXPRESSION_PREDEFINED','TARGETING_EXPRESSION')"


def _cvt(v):
    return float(v) if isinstance(v, decimal.Decimal) else v


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


@search_terms_bp.route('/search-terms')
def search_terms_page():
    return send_from_directory(BASE_DIR, 'search_terms.html')


@search_terms_bp.route('/search-terms/data')
def search_terms_data():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    suffix       = account_type.lower()
    date_from    = args.get('date_from', '')
    date_to      = args.get('date_to', '')
    marketplace  = args.get('marketplace', 'US').upper()
    portfolio_ids_raw = args.get('portfolio_ids', '')
    name_filter  = args.get('name', '').strip()
    initiator_type = args.get('initiator_type', '')   # keyword / auto / product / ''
    match_type_filter = args.get('match_type_filter', '').upper()
    query_type   = args.get('query_type', '')          # text / product / ''
    state_filter = args.get('state_filter', '')
    sort_by      = args.get('sort_by', 'clicks')
    sort_dir     = 'DESC' if args.get('sort_dir', 'desc').lower() == 'desc' else 'ASC'
    page         = max(1, int(args.get('page', 1)))
    per_page     = min(200, max(10, int(args.get('per_page', 50))))
    offset       = (page - 1) * per_page

    if sort_by not in ALLOWED_SORT:
        sort_by = 'clicks'

    camp_state_filter = args.get('camp_state_filter', '')   # ENABLED / PAUSED / ''

    st_table   = f"{PROJECT_ID}.{DATASET}.search_terms_{suffix}"
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    pf_table   = f"{PROJECT_ID}.{DATASET}.portfolio_labels"

    # Date filter
    date_parts = []
    if date_from:
        date_parts.append(f"s.date >= '{date_from}'")
    if date_to:
        date_parts.append(f"s.date <= '{date_to}'")
    date_where = ('AND ' + ' AND '.join(date_parts)) if date_parts else ''

    # Marketplace
    safe_mkt = marketplace.replace("'", "''")
    mkt_cond = f"AND s.marketplace = '{safe_mkt}'"

    # Initiator type (keyword_type of the initiating target)
    if initiator_type == 'keyword':
        type_cond = f"AND s.keyword_type IN {KW_TYPES_MANUAL}"
    elif initiator_type == 'auto':
        type_cond = f"AND s.keyword_type IN {KW_TYPES_AUTO}"
    elif initiator_type == 'product':
        type_cond = f"AND s.keyword_type IN {KW_TYPES_PRODUCT}"
    else:
        type_cond = f"AND s.keyword_type IN {KW_TYPES_ALL}"

    # Match type filter
    if match_type_filter in ('BROAD', 'PHRASE', 'EXACT'):
        mt_cond = f"AND s.match_type = '{match_type_filter}'"
    elif match_type_filter == 'AUTO':
        mt_cond = "AND s.match_type IS NULL"
    else:
        mt_cond = ''

    # Query type (text vs ASIN search term)
    if query_type == 'text':
        qt_cond = "AND NOT REGEXP_CONTAINS(UPPER(st.search_term), r'^B[0-9A-Z]{9}$')"
    elif query_type == 'product':
        qt_cond = "AND REGEXP_CONTAINS(UPPER(st.search_term), r'^B[0-9A-Z]{9}$')"
    else:
        qt_cond = ''

    # Portfolio filter
    portfolio_cond = ''
    if portfolio_ids_raw:
        pids = [p.strip() for p in portfolio_ids_raw.split(',') if p.strip()]
        if pids:
            quoted = ','.join(f"'{p}'" for p in pids)
            portfolio_cond = f"AND c.portfolio_id IN ({quoted})"

    # Name search (on search_term OR keyword/targeting initiator)
    name_cond = ''
    if name_filter:
        sn = name_filter.replace("'", "''")
        name_cond = f"AND (LOWER(st.search_term) LIKE LOWER('%{sn}%') OR LOWER(COALESCE(st.keyword, st.targeting, '')) LIKE LOWER('%{sn}%'))"

    # Campaign state (ad_group state filter)
    state_cond = ''
    if state_filter:
        sf = state_filter.replace("'", "''")
        state_cond = f"AND g.ad_group_state = '{sf}'"

    # Campaign activity filter
    camp_state_cond = ''
    if camp_state_filter:
        csf = camp_state_filter.replace("'", "''")
        camp_state_cond = f"AND c.campaign_state = '{csf}'"

    num_where = _build_num_where(args)

    sql = f"""
    WITH st AS (
        SELECT
            s.ad_group_id, s.campaign_id, s.keyword_id, s.marketplace,
            s.keyword, s.targeting, s.keyword_type, s.match_type, s.search_term,
            SUM(s.impressions)        AS impressions,
            SUM(s.clicks)             AS clicks,
            ROUND(SUM(s.cost), 2)     AS cost,
            SUM(s.purchases_14d)      AS purchases_14d,
            ROUND(SUM(s.sales_14d),2) AS sales_14d
        FROM `{st_table}` s
        WHERE 1=1 {date_where} {mkt_cond} {type_cond} {mt_cond}
        GROUP BY s.ad_group_id, s.campaign_id, s.keyword_id, s.marketplace,
                 s.keyword, s.targeting, s.keyword_type, s.match_type, s.search_term
    ),
    c_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
        FROM `{camp_table}` WHERE entity_type = 'campaign'
    ),
    g_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
        FROM `{camp_table}` WHERE entity_type = 'ad_group'
    ),
    c AS (SELECT * FROM c_raw WHERE rn = 1),
    g AS (
        SELECT ad_group_id, ad_group_name, campaign_id, marketplace, ad_group_state
        FROM g_raw WHERE rn = 1
    ),
    base AS (
        SELECT
            st.search_term, st.keyword, st.targeting, st.keyword_type, st.match_type,
            st.keyword_id, st.ad_group_id, st.campaign_id, st.marketplace,
            st.impressions, st.clicks, st.cost, st.purchases_14d, st.sales_14d,
            CASE WHEN st.impressions > 0 THEN ROUND(st.clicks / st.impressions * 100, 3) ELSE NULL END AS ctr,
            CASE WHEN st.sales_14d > 0   THEN ROUND(st.cost   / st.sales_14d   * 100, 1) ELSE NULL END AS acos,
            g.ad_group_name, g.ad_group_state,
            c.campaign_name, c.campaign_state,
            COALESCE(pl.portfolio_name, c.portfolio_name) AS portfolio_name,
            c.portfolio_id
        FROM st
        LEFT JOIN c  ON c.campaign_id  = st.campaign_id  AND c.marketplace = st.marketplace
        LEFT JOIN g  ON g.ad_group_id  = st.ad_group_id  AND g.marketplace = st.marketplace
        LEFT JOIN `{pf_table}` pl
            ON pl.portfolio_id  = c.portfolio_id
            AND pl.marketplace  = c.marketplace
            AND pl.account_type = '{account_type}'
        WHERE c.campaign_id IS NOT NULL {qt_cond} {name_cond} {state_cond} {camp_state_cond} {portfolio_cond}
    ),
    filtered AS (SELECT * FROM base {num_where})
    SELECT *,
        COUNT(*) OVER()                     AS _total,
        SUM(impressions) OVER()             AS _sum_impressions,
        SUM(clicks) OVER()                  AS _sum_clicks,
        ROUND(SUM(cost) OVER(), 2)          AS _sum_cost,
        ROUND(SUM(sales_14d) OVER(), 2)     AS _sum_sales,
        SUM(purchases_14d) OVER()           AS _sum_purchases
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
            'summary': {'total_count': 0, 'sum_impressions': 0, 'sum_clicks': 0,
                        'sum_cost': 0, 'sum_sales': 0, 'sum_purchases': 0}
        })

    total         = int(rows[0]['_total'])
    sum_imp       = int(rows[0]['_sum_impressions'] or 0)
    sum_clicks    = int(rows[0]['_sum_clicks'] or 0)
    sum_cost      = float(rows[0]['_sum_cost'] or 0)
    sum_sales     = float(rows[0]['_sum_sales'] or 0)
    sum_purchases = int(rows[0]['_sum_purchases'] or 0)

    skip = {'_total', '_sum_impressions', '_sum_clicks', '_sum_cost', '_sum_sales', '_sum_purchases'}
    result_rows = [{k: _cvt(v) for k, v in dict(r).items() if k not in skip} for r in rows]

    return jsonify({
        'rows': result_rows,
        'total': total,
        'page': page,
        'per_page': per_page,
        'summary': {
            'total_count': total,
            'sum_impressions': sum_imp,
            'sum_clicks': sum_clicks,
            'sum_cost': sum_cost,
            'sum_sales': sum_sales,
            'sum_purchases': sum_purchases,
        }
    })


@search_terms_bp.route('/search-terms/groups-for-asin')
def groups_for_asin():
    """Find ad groups that share the same ASIN as the given ad_group_id."""
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    suffix       = account_type.lower()
    marketplace  = args.get('marketplace', 'US').upper()
    ad_group_id  = args.get('ad_group_id', '').strip()

    if not ad_group_id:
        return jsonify({'groups': [], 'asin': ''})

    camp_table  = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    asin_table  = f"{PROJECT_ID}.{DATASET}.asin_stats_{suffix}"
    safe_mkt    = marketplace.replace("'", "''")
    safe_agid   = ad_group_id.replace("'", "''")

    sql = f"""
    WITH source_asins AS (
        -- Find ASINs advertised in the source group
        SELECT DISTINCT advertised_asin
        FROM `{asin_table}`
        WHERE ad_group_id = '{safe_agid}' AND marketplace = '{safe_mkt}'
        LIMIT 5
    ),
    ag_ids AS (
        -- Find all groups advertising those ASINs
        SELECT DISTINCT s.ad_group_id
        FROM `{asin_table}` s
        JOIN source_asins sa ON sa.advertised_asin = s.advertised_asin
        WHERE s.marketplace = '{safe_mkt}'
    ),
    g_raw AS (
        SELECT ad_group_id, ad_group_name, campaign_id, ad_group_state, marketplace,
               ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
        FROM `{camp_table}` WHERE entity_type = 'ad_group'
    ),
    c_raw AS (
        SELECT campaign_id, campaign_name, campaign_state, targeting_type, marketplace,
               ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
        FROM `{camp_table}` WHERE entity_type = 'campaign'
    ),
    g AS (SELECT * FROM g_raw WHERE rn = 1),
    c AS (SELECT * FROM c_raw WHERE rn = 1)
    SELECT g.ad_group_id, g.ad_group_name, g.ad_group_state,
           c.campaign_id, c.campaign_name, c.campaign_state, c.targeting_type,
           g.marketplace,
           (SELECT STRING_AGG(DISTINCT advertised_asin ORDER BY advertised_asin LIMIT 3)
            FROM `{asin_table}` WHERE ad_group_id = '{safe_agid}' AND marketplace = '{safe_mkt}') AS source_asins
    FROM ag_ids
    JOIN g ON g.ad_group_id = ag_ids.ad_group_id AND g.marketplace = '{safe_mkt}'
    LEFT JOIN c ON c.campaign_id = g.campaign_id AND c.marketplace = g.marketplace
    WHERE c.campaign_id IS NOT NULL
    ORDER BY
        CASE WHEN c.campaign_state = 'ENABLED' AND g.ad_group_state = 'ENABLED' THEN 0 ELSE 1 END,
        c.campaign_name, g.ad_group_name
    LIMIT 300
    """
    try:
        client = get_client()
        rows = list(client.query(sql).result())
        groups = [dict(r) for r in rows]
        asin = groups[0]['source_asins'] if groups else ''
        # remove source_asins field from each row
        for g in groups:
            g.pop('source_asins', None)
        return jsonify({'groups': groups, 'asin': asin})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
