from bq_client import get_client
import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory

targets_bp = Blueprint('targets', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

OP_MAP = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'eq': '='}
NUM_FIELDS = ['impressions', 'clicks', 'cost', 'ctr', 'sales_14d', 'purchases_14d', 'acos',
              'bid', 'ad_group_default_bid']

ALLOWED_SORT_GROUPS = {
    'ad_group_name', 'campaign_name', 'portfolio_name', 'marketplace',
    'ad_group_state', 'campaign_state', 'ad_group_default_bid',
    'impressions', 'clicks', 'cost', 'ctr', 'sales_14d', 'purchases_14d', 'acos',
}
ALLOWED_SORT_TARGETS = {
    'kw_text', 'keyword_type', 'match_type', 'ad_group_name', 'campaign_name',
    'bid', 'target_state', 'impressions', 'clicks', 'cost', 'ctr',
    'sales_14d', 'purchases_14d', 'acos',
}

TYPE_FILTER_MAP = {
    'keyword': "('BROAD','PHRASE','EXACT')",
    'auto':    "('TARGETING_EXPRESSION_PREDEFINED')",
    'product': "('TARGETING_EXPRESSION')",
}
ALL_TYPES = "('BROAD','PHRASE','EXACT','TARGETING_EXPRESSION_PREDEFINED','TARGETING_EXPRESSION')"


def _cvt(v):
    return float(v) if isinstance(v, decimal.Decimal) else v


def _build_having(args):
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
    return parts


@targets_bp.route('/targets')
def targets_page():
    return send_from_directory(BASE_DIR, 'targets.html')


