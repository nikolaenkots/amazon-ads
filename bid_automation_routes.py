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


RULES_TABLE = f"{PROJECT_ID}.{DATASET}.bid_rules"

# Default rule set returned when the table is empty (also used to seed the UI).
# low_impr / boost_pct / boost_max drive the "Разгон" (boost) action: a target
# below low_impr impressions gets its bid raised by boost_pct (capped at boost_max)
# to win more auctions. low_impr=0 disables boost for that rule.
DEFAULT_RULES = [
    {'name':'Новые',   'color':'#1a6fd4', 'scope':'global', 'portfolio_id':'', 'targeting_type':'ANY', 'use_age':True,  'age_from':0,  'age_to':10,   'high_acos':50, 'high_pct':10, 'low_acos':15, 'low_pct':10, 'min_bid':0.20, 'max_bid':5.00, 'min_clicks':0,  'no_sale_clicks':15, 'low_impr':100, 'boost_pct':25, 'boost_max':2.00, 'priority':100, 'enabled':True},
    {'name':'Средние', 'color':'#b07800', 'scope':'global', 'portfolio_id':'', 'targeting_type':'ANY', 'use_age':True,  'age_from':10, 'age_to':50,   'high_acos':40, 'high_pct':15, 'low_acos':12, 'low_pct':15, 'min_bid':0.20, 'max_bid':5.00, 'min_clicks':10, 'no_sale_clicks':25, 'low_impr':0,   'boost_pct':20, 'boost_max':2.00, 'priority':100, 'enabled':True},
    {'name':'Зрелые',  'color':'#1a8f5c', 'scope':'global', 'portfolio_id':'', 'targeting_type':'ANY', 'use_age':True,  'age_from':50, 'age_to':None, 'high_acos':35, 'high_pct':20, 'low_acos':10, 'low_pct':20, 'min_bid':0.20, 'max_bid':5.00, 'min_clicks':25, 'no_sale_clicks':30, 'low_impr':0,   'boost_pct':20, 'boost_max':2.00, 'priority':100, 'enabled':True},
]

_RULES_DDL = f"""
CREATE TABLE IF NOT EXISTS `{RULES_TABLE}` (
  account_type STRING, rule_id STRING, name STRING, color STRING,
  scope STRING, portfolio_id STRING, targeting_type STRING,
  use_age BOOL, age_from INT64, age_to INT64,
  high_acos FLOAT64, high_pct FLOAT64, low_acos FLOAT64, low_pct FLOAT64,
  min_bid FLOAT64, max_bid FLOAT64, min_clicks INT64, no_sale_clicks INT64,
  low_impr INT64, boost_pct FLOAT64, boost_max FLOAT64,
  priority INT64, enabled BOOL, updated_at TIMESTAMP
)
"""

# Columns added after the first release — kept in sync on existing tables.
_RULES_ALTERS = [
    f"ALTER TABLE `{RULES_TABLE}` ADD COLUMN IF NOT EXISTS low_impr INT64",
    f"ALTER TABLE `{RULES_TABLE}` ADD COLUMN IF NOT EXISTS boost_pct FLOAT64",
    f"ALTER TABLE `{RULES_TABLE}` ADD COLUMN IF NOT EXISTS boost_max FLOAT64",
]


_rules_table_ready = False

def _ensure_rules_table(client):
    # Run CREATE/ALTER at most once per process — BigQuery rate-limits table
    # metadata updates, so doing this on every request triggers 429s.
    global _rules_table_ready
    if _rules_table_ready:
        return
    client.query(_RULES_DDL).result()
    for stmt in _RULES_ALTERS:
        try:
            client.query(stmt).result()
        except Exception:
            pass
    _rules_table_ready = True


def _fnum(v, default=None):
    try:
        if v is None or v == '':
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _inum(v, default=None):
    f = _fnum(v, None)
    return int(f) if f is not None else default


@bid_automation_bp.route('/automation/bid-automation')
def bid_automation_page():
    return send_from_directory(BASE_DIR, 'bid_automation.html')


