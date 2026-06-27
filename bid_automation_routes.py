"""
bid_automation_routes.py — Blueprint for bid automation page.
/automation/bid-automation

Endpoints:
  GET  /automation/bid-automation          — HTML page
  GET  /automation/bid-automation/keywords — keyword/target list with stats
  GET  /automation/bid-automation/search-terms — search terms for a keyword/target
  GET  /automation/bid-automation/bid-history  — bid change history for entity
"""

import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory
from bq_client import get_client

try:
    from google.cloud import bigquery
    _QJC = bigquery.QueryJobConfig(job_timeout_ms=45000)
except Exception:
    _QJC = None

bid_automation_bp = Blueprint('bid_automation', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


def _cvt(v):
    return float(v) if isinstance(v, decimal.Decimal) else v


def _suffix(account_type):
    return 'kdp' if account_type == 'KDP' else 'merch'


def _safe(s):
    return str(s).replace("'", "''")


@bid_automation_bp.route('/automation/bid-automation')
def bid_automation_page():
    return send_from_directory(BASE_DIR, 'bid_automation.html')


@bid_automation_bp.route('/automation/bid-automation/keywords')
def ba_keywords():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    marketplace  = args.get('marketplace', 'US').upper()
    date_from    = args.get('date_from', '').strip()
    date_to      = args.get('date_to', '').strip()
    days         = max(1, int(args.get('days', 30)))
    portfolio_ids_raw = args.get('portfolio_ids', '')
    campaign_id_raw   = args.get('campaign_id', '')
    ad_group_id_raw   = args.get('ad_group_id', '')
    targeting_type    = args.get('targeting_type', '')  # MANUAL | AUTO | ''
    name_filter       = args.get('name_filter', '').strip()
    state_filter      = args.get('state_filter', '')    # ENABLED | PAUSED | ''
    sort_by           = args.get('sort_by', 'clicks')
    sort_dir          = args.get('sort_dir', 'DESC').upper()
    page              = max(1, int(args.get('page', 1)))
    per_page          = min(200, max(1, int(args.get('per_page', 100))))

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({'error': 'Неверный account_type'}), 400

    suffix     = _suffix(account_type)
    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    stat_table = f"`{PROJECT_ID}.{DATASET}.targets_stats_{suffix}`"
    clog_table = f"`{PROJECT_ID}.{DATASET}.change_log_{suffix}`"
    pf_table   = f"`{PROJECT_ID}.{DATASET}.portfolio_labels`"

    safe_mkt = _safe(marketplace)

    # Date filter for stats
    if date_from and date_to:
        date_cond = f"s.date >= '{_safe(date_from)}' AND s.date <= '{_safe(date_to)}'"
    else:
        date_cond = f"s.date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)"

    # Campaign-level filters
    camp_conds = [
        f"marketplace = '{safe_mkt}'",
        "entity_type IN ('keyword', 'product_targeting')",
    ]
    if portfolio_ids_raw:
        pids = [p.strip() for p in portfolio_ids_raw.split(',') if p.strip()]
        if pids:
            quoted = ','.join(f"'{_safe(p)}'" for p in pids)
            camp_conds.append(f"portfolio_id IN ({quoted})")
    if campaign_id_raw:
        camp_conds.append(f"campaign_id = '{_safe(campaign_id_raw)}'")
    if ad_group_id_raw:
        camp_conds.append(f"ad_group_id = '{_safe(ad_group_id_raw)}'")

    kw_extra_conds = []
    if state_filter in ('ENABLED', 'PAUSED'):
        kw_extra_conds.append(f"keyword_state = '{state_filter}'")
    if name_filter:
        sf = _safe(name_filter)
        kw_extra_conds.append(
            f"LOWER(keyword_text) LIKE LOWER('%{sf}%')"
        )
    kw_extra = ('AND ' + ' AND '.join(kw_extra_conds)) if kw_extra_conds else ''

    camp_extra_conds = []
    if targeting_type in ('MANUAL', 'AUTO'):
        camp_extra_conds.append(f"targeting_type = '{targeting_type}'")
    camp_filter = ('AND ' + ' AND '.join(camp_extra_conds)) if camp_extra_conds else ''

    allowed_sort = {
        'clicks', 'cost', 'acos', 'sales', 'bid', 'last_change_date',
        'impressions', 'purchases', 'keyword_text'
    }
    if sort_by not in allowed_sort:
        sort_by = 'clicks'
    if sort_dir not in ('ASC', 'DESC'):
        sort_dir = 'DESC'

    offset = (page - 1) * per_page

    sql = f"""
    WITH kw_raw AS (
        SELECT
            COALESCE(keyword_id, target_id)  AS entity_id,
            CASE WHEN entity_type = 'keyword' THEN 'keyword' ELSE 'target' END AS entity_type,
            keyword_id,
            target_id,
            CASE WHEN entity_type = 'keyword' THEN keyword_text ELSE targeting_expression END AS keyword_text,
            targeting_expression,
            match_type,
            CASE WHEN entity_type = 'keyword' THEN keyword_state ELSE target_state END AS keyword_state,
            SAFE_CAST(CASE WHEN entity_type = 'keyword' THEN keyword_bid ELSE target_bid END AS FLOAT64) AS bid,
            ad_group_id,
            campaign_id,
            marketplace,
            ROW_NUMBER() OVER (
                PARTITION BY
                    COALESCE(keyword_id, target_id),
                    marketplace
                ORDER BY synced_at DESC
            ) AS rn
        FROM {camp_table}
        WHERE {' AND '.join(camp_conds)}
    ),
    kw AS (
        SELECT
            entity_id,
            entity_type,
            keyword_id,
            target_id,
            keyword_text,
            targeting_expression AS targeting,
            match_type,
            CAST(NULL AS STRING) AS keyword_type,
            keyword_state,
            bid,
            ad_group_id,
            campaign_id,
            marketplace
        FROM kw_raw
        WHERE rn = 1
        {kw_extra}
    ),
    c_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table}
        WHERE entity_type = 'campaign' AND marketplace = '{safe_mkt}' {camp_filter}
    ),
    c AS (SELECT * FROM c_raw WHERE rn = 1),
    g_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table}
        WHERE entity_type = 'ad_group' AND marketplace = '{safe_mkt}'
    ),
    g AS (SELECT * FROM g_raw WHERE rn = 1),
    stats AS (
        SELECT
            s.keyword_id,
            SUM(s.impressions)         AS impressions,
            SUM(s.clicks)              AS clicks,
            ROUND(SUM(s.cost), 2)      AS cost,
            ROUND(SUM(s.sales_14d), 2) AS sales,
            SUM(s.purchases_14d)       AS purchases
        FROM {stat_table} s
        WHERE s.marketplace = '{safe_mkt}'
          AND {date_cond}
        GROUP BY s.keyword_id
    ),
    -- last bid change from change_log
    last_change AS (
        SELECT
            entity_id,
            MAX(sent_at)  AS last_change_date
        FROM {clog_table}
        WHERE field_name = 'bid'
          AND result = 'SUCCESS'
          AND entity_type IN ('keyword', 'target')
        GROUP BY entity_id
    ),
    prev_bid AS (
        SELECT
            cl.entity_id,
            ANY_VALUE(cl.old_value)  AS prev_bid
        FROM {clog_table} cl
        INNER JOIN last_change lc
            ON lc.entity_id = cl.entity_id AND lc.last_change_date = cl.sent_at
        WHERE cl.field_name = 'bid'
          AND cl.result = 'SUCCESS'
        GROUP BY cl.entity_id
    ),
    base AS (
        SELECT
            kw.entity_id,
            kw.entity_type,
            kw.keyword_id,
            kw.target_id,
            COALESCE(kw.keyword_text, kw.targeting) AS keyword_text,
            kw.targeting,
            kw.match_type,
            kw.keyword_type,
            kw.keyword_state,
            kw.bid,
            kw.ad_group_id,
            kw.campaign_id,
            kw.marketplace,
            c.campaign_name,
            c.campaign_state,
            c.targeting_type,
            COALESCE(pl.portfolio_name, c.portfolio_name) AS portfolio_name,
            c.portfolio_id,
            g.ad_group_name,
            g.ad_group_state,
            COALESCE(st.impressions, 0)  AS impressions,
            COALESCE(st.clicks, 0)       AS clicks,
            COALESCE(st.cost, 0.0)       AS cost,
            COALESCE(st.sales, 0.0)      AS sales,
            COALESCE(st.purchases, 0)    AS purchases,
            CASE WHEN COALESCE(st.sales, 0) > 0
                 THEN ROUND(COALESCE(st.cost,0) / st.sales * 100, 1)
                 ELSE NULL END AS acos,
            lc.last_change_date,
            pv.prev_bid
        FROM kw
        INNER JOIN c  ON c.campaign_id  = kw.campaign_id  AND c.marketplace = kw.marketplace
        INNER JOIN g  ON g.ad_group_id  = kw.ad_group_id  AND g.marketplace = kw.marketplace
        LEFT JOIN {pf_table} pl
            ON pl.portfolio_id  = c.portfolio_id
            AND pl.marketplace  = c.marketplace
            AND pl.account_type = '{account_type}'
        LEFT JOIN stats  st ON st.keyword_id = kw.entity_id
        LEFT JOIN last_change lc ON lc.entity_id = kw.entity_id
        LEFT JOIN prev_bid    pv ON pv.entity_id = kw.entity_id
    )
    SELECT *,
        COUNT(*) OVER() AS _total
    FROM base
    ORDER BY {sort_by} {sort_dir} NULLS LAST
    LIMIT {per_page} OFFSET {offset}
    """

    try:
        client = get_client()
        kw_args = _QJC if _QJC else None
        rows = list(client.query(sql, job_config=kw_args).result())
        total = rows[0]['_total'] if rows else 0
        result = []
        for r in rows:
            result.append({
                'entity_id':      r['entity_id'],
                'entity_type':    r['entity_type'],
                'keyword_id':     r['keyword_id'],
                'target_id':      r['target_id'],
                'keyword_text':   r['keyword_text'],
                'targeting':      r['targeting'],
                'match_type':     r['match_type'],
                'keyword_type':   r['keyword_type'],
                'keyword_state':  r['keyword_state'],
                'bid':            _cvt(r['bid']),
                'ad_group_id':    r['ad_group_id'],
                'ad_group_name':  r['ad_group_name'],
                'ad_group_state': r['ad_group_state'],
                'campaign_id':    r['campaign_id'],
                'campaign_name':  r['campaign_name'],
                'campaign_state': r['campaign_state'],
                'targeting_type': r['targeting_type'],
                'portfolio_name': r['portfolio_name'],
                'impressions':    r['impressions'],
                'clicks':         r['clicks'],
                'cost':           _cvt(r['cost']),
                'sales':          _cvt(r['sales']),
                'purchases':      r['purchases'],
                'acos':           _cvt(r['acos']) if r['acos'] is not None else None,
                'last_change_date': r['last_change_date'].isoformat() if r['last_change_date'] else None,
                'prev_bid':       _cvt(r['prev_bid']) if r['prev_bid'] else None,
            })
        return jsonify({'rows': result, 'total': total, 'page': page, 'per_page': per_page})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bid_automation_bp.route('/automation/bid-automation/search-terms')
def ba_search_terms():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    marketplace  = args.get('marketplace', 'US').upper()
    keyword_id   = args.get('keyword_id', '').strip()
    date_from    = args.get('date_from', '').strip()
    date_to      = args.get('date_to', '').strip()
    days         = max(1, int(args.get('days', 30)))

    if not keyword_id:
        return jsonify({'error': 'keyword_id обязателен'}), 400

    suffix   = _suffix(account_type)
    st_table = f"`{PROJECT_ID}.{DATASET}.search_terms_{suffix}`"
    safe_mkt = _safe(marketplace)
    safe_kid = _safe(keyword_id)

    if date_from and date_to:
        date_cond = f"date >= '{_safe(date_from)}' AND date <= '{_safe(date_to)}'"
    else:
        date_cond = f"date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)"

    sql = f"""
    SELECT
        search_term,
        SUM(impressions)         AS impressions,
        SUM(clicks)              AS clicks,
        ROUND(SUM(cost), 2)      AS cost,
        ROUND(SUM(sales_14d), 2) AS sales,
        SUM(purchases_14d)       AS purchases,
        CASE WHEN SUM(sales_14d) > 0
             THEN ROUND(SUM(cost) / SUM(sales_14d) * 100, 1)
             ELSE NULL END AS acos
    FROM {st_table}
    WHERE marketplace = '{safe_mkt}'
      AND keyword_id  = '{safe_kid}'
      AND {date_cond}
    GROUP BY search_term
    ORDER BY clicks DESC
    LIMIT 200
    """

    try:
        client = get_client()
        rows = list(client.query(sql, job_config=_QJC).result())
        result = [{
            'search_term': r['search_term'],
            'impressions': r['impressions'],
            'clicks':      r['clicks'],
            'cost':        _cvt(r['cost']),
            'sales':       _cvt(r['sales']),
            'purchases':   r['purchases'],
            'acos':        _cvt(r['acos']) if r['acos'] is not None else None,
        } for r in rows]
        return jsonify({'rows': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bid_automation_bp.route('/automation/bid-automation/bid-history')
def ba_bid_history():
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    entity_id    = args.get('entity_id', '').strip()

    if not entity_id:
        return jsonify({'error': 'entity_id обязателен'}), 400

    suffix     = _suffix(account_type)
    clog_table = f"`{PROJECT_ID}.{DATASET}.change_log_{suffix}`"
    safe_eid   = _safe(entity_id)

    sql = f"""
    SELECT
        sent_at,
        old_value,
        new_value,
        result
    FROM {clog_table}
    WHERE entity_id  = '{safe_eid}'
      AND field_name = 'bid'
      AND result     = 'SUCCESS'
    ORDER BY sent_at DESC
    LIMIT 50
    """

    try:
        client = get_client()
        rows = list(client.query(sql, job_config=_QJC).result())
        result = [{
            'sent_at':   r['sent_at'].isoformat() if r['sent_at'] else None,
            'old_value': r['old_value'],
            'new_value': r['new_value'],
            'result':    r['result'],
            'note':      None,
        } for r in rows]
        return jsonify({'rows': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