@targets_bp.route('/targets/data')
def targets_data():
    mode         = request.args.get('mode', 'groups')
    account_type = request.args.get('account_type', 'MERCH').upper()
    date_from    = request.args.get('date_from', '')
    date_to      = request.args.get('date_to', '')
    marketplace  = request.args.get('marketplace', '')
    portfolio_ids = request.args.get('portfolio_ids', '')
    name_filter  = request.args.get('name', '').strip()
    state_filter = request.args.get('state', '')
    camp_state   = request.args.get('campaign_state', '')
    target_type  = request.args.get('target_type', '')
    sort_by      = request.args.get('sort_by', 'clicks')
    sort_dir     = request.args.get('sort_dir', 'desc').upper()
    try:
        page     = max(1, int(request.args.get('page', 1)))
        per_page = min(100, max(1, int(request.args.get('per_page', 50))))
    except ValueError:
        page, per_page = 1, 50

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400
    if sort_dir not in ('ASC', 'DESC'):
        sort_dir = 'DESC'

    suffix     = account_type.lower()
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    stat_table = f"{PROJECT_ID}.{DATASET}.targets_stats_{suffix}"
    pf_table   = f"{PROJECT_ID}.{DATASET}.portfolio_labels"
    offset     = (page - 1) * per_page

    date_conds = []
    if date_from: date_conds.append(f"s.date >= '{date_from}'")
    if date_to:   date_conds.append(f"s.date <= '{date_to}'")
    stat_date = ('AND ' + ' AND '.join(date_conds)) if date_conds else ''

    group_tgt_type = request.args.get('group_targeting_type', '')

    group_state_filter = request.args.get('group_state_filter', '')

    camp_conds = []
    if marketplace:
        safe_mkt = marketplace.replace("'", "''")
        camp_conds.append(f"marketplace = '{safe_mkt}'")
    if portfolio_ids:
        ids = [i.strip() for i in portfolio_ids.split(',') if i.strip()]
        safe_ids = ','.join(f"'{i}'" for i in ids)
        camp_conds.append(f"portfolio_id IN ({safe_ids})")
    if camp_state:
        safe_cs = camp_state.replace("'", "''")
        camp_conds.append(f"campaign_state = '{safe_cs}'")
    if group_tgt_type and mode == 'groups':
        safe_gtt = group_tgt_type.replace("'", "''")
        camp_conds.append(f"targeting_type = '{safe_gtt}'")
    camp_extra = ('AND ' + ' AND '.join(camp_conds)) if camp_conds else ''

    having_parts = _build_having(request.args)
    num_where = ('WHERE ' + ' AND '.join(having_parts)) if having_parts else ''

    if mode == 'groups':
        if sort_by not in ALLOWED_SORT_GROUPS:
            sort_by = 'clicks'

        extra_conds = []
        if name_filter:
            s = name_filter.replace("'", "''")
            extra_conds.append(
                f"(LOWER(g.ad_group_name) LIKE LOWER('%{s}%') OR LOWER(c.campaign_name) LIKE LOWER('%{s}%'))"
            )
        if state_filter:
            sf = state_filter.replace("'", "''")
            extra_conds.append(f"g.ad_group_state = '{sf}'")
        base_extra = ('AND ' + ' AND '.join(extra_conds)) if extra_conds else ''

        sql = f"""
        WITH g_raw AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
            FROM `{camp_table}` WHERE entity_type = 'ad_group'
        ),
        c_raw AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
            FROM `{camp_table}` WHERE entity_type = 'campaign'
        ),
        g AS (SELECT * FROM g_raw WHERE rn = 1),
        c AS (
            SELECT * FROM c_raw
            WHERE rn = 1 {camp_extra}
        ),
        agg AS (
            SELECT s.ad_group_id, s.marketplace,
                SUM(s.impressions)   AS impressions,
                SUM(s.clicks)        AS clicks,
                ROUND(SUM(s.cost), 2)       AS cost,
                ROUND(SUM(s.sales_14d), 2)  AS sales_14d,
                SUM(s.purchases_14d) AS purchases_14d
            FROM `{stat_table}` s
            WHERE s.keyword_type IN {ALL_TYPES} {stat_date}
            GROUP BY s.ad_group_id, s.marketplace
        ),
        base AS (
            SELECT
                g.ad_group_id, g.ad_group_name,
                SAFE_CAST(g.ad_group_default_bid AS FLOAT64) AS ad_group_default_bid,
                g.ad_group_state,
                c.campaign_id, c.campaign_name,
                c.targeting_type, c.campaign_state,
                COALESCE(pl.portfolio_name, c.portfolio_name) AS portfolio_name,
                g.marketplace,
                COALESCE(agg.impressions,   0)   AS impressions,
                COALESCE(agg.clicks,        0)   AS clicks,
                COALESCE(agg.cost,          0.0) AS cost,
                COALESCE(agg.sales_14d,     0.0) AS sales_14d,
                COALESCE(agg.purchases_14d, 0)   AS purchases_14d,
                CASE WHEN COALESCE(agg.impressions,0) > 0
                     THEN ROUND(COALESCE(agg.clicks,0) / COALESCE(agg.impressions,0) * 100, 3)
                     ELSE NULL END AS ctr,
                CASE WHEN COALESCE(agg.sales_14d,0) > 0
                     THEN ROUND(COALESCE(agg.cost,0) / COALESCE(agg.sales_14d,0) * 100, 1)
                     ELSE NULL END AS acos
            FROM g
            INNER JOIN c ON c.campaign_id = g.campaign_id AND c.marketplace = g.marketplace
            LEFT JOIN agg ON agg.ad_group_id = g.ad_group_id AND agg.marketplace = g.marketplace
            LEFT JOIN `{pf_table}` pl
                ON pl.portfolio_id  = c.portfolio_id
                AND pl.marketplace  = c.marketplace
                AND pl.account_type = '{account_type}'
            WHERE 1=1 {base_extra}
        ),
        filtered AS (SELECT * FROM base {num_where})
        SELECT *,
            COUNT(*) OVER()                    AS _total,
            SUM(impressions) OVER()            AS _sum_impressions,
            SUM(clicks) OVER()                 AS _sum_clicks,
            ROUND(SUM(cost) OVER(), 2)         AS _sum_cost,
            ROUND(SUM(sales_14d) OVER(), 2)    AS _sum_sales,
            SUM(purchases_14d) OVER()          AS _sum_purchases
        FROM filtered
        ORDER BY {sort_by} {sort_dir} NULLS LAST
        LIMIT {per_page} OFFSET {offset}
        """

    else:
        if sort_by not in ALLOWED_SORT_TARGETS:
            sort_by = 'clicks'

        type_in = TYPE_FILTER_MAP.get(target_type, '') or ALL_TYPES
        type_cond = f"AND s.keyword_type IN {type_in}"

        extra_conds = []
        if name_filter:
            s2 = name_filter.replace("'", "''")
            extra_conds.append(
                f"(LOWER(COALESCE(agg.keyword, agg.targeting, '')) LIKE LOWER('%{s2}%'))"
            )
        if state_filter:
            sf = state_filter.replace("'", "''")
            extra_conds.append(f"kw.state = '{sf}'")
        if group_state_filter:
            gsf = group_state_filter.replace("'", "''")
            extra_conds.append(f"g.ad_group_state = '{gsf}'")
        base_extra = ('AND ' + ' AND '.join(extra_conds)) if extra_conds else ''

        sql = f"""
        WITH agg AS (
            SELECT
                s.keyword_id, s.keyword, s.targeting, s.keyword_type,
                s.ad_group_id, s.campaign_id, s.marketplace,
                SUM(s.impressions)   AS impressions,
                SUM(s.clicks)        AS clicks,
                ROUND(SUM(s.cost), 2)      AS cost,
                ROUND(SUM(s.sales_14d), 2) AS sales_14d,
                SUM(s.purchases_14d) AS purchases_14d
            FROM `{stat_table}` s
            WHERE 1=1 {type_cond} {stat_date}
            GROUP BY s.keyword_id, s.keyword, s.targeting, s.keyword_type,
                     s.ad_group_id, s.campaign_id, s.marketplace
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
        kw_raw AS (
            SELECT
                CASE WHEN entity_type = 'keyword'
                     THEN keyword_id ELSE target_id END AS stat_key,
                CASE WHEN entity_type = 'keyword'
                     THEN keyword_bid ELSE target_bid END AS bid_raw,
                CASE WHEN entity_type = 'keyword'
                     THEN keyword_state ELSE target_state END AS state,
                match_type, marketplace,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        CASE WHEN entity_type='keyword' THEN keyword_id ELSE target_id END,
                        marketplace
                    ORDER BY synced_at DESC
                ) rn
            FROM `{camp_table}`
            WHERE entity_type IN ('keyword','product_targeting')
        ),
        c  AS (SELECT * FROM c_raw WHERE rn = 1 {camp_extra}),
        g  AS (
            SELECT ad_group_id, ad_group_name, marketplace,
                   SAFE_CAST(ad_group_default_bid AS FLOAT64) AS ad_group_default_bid,
                   ad_group_state
            FROM g_raw WHERE rn = 1
        ),
        kw AS (
            SELECT stat_key, SAFE_CAST(bid_raw AS FLOAT64) AS bid, state, match_type, marketplace
            FROM kw_raw WHERE rn = 1
        ),
        base AS (
            SELECT
                agg.keyword_id,
                COALESCE(agg.keyword, agg.targeting) AS kw_text,
                agg.keyword, agg.targeting, agg.keyword_type,
                agg.ad_group_id, agg.campaign_id, agg.marketplace,
                agg.impressions, agg.clicks, agg.cost, agg.sales_14d, agg.purchases_14d,
                c.campaign_name, c.targeting_type, c.campaign_state,
                COALESCE(pl.portfolio_name, c.portfolio_name) AS portfolio_name,
                g.ad_group_name,
                g.ad_group_default_bid,
                g.ad_group_state AS group_state,
                kw.bid, kw.state AS target_state, kw.match_type,
                CASE WHEN agg.impressions > 0
                     THEN ROUND(agg.clicks / agg.impressions * 100, 3)
                     ELSE NULL END AS ctr,
                CASE WHEN agg.sales_14d > 0
                     THEN ROUND(agg.cost / agg.sales_14d * 100, 1)
                     ELSE NULL END AS acos
            FROM agg
            LEFT JOIN c  ON c.campaign_id  = agg.campaign_id  AND c.marketplace  = agg.marketplace
            LEFT JOIN g  ON g.ad_group_id  = agg.ad_group_id  AND g.marketplace  = agg.marketplace
            LEFT JOIN kw ON kw.stat_key    = agg.keyword_id   AND kw.marketplace = agg.marketplace
            LEFT JOIN `{pf_table}` pl
                ON pl.portfolio_id  = c.portfolio_id
                AND pl.marketplace  = c.marketplace
                AND pl.account_type = '{account_type}'
            WHERE c.campaign_id IS NOT NULL {base_extra}
        ),
        filtered AS (SELECT * FROM base {num_where})
        SELECT *,
            COUNT(*) OVER()                    AS _total,
            SUM(impressions) OVER()            AS _sum_impressions,
            SUM(clicks) OVER()                 AS _sum_clicks,
            ROUND(SUM(cost) OVER(), 2)         AS _sum_cost,
            ROUND(SUM(sales_14d) OVER(), 2)    AS _sum_sales,
            SUM(purchases_14d) OVER()          AS _sum_purchases
        FROM filtered
        ORDER BY {sort_by} {sort_dir} NULLS LAST
        LIMIT {per_page} OFFSET {offset}
        """

    try:
        client  = get_client()
        all_rows = list(client.query(sql).result())

        rows = []
        total = sum_impr = sum_clicks = sum_cost = sum_sales = sum_purch = 0

        for r in all_rows:
            d = {k: _cvt(v) for k, v in dict(r).items()}
            if not rows:
                total      = int(d.pop('_total') or 0)
                sum_impr   = float(d.pop('_sum_impressions') or 0)
                sum_clicks = float(d.pop('_sum_clicks') or 0)
                sum_cost   = float(d.pop('_sum_cost') or 0)
                sum_sales  = float(d.pop('_sum_sales') or 0)
                sum_purch  = float(d.pop('_sum_purchases') or 0)
            else:
                for k in ('_total','_sum_impressions','_sum_clicks','_sum_cost','_sum_sales','_sum_purchases'):
                    d.pop(k, None)
            rows.append(d)

        summary = {
            'total':       total,
            'impressions': int(sum_impr),
            'clicks':      int(sum_clicks),
            'cost':        round(sum_cost, 2),
            'sales_14d':   round(sum_sales, 2),
            'purchases':   int(sum_purch),
            'acos': round(sum_cost / sum_sales * 100, 1) if sum_sales > 0 else None,
            'ctr':  round(sum_clicks / sum_impr * 100, 3) if sum_impr > 0 else None,
        }

        return jsonify({'rows': rows, 'total': total, 'page': page, 'per_page': per_page, 'summary': summary})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@targets_bp.route('/targets/group')
