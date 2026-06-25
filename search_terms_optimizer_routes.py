from bq_client import get_client
import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory

st_optimizer_bp = Blueprint('st_optimizer', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


def _cvt(v):
    return float(v) if isinstance(v, decimal.Decimal) else v


def _suffix(account_type):
    return 'kdp' if account_type == 'KDP' else 'merch'


@st_optimizer_bp.route('/automation/search-terms')
def search_terms_optimizer_page():
    return send_from_directory(BASE_DIR, 'search_terms_optimizer.html')


def _date_where(args, alias='s'):
    """Возвращает SQL-условие диапазона дат.
    Если переданы date_from и date_to — используется явный период,
    иначе — последние N дней (days)."""
    date_from = args.get('date_from', '').strip()
    date_to   = args.get('date_to', '').strip()
    if date_from and date_to:
        df = date_from.replace("'", "''")
        dt = date_to.replace("'", "''")
        return f"{alias}.date >= '{df}' AND {alias}.date <= '{dt}'"
    days = max(1, int(args.get('days', 30)))
    return f"{alias}.date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)"


@st_optimizer_bp.route('/automation/search-terms/portfolios')
def st_portfolios():
    """Уникальные портфолио с актуальными именами из portfolio_labels."""
    account_type = request.args.get('account_type', 'MERCH').upper()
    marketplace  = request.args.get('marketplace', '').upper()
    if account_type not in ('MERCH', 'KDP'):
        return jsonify({'portfolios': []})

    suffix     = _suffix(account_type)
    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    pf_table   = f"`{PROJECT_ID}.{DATASET}.portfolio_labels`"

    conds = ["c.entity_type = 'campaign'", "c.portfolio_id IS NOT NULL", "c.portfolio_id != ''"]
    if marketplace:
        conds.append(f"c.marketplace = '{marketplace.replace(chr(39), chr(39)*2)}'")
    where = 'WHERE ' + ' AND '.join(conds)

    sql = f"""
    SELECT DISTINCT
        c.portfolio_id,
        COALESCE(pl.portfolio_name, c.portfolio_name, c.portfolio_id) AS portfolio_name
    FROM {camp_table} c
    LEFT JOIN {pf_table} pl
        ON  pl.portfolio_id  = c.portfolio_id
        AND pl.marketplace   = c.marketplace
        AND pl.account_type  = '{account_type}'
    {where}
    ORDER BY portfolio_name
    """
    try:
        client = get_client()
        rows = [{'id': r['portfolio_id'], 'name': r['portfolio_name']}
                for r in client.query(sql).result()]
        return jsonify({'portfolios': rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@st_optimizer_bp.route('/automation/search-terms/negatives-candidates')
def negatives_candidates():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    suffix       = _suffix(account_type)
    marketplace  = args.get('marketplace', 'US').upper()
    portfolio_ids_raw = args.get('portfolio_ids', '')
    min_clicks   = max(0, int(args.get('min_clicks', 10)))

    st_table   = f"`{PROJECT_ID}.{DATASET}.search_terms_{suffix}`"
    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    pf_table   = f"`{PROJECT_ID}.{DATASET}.portfolio_labels`"

    safe_mkt   = marketplace.replace("'", "''")
    date_where = _date_where(args, 's')

    portfolio_cond = ''
    if portfolio_ids_raw:
        pids = [p.strip() for p in portfolio_ids_raw.split(',') if p.strip()]
        if pids:
            quoted = ','.join(f"'{p}'" for p in pids)
            portfolio_cond = f"AND c.portfolio_id IN ({quoted})"

    sql = f"""
    WITH st AS (
        SELECT
            s.search_term, s.campaign_id, s.ad_group_id,
            s.keyword_type, s.match_type,
            SUM(s.impressions)        AS impressions,
            SUM(s.clicks)             AS clicks,
            ROUND(SUM(s.cost), 2)     AS cost,
            SUM(s.purchases_14d)      AS purchases_14d
        FROM {st_table} s
        WHERE s.marketplace = '{safe_mkt}'
          AND {date_where}
        GROUP BY s.search_term, s.campaign_id, s.ad_group_id, s.keyword_type, s.match_type
        HAVING SUM(s.clicks) >= {min_clicks} AND SUM(s.purchases_14d) = 0
    ),
    c_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table} WHERE entity_type = 'campaign'
    ),
    g_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table} WHERE entity_type = 'ad_group'
    ),
    c AS (SELECT * FROM c_raw WHERE rn = 1 AND marketplace = '{safe_mkt}'),
    g AS (SELECT ad_group_id, ad_group_name, campaign_id, marketplace FROM g_raw WHERE rn = 1 AND marketplace = '{safe_mkt}')
    SELECT
        st.search_term, st.clicks, st.cost, st.impressions,
        st.campaign_id, c.campaign_name,
        st.ad_group_id, g.ad_group_name,
        COALESCE(pl.portfolio_name, c.portfolio_name) AS portfolio_name,
        st.keyword_type, st.match_type
    FROM st
    LEFT JOIN c ON c.campaign_id = st.campaign_id
    LEFT JOIN g ON g.ad_group_id = st.ad_group_id
    LEFT JOIN `{PROJECT_ID}.{DATASET}.portfolio_labels` pl
        ON pl.portfolio_id = c.portfolio_id
        AND pl.marketplace = '{safe_mkt}'
        AND pl.account_type = '{account_type}'
    WHERE c.campaign_id IS NOT NULL
    {portfolio_cond}
    ORDER BY st.clicks DESC
    LIMIT 500
    """

    try:
        client = get_client()
        rows = list(client.query(sql).result())
        result = [{k: _cvt(v) for k, v in dict(r).items()} for r in rows]
        return jsonify({'rows': result, 'total': len(result)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@st_optimizer_bp.route('/automation/search-terms/existing-negatives')
def existing_negatives():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    suffix       = _suffix(account_type)
    marketplace  = args.get('marketplace', 'US').upper()
    portfolio_ids_raw = args.get('portfolio_ids', '')

    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    safe_mkt   = marketplace.replace("'", "''")

    portfolio_cond = ''
    if portfolio_ids_raw:
        pids = [p.strip() for p in portfolio_ids_raw.split(',') if p.strip()]
        if pids:
            quoted = ','.join(f"'{p}'" for p in pids)
            # filter by campaign portfolio via subquery
            portfolio_cond = f"""
            AND campaign_id IN (
                SELECT campaign_id FROM {camp_table}
                WHERE entity_type = 'campaign'
                  AND marketplace = '{safe_mkt}'
                  AND portfolio_id IN ({quoted})
            )"""

    sql = f"""
    SELECT DISTINCT keyword_text, match_type, campaign_id, ad_group_id
    FROM {camp_table}
    WHERE entity_type = 'negative_keyword'
      AND marketplace = '{safe_mkt}'
      AND keyword_text IS NOT NULL
      AND (keyword_state IS NULL OR keyword_state != 'ARCHIVED')
    {portfolio_cond}

    UNION ALL

    SELECT DISTINCT
        targeting_expression AS keyword_text,
        'NEGATIVE_PRODUCT' AS match_type,
        campaign_id, ad_group_id
    FROM {camp_table}
    WHERE entity_type = 'negative_product_targeting'
      AND marketplace = '{safe_mkt}'
      AND targeting_expression IS NOT NULL
      AND (target_state IS NULL OR target_state != 'ARCHIVED')
    {portfolio_cond}

    LIMIT 200000
    """

    try:
        client = get_client()
        rows = list(client.query(sql).result())
        result = [dict(r) for r in rows]
        return jsonify({'negatives': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@st_optimizer_bp.route('/automation/search-terms/keywords-candidates')
def keywords_candidates():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    suffix       = _suffix(account_type)
    marketplace  = args.get('marketplace', 'US').upper()
    portfolio_ids_raw = args.get('portfolio_ids', '')
    min_orders   = max(0, int(args.get('min_orders', 1)))

    st_table   = f"`{PROJECT_ID}.{DATASET}.search_terms_{suffix}`"
    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    pf_table   = f"`{PROJECT_ID}.{DATASET}.portfolio_labels`"

    safe_mkt   = marketplace.replace("'", "''")
    date_where = _date_where(args, 's')

    portfolio_cond = ''
    if portfolio_ids_raw:
        pids = [p.strip() for p in portfolio_ids_raw.split(',') if p.strip()]
        if pids:
            quoted = ','.join(f"'{p}'" for p in pids)
            portfolio_cond = f"AND c.portfolio_id IN ({quoted})"

    sql = f"""
    WITH st AS (
        SELECT
            s.search_term, s.campaign_id, s.ad_group_id,
            s.keyword_type, s.match_type,
            SUM(s.impressions)         AS impressions,
            SUM(s.clicks)              AS clicks,
            ROUND(SUM(s.cost), 2)      AS cost,
            SUM(s.purchases_14d)       AS orders,
            ROUND(SUM(s.sales_14d), 2) AS sales
        FROM {st_table} s
        WHERE s.marketplace = '{safe_mkt}'
          AND {date_where}
        GROUP BY s.search_term, s.campaign_id, s.ad_group_id, s.keyword_type, s.match_type
        HAVING SUM(s.purchases_14d) >= {min_orders}
    ),
    c_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table} WHERE entity_type = 'campaign'
    ),
    g_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table} WHERE entity_type = 'ad_group'
    ),
    c AS (SELECT * FROM c_raw WHERE rn = 1 AND marketplace = '{safe_mkt}'),
    g AS (SELECT ad_group_id, ad_group_name, campaign_id, marketplace FROM g_raw WHERE rn = 1 AND marketplace = '{safe_mkt}')
    SELECT
        st.search_term, st.clicks, st.cost, st.impressions,
        st.orders, st.sales,
        CASE WHEN st.sales > 0 THEN ROUND(st.cost / st.sales * 100, 1) ELSE NULL END AS acos,
        st.campaign_id, c.campaign_name,
        st.ad_group_id, g.ad_group_name,
        COALESCE(pl.portfolio_name, c.portfolio_name) AS portfolio_name,
        st.keyword_type, st.match_type
    FROM st
    LEFT JOIN c ON c.campaign_id = st.campaign_id
    LEFT JOIN g ON g.ad_group_id = st.ad_group_id
    LEFT JOIN `{PROJECT_ID}.{DATASET}.portfolio_labels` pl
        ON pl.portfolio_id = c.portfolio_id
        AND pl.marketplace = '{safe_mkt}'
        AND pl.account_type = '{account_type}'
    WHERE c.campaign_id IS NOT NULL
    {portfolio_cond}
    ORDER BY st.orders DESC
    LIMIT 500
    """

    try:
        client = get_client()
        rows = list(client.query(sql).result())
        result = [{k: _cvt(v) for k, v in dict(r).items()} for r in rows]
        return jsonify({'rows': result, 'total': len(result)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@st_optimizer_bp.route('/automation/search-terms/groups-for-asin')
def groups_for_asin():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    suffix       = _suffix(account_type)
    marketplace  = args.get('marketplace', 'US').upper()
    ad_group_id  = args.get('ad_group_id', '').strip()

    if not ad_group_id:
        return jsonify({'groups': [], 'asin': ''})

    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    asin_table = f"`{PROJECT_ID}.{DATASET}.asin_stats_{suffix}`"
    safe_mkt   = marketplace.replace("'", "''")
    safe_agid  = ad_group_id.replace("'", "''")

    sql = f"""
    WITH source_asins AS (
        SELECT DISTINCT advertised_asin
        FROM {asin_table}
        WHERE ad_group_id = '{safe_agid}' AND marketplace = '{safe_mkt}'
        LIMIT 5
    ),
    ag_ids AS (
        SELECT DISTINCT s.ad_group_id
        FROM {asin_table} s
        JOIN source_asins sa ON sa.advertised_asin = s.advertised_asin
        WHERE s.marketplace = '{safe_mkt}'
    ),
    g_raw AS (
        SELECT ad_group_id, ad_group_name, campaign_id, ad_group_state, marketplace,
               ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table} WHERE entity_type = 'ad_group'
    ),
    c_raw AS (
        SELECT campaign_id, campaign_name, campaign_state, targeting_type, marketplace,
               ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table} WHERE entity_type = 'campaign'
    ),
    g AS (SELECT * FROM g_raw WHERE rn = 1),
    c AS (SELECT * FROM c_raw WHERE rn = 1)
    SELECT g.ad_group_id, g.ad_group_name, g.ad_group_state,
           c.campaign_id, c.campaign_name, c.campaign_state, c.targeting_type,
           g.marketplace,
           (SELECT STRING_AGG(DISTINCT advertised_asin ORDER BY advertised_asin LIMIT 3)
            FROM {asin_table} WHERE ad_group_id = '{safe_agid}' AND marketplace = '{safe_mkt}') AS source_asins
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
        for grp in groups:
            grp.pop('source_asins', None)
        return jsonify({'groups': groups, 'asin': asin})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