@bid_automation_bp.route('/automation/bid-automation/rules')
def ba_rules_get():
    account_type = request.args.get('account_type', 'MERCH').upper()
    if account_type not in ('MERCH', 'KDP'):
        return jsonify({'error': 'Неверный account_type'}), 400
    try:
        client = get_client()
        _ensure_rules_table(client)
        sql = f"""
        SELECT name, color, scope, portfolio_id, targeting_type, use_age,
               age_from, age_to, high_acos, high_pct, low_acos, low_pct,
               min_bid, max_bid, min_clicks, no_sale_clicks,
               low_impr, boost_pct, boost_max, priority, enabled
        FROM `{RULES_TABLE}`
        WHERE account_type = '{_safe(account_type)}'
        ORDER BY priority, scope DESC, name
        """
        rows = [{k: _cvt(v) for k, v in dict(r).items()} for r in client.query(sql, job_config=_QJC).result()]
        # Read-only: don't write on read (avoids hammering BigQuery's table-update
        # quota). When empty, just return defaults for display; they get persisted
        # only when the user clicks "Сохранить правила".
        if not rows:
            rows = [dict(d) for d in DEFAULT_RULES]
        return jsonify({'rules': rows, 'seeded': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _build_rule_rows(account_type, rules):
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc).isoformat()
    out = []
    for r in rules:
        tt = (r.get('targeting_type') or 'ANY').upper()
        if tt not in ('ANY', 'AUTO', 'MANUAL'):
            tt = 'ANY'
        scope = (r.get('scope') or 'global').lower()
        if scope not in ('global', 'portfolio'):
            scope = 'global'
        out.append({
            'account_type':  account_type,
            'rule_id':       str(uuid.uuid4()),
            'name':          str(r.get('name') or '')[:80],
            'color':         str(r.get('color') or '#888888')[:16],
            'scope':         scope,
            'portfolio_id':  str(r.get('portfolio_id') or ''),
            'targeting_type': tt,
            'use_age':       bool(r.get('use_age', True)),
            'age_from':      _inum(r.get('age_from'), 0),
            'age_to':        _inum(r.get('age_to'), None),
            'high_acos':     _fnum(r.get('high_acos'), 40.0),
            'high_pct':      _fnum(r.get('high_pct'), 15.0),
            'low_acos':      _fnum(r.get('low_acos'), 12.0),
            'low_pct':       _fnum(r.get('low_pct'), 15.0),
            'min_bid':       _fnum(r.get('min_bid'), 0.20),
            'max_bid':       _fnum(r.get('max_bid'), 5.00),
            'min_clicks':    _inum(r.get('min_clicks'), 0),
            'no_sale_clicks': _inum(r.get('no_sale_clicks'), 0),
            'low_impr':      _inum(r.get('low_impr'), 0),
            'boost_pct':     _fnum(r.get('boost_pct'), 20.0),
            'boost_max':     _fnum(r.get('boost_max'), 2.00),
            'priority':      _inum(r.get('priority'), 100),
            'enabled':       bool(r.get('enabled', True)),
            'updated_at':    now,
        })
    return out


def _write_rules(client, account_type, rules):
    out = _build_rule_rows(account_type, rules)
    _ensure_rules_table(client)
    client.query(
        f"DELETE FROM `{RULES_TABLE}` WHERE account_type = '{_safe(account_type)}'"
    ).result()
    if out:
        job = client.load_table_from_json(
            out, RULES_TABLE,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        )
        job.result()
    return len(out)


@bid_automation_bp.route('/automation/bid-automation/rules', methods=['POST'])
def ba_rules_save():
    data = request.get_json(silent=True) or {}
    account_type = (data.get('account_type') or 'MERCH').upper()
    rules = data.get('rules') or []
    if account_type not in ('MERCH', 'KDP'):
        return jsonify({'error': 'Неверный account_type'}), 400
    if len(rules) > 500:
        return jsonify({'error': 'Слишком много правил'}), 400
    try:
        client = get_client()
        n = _write_rules(client, account_type, rules)
        return jsonify({'success': True, 'saved': n})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
    camp_state_filter = args.get('camp_state', '')      # ENABLED | PAUSED | ''
    group_state_filter= args.get('group_state', '')     # ENABLED | PAUSED | ''
    from_last_change  = args.get('from_last_change', '') in ('1', 'true', 'yes')
    rec_filter        = args.get('rec_filter', '')       # raise|lower|pause|hold|new|changed
    sort_by           = args.get('sort_by', 'clicks')
    sort_dir          = args.get('sort_dir', 'DESC').upper()
    page              = max(1, int(args.get('page', 1)))
    per_page          = min(2000, max(1, int(args.get('per_page', 100))))

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({'error': 'Неверный account_type'}), 400

    suffix     = _suffix(account_type)
    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    stat_table = f"`{PROJECT_ID}.{DATASET}.targets_stats_{suffix}`"
    clog_table = f"`{PROJECT_ID}.{DATASET}.change_log_{suffix}`"
    asin_table = f"`{PROJECT_ID}.{DATASET}.asin_stats_{suffix}`"
    pf_table   = f"`{PROJECT_ID}.{DATASET}.portfolio_labels`"

    safe_mkt = _safe(marketplace)

    # Date window for stats.
    # fallback_start / upper_bound define the fixed window; when from_last_change
    # is on, each entity's stats start at its last bid change date (fallback to the
    # fixed window if it was never changed).
    if date_from and date_to:
        fallback_start = f"DATE('{_safe(date_from)}')"
        upper_bound    = f"AND s.date <= '{_safe(date_to)}'"
    else:
        fallback_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)"
        upper_bound    = ""

    if from_last_change:
        start_expr = f"COALESCE(DATE(lc.last_change_date), {fallback_start})"
    else:
        start_expr = fallback_start

    # Filters applied to the keyword/target rows themselves
    camp_conds = [
        f"marketplace = '{safe_mkt}'",
        "entity_type IN ('keyword', 'product_targeting')",
    ]
    if campaign_id_raw:
        camp_conds.append(f"campaign_id = '{_safe(campaign_id_raw)}'")
    if ad_group_id_raw:
        camp_conds.append(f"ad_group_id = '{_safe(ad_group_id_raw)}'")

    # Portfolio lives on the CAMPAIGN entity, not on keyword/target rows — apply
    # it to the campaign CTE (otherwise it filters out all keyword rows).
    portfolio_cond = ''
    if portfolio_ids_raw:
        pids = [p.strip() for p in portfolio_ids_raw.split(',') if p.strip()]
        if pids:
            quoted = ','.join(f"'{_safe(p)}'" for p in pids)
            portfolio_cond = f"AND portfolio_id IN ({quoted})"

    kw_extra_conds = []
    if state_filter in ('ENABLED', 'PAUSED'):
        kw_extra_conds.append(f"keyword_state = '{state_filter}'")
    if name_filter:
        sf = _safe(name_filter)
        kw_extra_conds.append(
            f"LOWER(keyword_text) LIKE LOWER('%{sf}%')"
        )
    kw_extra = ('AND ' + ' AND '.join(kw_extra_conds)) if kw_extra_conds else ''

    # Server-side recommendation filter
    rec_where = ''
    if rec_filter == 'changed':
        rec_where = 'WHERE ABS(new_bid - bid) >= 0.01'
    elif rec_filter in ('raise', 'lower', 'pause', 'hold', 'new', 'boost'):
        rec_where = f"WHERE action = '{rec_filter}'"

    camp_extra_conds = []
    if targeting_type in ('MANUAL', 'AUTO'):
        camp_extra_conds.append(f"targeting_type = '{targeting_type}'")
    if camp_state_filter in ('ENABLED', 'PAUSED'):
        camp_extra_conds.append(f"campaign_state = '{camp_state_filter}'")
    camp_filter = ('AND ' + ' AND '.join(camp_extra_conds)) if camp_extra_conds else ''

    group_filter = ''
    if group_state_filter in ('ENABLED', 'PAUSED'):
        group_filter = f"AND ad_group_state = '{group_state_filter}'"

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
        WHERE entity_type = 'campaign' AND marketplace = '{safe_mkt}' {camp_filter} {portfolio_cond}
    ),
    c AS (SELECT * FROM c_raw WHERE rn = 1),
    g_raw AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table}
        WHERE entity_type = 'ad_group' AND marketplace = '{safe_mkt}'
    ),
    g AS (SELECT * FROM g_raw WHERE rn = 1 {group_filter}),
    -- last bid change from change_log (defined before stats so the analysis
    -- window can start at each entity's last change date)
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
    stats AS (
        SELECT
            s.keyword_id,
            SUM(s.impressions)         AS impressions,
            SUM(s.clicks)              AS clicks,
            ROUND(SUM(s.cost), 2)      AS cost,
            ROUND(SUM(s.sales_14d), 2) AS sales,
            SUM(s.purchases_14d)       AS purchases
        FROM {stat_table} s
        LEFT JOIN last_change lc ON lc.entity_id = s.keyword_id
        WHERE s.marketplace = '{safe_mkt}'
          AND s.date >= {start_expr}
          {upper_bound}
        GROUP BY s.keyword_id
    ),
    -- Product "age" = total clicks on the ASIN across ALL campaigns (lifetime).
    -- Map ad group → its advertised ASIN(s), then sum each ASIN's all-campaign clicks.
    asin_clicks AS (
        SELECT advertised_asin, SUM(clicks) AS asin_total_clicks
        FROM {asin_table}
        WHERE marketplace = '{safe_mkt}'
          AND advertised_asin IS NOT NULL AND advertised_asin != ''
        GROUP BY advertised_asin
    ),
    ag_asin AS (
        SELECT DISTINCT ad_group_id, advertised_asin
        FROM {asin_table}
        WHERE marketplace = '{safe_mkt}'
          AND advertised_asin IS NOT NULL AND advertised_asin != ''
    ),
    grp_clicks AS (
        SELECT aa.ad_group_id, SUM(ac.asin_total_clicks) AS group_total_clicks
        FROM ag_asin aa
        JOIN asin_clicks ac ON ac.advertised_asin = aa.advertised_asin
        GROUP BY aa.ad_group_id
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
            COALESCE(kw.bid, SAFE_CAST(g.ad_group_default_bid AS FLOAT64)) AS bid,
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
            pv.prev_bid,
            COALESCE(gc.group_total_clicks, 0) AS group_total_clicks
        FROM kw
        INNER JOIN c  ON c.campaign_id  = kw.campaign_id  AND c.marketplace = kw.marketplace
        INNER JOIN g  ON g.ad_group_id  = kw.ad_group_id  AND g.marketplace = kw.marketplace
        LEFT JOIN grp_clicks gc ON gc.ad_group_id = kw.ad_group_id
        LEFT JOIN {pf_table} pl
            ON pl.portfolio_id  = c.portfolio_id
            AND pl.marketplace  = c.marketplace
            AND pl.account_type = '{account_type}'
        LEFT JOIN stats  st ON st.keyword_id = kw.entity_id
        LEFT JOIN last_change lc ON lc.entity_id = kw.entity_id
        LEFT JOIN prev_bid    pv ON pv.entity_id = kw.entity_id
    ),
    rules AS (
        SELECT scope, portfolio_id, targeting_type, use_age, age_from, age_to,
               high_acos, high_pct, low_acos, low_pct, min_bid, max_bid,
               min_clicks AS r_min_clicks, no_sale_clicks AS r_no_sale_clicks,
               low_impr, boost_pct, boost_max,
               priority, name AS rule_name, color AS rule_color
        FROM `{RULES_TABLE}`
        WHERE account_type = '{account_type}' AND enabled = TRUE
    ),
    matched AS (
        SELECT b.*,
            r.high_acos, r.high_pct, r.low_acos, r.low_pct, r.min_bid, r.max_bid,
            r.r_min_clicks, r.r_no_sale_clicks, r.low_impr, r.boost_pct, r.boost_max,
            r.rule_name, r.rule_color,
            CASE
                WHEN r.scope IS NULL THEN 999
                WHEN r.scope = 'portfolio' AND r.targeting_type <> 'ANY' THEN 1
                WHEN r.scope = 'portfolio' THEN 2
                WHEN r.targeting_type <> 'ANY' THEN 3
                ELSE 4
            END AS match_score,
            COALESCE(r.priority, 9999) AS rule_priority
        FROM base b
        LEFT JOIN rules r
            ON (r.scope = 'global' OR (r.scope = 'portfolio' AND r.portfolio_id = b.portfolio_id))
           AND (r.targeting_type = 'ANY' OR r.targeting_type = b.targeting_type)
           AND (r.use_age = FALSE OR (b.group_total_clicks >= r.age_from
                                      AND (r.age_to IS NULL OR b.group_total_clicks < r.age_to)))
    ),
    ranked AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY match_score, rule_priority) rn
        FROM matched
    ),
    acted AS (
        SELECT *,
            CASE
                WHEN rule_name IS NULL THEN 'hold'
                WHEN clicks < r_min_clicks THEN
                    -- not enough clicks: if also few impressions and bid below the
                    -- boost ceiling → ramp the bid up to win auctions; otherwise hold
                    CASE WHEN COALESCE(low_impr,0) > 0 AND impressions <= low_impr
                              AND bid < boost_max THEN 'boost'
                         ELSE 'hold' END
                WHEN acos IS NULL THEN
                    CASE WHEN r_no_sale_clicks > 0 AND clicks >= r_no_sale_clicks THEN 'pause'
                         WHEN COALESCE(low_impr,0) > 0 AND impressions <= low_impr
                              AND bid < boost_max THEN 'boost'
                         WHEN clicks > 5 THEN 'hold' ELSE 'new' END
                WHEN acos > high_acos THEN 'lower'
                WHEN acos < low_acos THEN 'raise'
                ELSE 'hold'
            END AS action
        FROM ranked WHERE rn = 1
    ),
    finalized AS (
        SELECT *,
            CASE action
                WHEN 'raise' THEN LEAST(max_bid, GREATEST(min_bid, ROUND(bid * (1 + low_pct/100), 2)))
                WHEN 'lower' THEN LEAST(max_bid, GREATEST(min_bid, ROUND(bid * (1 - high_pct/100), 2)))
                WHEN 'boost' THEN LEAST(boost_max, GREATEST(min_bid, ROUND(bid * (1 + boost_pct/100), 2)))
                ELSE bid
            END AS new_bid
        FROM acted
    ),
    filtered AS (SELECT * FROM finalized {rec_where})
    SELECT *,
        COUNT(*) OVER() AS _total
    FROM filtered
    ORDER BY {sort_by} {sort_dir} NULLS LAST
    LIMIT {per_page} OFFSET {offset}
    """

    try:
        client = get_client()
        _ensure_rules_table(client)
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
                'group_total_clicks': r['group_total_clicks'],
                'action':         r['action'],
                'new_bid':        _cvt(r['new_bid']) if r['new_bid'] is not None else None,
                'rule_name':      r['rule_name'],
                'rule_color':     r['rule_color'],
            })
        return jsonify({'rows': result, 'total': total, 'page': page, 'per_page': per_page})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bid_automation_bp.route('/automation/bid-automation/campaigns')
def ba_campaigns():
    """Список кампаний для фильтра (актуальные, дедуп по synced_at)."""
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    marketplace  = args.get('marketplace', 'US').upper()
    if account_type not in ('MERCH', 'KDP'):
        return jsonify({'error': 'Неверный account_type'}), 400

    suffix     = _suffix(account_type)
    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    safe_mkt   = _safe(marketplace)

    sql = f"""
    WITH c_raw AS (
        SELECT campaign_id, campaign_name, campaign_state, targeting_type,
            ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table}
        WHERE entity_type = 'campaign' AND marketplace = '{safe_mkt}'
    )
    SELECT campaign_id, campaign_name, campaign_state, targeting_type
    FROM c_raw WHERE rn = 1
    ORDER BY CASE WHEN campaign_state = 'ENABLED' THEN 0 ELSE 1 END, campaign_name
    """
    try:
        client = get_client()
        rows = [{
            'campaign_id':    r['campaign_id'],
            'campaign_name':  r['campaign_name'],
            'campaign_state': r['campaign_state'],
            'targeting_type': r['targeting_type'],
        } for r in client.query(sql, job_config=_QJC).result()]
        return jsonify({'rows': rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bid_automation_bp.route('/automation/bid-automation/ad-groups')
def ba_ad_groups():
    """Список групп для выбранной кампании."""
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    marketplace  = args.get('marketplace', 'US').upper()
    campaign_id  = args.get('campaign_id', '').strip()
    if account_type not in ('MERCH', 'KDP'):
        return jsonify({'error': 'Неверный account_type'}), 400

    suffix     = _suffix(account_type)
    camp_table = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    safe_mkt   = _safe(marketplace)

    conds = [f"entity_type = 'ad_group'", f"marketplace = '{safe_mkt}'"]
    if campaign_id:
        conds.append(f"campaign_id = '{_safe(campaign_id)}'")

    sql = f"""
    WITH g_raw AS (
        SELECT ad_group_id, ad_group_name, ad_group_state, campaign_id,
            ROW_NUMBER() OVER (PARTITION BY ad_group_id, marketplace ORDER BY synced_at DESC) rn
        FROM {camp_table}
        WHERE {' AND '.join(conds)}
    )
    SELECT ad_group_id, ad_group_name, ad_group_state, campaign_id
    FROM g_raw WHERE rn = 1
    ORDER BY CASE WHEN ad_group_state = 'ENABLED' THEN 0 ELSE 1 END, ad_group_name
    LIMIT 1000
    """
    try:
        client = get_client()
        rows = [{
            'ad_group_id':    r['ad_group_id'],
            'ad_group_name':  r['ad_group_name'],
            'ad_group_state': r['ad_group_state'],
            'campaign_id':    r['campaign_id'],
        } for r in client.query(sql, job_config=_QJC).result()]
        return jsonify({'rows': rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bid_automation_bp.route('/automation/bid-automation/negatives')
def ba_negatives():
    """Существующие минус-слова и минус-продукты в группе (для подсветки).
    Возвращает множества текстов (lowercase) и ASIN (upper)."""
    args         = request.args
    account_type = args.get('account_type', 'MERCH').upper()
    marketplace  = args.get('marketplace', 'US').upper()
    ad_group_id  = args.get('ad_group_id', '').strip()
    if not ad_group_id:
        return jsonify({'error': 'ad_group_id обязателен'}), 400

    suffix      = _suffix(account_type)
    camp_table  = f"`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`"
    pend_table  = f"`{PROJECT_ID}.{DATASET}.pending_changes_{suffix}`"
    safe_mkt    = _safe(marketplace)
    safe_agid   = _safe(ad_group_id)

    # Current negatives synced from Amazon (dedup latest by synced_at)
    sql = f"""
    WITH neg_raw AS (
        SELECT entity_type, keyword_text, targeting_expression,
            CASE WHEN entity_type = 'negative_keyword' THEN keyword_state ELSE target_state END AS st,
            ROW_NUMBER() OVER (
                PARTITION BY COALESCE(keyword_id, target_id), marketplace
                ORDER BY synced_at DESC
            ) rn
        FROM {camp_table}
        WHERE entity_type IN ('negative_keyword', 'negative_product_targeting')
          AND ad_group_id = '{safe_agid}'
          AND marketplace = '{safe_mkt}'
    )
    SELECT entity_type, keyword_text, targeting_expression
    FROM neg_raw
    WHERE rn = 1 AND (st IS NULL OR st != 'ARCHIVED')
    """

    texts = set()
    asins = set()
    try:
        client = get_client()
        for r in client.query(sql, job_config=_QJC).result():
            if r['entity_type'] == 'negative_keyword' and r['keyword_text']:
                texts.add(r['keyword_text'].strip().lower())
            elif r['entity_type'] == 'negative_product_targeting' and r['targeting_expression']:
                expr = r['targeting_expression']
                # формат вида: asin="B0XXXXXXXX"
                import re
                m = re.search(r'(B0[0-9A-Z]{8})', expr.upper())
                if m:
                    asins.add(m.group(1))
                else:
                    asins.add(expr.strip().upper())

        # Также учитываем ожидающие изменения (ещё не отправленные)
        psql = f"""
        SELECT entity_type, new_value
        FROM {pend_table}
        WHERE entity_id = '{safe_agid}'
          AND marketplace = '{safe_mkt}'
          AND entity_type IN ('negative_add', 'negative_product_add')
          AND status IN ('PENDING', 'APPROVED', 'SENDING')
        """
        import json as _json
        for r in client.query(psql, job_config=_QJC).result():
            try:
                v = _json.loads(r['new_value']) if r['new_value'] else {}
            except Exception:
                v = {}
            if r['entity_type'] == 'negative_add' and v.get('text'):
                texts.add(str(v['text']).strip().lower())
            elif r['entity_type'] == 'negative_product_add' and v.get('asin'):
                asins.add(str(v['asin']).strip().upper())

        return jsonify({'texts': sorted(texts), 'asins': sorted(asins)})
    except Exception as e:
        return jsonify({'error': str(e), 'texts': [], 'asins': []}), 500


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