def targets_group():
    ad_group_id  = request.args.get('ad_group_id', '')
    marketplace  = request.args.get('marketplace', '')
    account_type = request.args.get('account_type', 'MERCH').upper()
    date_from    = request.args.get('date_from', '')
    date_to      = request.args.get('date_to', '')

    if not ad_group_id or account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверные параметры"}), 400

    suffix     = account_type.lower()
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    stat_table = f"{PROJECT_ID}.{DATASET}.targets_stats_{suffix}"

    safe_gid = ad_group_id.replace("'", "''")
    safe_mkt = marketplace.replace("'", "''")
    mkt_cond = f"AND marketplace = '{safe_mkt}'" if marketplace else ''

    date_conds = []
    if date_from: date_conds.append(f"date >= '{date_from}'")
    if date_to:   date_conds.append(f"date <= '{date_to}'")
    date_where = ('AND ' + ' AND '.join(date_conds)) if date_conds else ''

    # Group info (default bid + campaign_id)
    sql_group_info = f"""
    SELECT ad_group_default_bid, campaign_id
    FROM `{camp_table}`
    WHERE entity_type = 'ad_group'
      AND ad_group_id = '{safe_gid}'
      {mkt_cond}
    ORDER BY synced_at DESC
    LIMIT 1
    """

    # Structure: all target/kw/neg entities for this group — most recent snapshot per id
    sql_struct = f"""
    SELECT entity_type,
           keyword_id, keyword_text, match_type, keyword_bid, keyword_state,
           target_id,  targeting_expression, target_bid, target_state
    FROM (
        SELECT entity_type,
               keyword_id, keyword_text, match_type, keyword_bid, keyword_state,
               target_id,  targeting_expression, target_bid, target_state,
               ROW_NUMBER() OVER (
                   PARTITION BY
                       CASE WHEN entity_type IN ('keyword','negative_keyword')
                            THEN keyword_id ELSE target_id END
                   ORDER BY synced_at DESC
               ) rn
        FROM `{camp_table}`
        WHERE entity_type IN ('keyword','product_targeting','negative_keyword','negative_product_targeting')
          AND ad_group_id = '{safe_gid}'
          {mkt_cond}
    )
    WHERE rn = 1
    """

    # Stats: aggregated by keyword_id for this group in the date range
    sql_stats = f"""
    SELECT
        keyword_id,
        ANY_VALUE(keyword_type) AS keyword_type,
        SUM(impressions)          AS impressions,
        SUM(clicks)               AS clicks,
        ROUND(SUM(cost), 2)       AS cost,
        ROUND(SUM(sales_14d), 2)  AS sales_14d,
        SUM(purchases_14d)        AS purchases_14d
    FROM `{stat_table}`
    WHERE ad_group_id = '{safe_gid}'
      {mkt_cond} {date_where}
    GROUP BY keyword_id
    """

    st_table = f"{PROJECT_ID}.{DATASET}.search_terms_{suffix}"
    sql_search_terms = f"""
    SELECT
        keyword_id, keyword_type, keyword, targeting, match_type, search_term,
        SUM(impressions)        AS impressions,
        SUM(clicks)             AS clicks,
        ROUND(SUM(cost), 2)     AS cost,
        SUM(purchases_14d)      AS purchases_14d,
        ROUND(SUM(sales_14d),2) AS sales_14d,
        CASE WHEN SUM(impressions)>0
             THEN ROUND(SUM(clicks)/SUM(impressions)*100,3) ELSE NULL END AS ctr,
        CASE WHEN SUM(sales_14d)>0
             THEN ROUND(SUM(cost)/SUM(sales_14d)*100,1) ELSE NULL END AS acos
    FROM `{st_table}`
    WHERE ad_group_id = '{safe_gid}'
      {mkt_cond} {date_where}
    GROUP BY keyword_id, keyword_type, keyword, targeting, match_type, search_term
    ORDER BY clicks DESC
    LIMIT 500
    """

    try:
        client = get_client()
        job_info  = client.query(sql_group_info)
        job_struct = client.query(sql_struct)
        job_stats = client.query(sql_stats)
        job_st    = client.query(sql_search_terms)

        # Group info
        group_rows = list(job_info.result())
        group_info = {}
        if group_rows:
            r = dict(group_rows[0])
            group_info = {
                'ad_group_default_bid': _cvt(r.get('ad_group_default_bid')),
                'campaign_id': r.get('campaign_id', ''),
            }

        # Stats index: keyword_id → stats dict
        stats_by_id = {}
        for r in job_stats.result():
            d = {k: _cvt(v) for k, v in dict(r).items()}
            kid = d.get('keyword_id') or ''
            impr  = d.get('impressions') or 0
            clks  = d.get('clicks') or 0
            cost  = d.get('cost') or 0
            sales = d.get('sales_14d') or 0
            d['ctr']  = round(clks/impr*100, 3) if impr > 0 else None
            d['acos'] = round(cost/sales*100, 1) if sales > 0 else None
            stats_by_id[kid] = d

        # Build targets and negatives from structure
        targets   = []
        negatives = []
        for r in job_struct.result():
            d = {k: _cvt(v) for k, v in dict(r).items()}
            et = d.get('entity_type', '')
            if et in ('negative_keyword', 'negative_product_targeting'):
                negatives.append(d)
            else:
                # keyword or product_targeting
                kid  = d.get('keyword_id') or d.get('target_id') or ''
                bid  = _cvt(d.get('keyword_bid') if et == 'keyword' else d.get('target_bid'))
                state = d.get('keyword_state') if et == 'keyword' else d.get('target_state')
                text  = d.get('keyword_text') if et == 'keyword' else d.get('targeting_expression')
                match = d.get('match_type') or ''
                st    = stats_by_id.get(kid, {})
                keyword_type = st.get('keyword_type') or (
                    (match.upper() if match else None) or
                    ('TARGETING_EXPRESSION' if et == 'product_targeting' else None)
                )
                targets.append({
                    'keyword_id':   kid,
                    'keyword':      text or '',
                    'keyword_type': keyword_type,
                    'match_type':   match,
                    'bid':          _cvt(bid),
                    'target_state': state,
                    'entity_type':  et,
                    'impressions':  st.get('impressions') or 0,
                    'clicks':       st.get('clicks') or 0,
                    'cost':         st.get('cost') or 0,
                    'sales_14d':    st.get('sales_14d') or 0,
                    'purchases_14d':st.get('purchases_14d') or 0,
                    'ctr':          st.get('ctr'),
                    'acos':         st.get('acos'),
                })
        targets.sort(key=lambda x: x.get('clicks', 0) or 0, reverse=True)

        search_terms = [{k: _cvt(v) for k, v in dict(r).items()} for r in job_st.result()]

        return jsonify({'group_info': group_info, 'targets': targets,
                        'negatives': negatives, 'search_terms': search_terms})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
