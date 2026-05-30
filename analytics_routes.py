import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory
from google.cloud import bigquery

analytics_bp = Blueprint('analytics', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

ALLOWED_SORT = {
    'campaign_name', 'clicks', 'impressions', 'cost', 'sales_14d',
    'purchases_14d', 'acos', 'ctr', 'marketplace', 'campaign_state',
    'targeting_type', 'portfolio_name', 'daily_budget',
}

SORT_EXPR = {
    'acos':          'acos',
    'ctr':           'ctr',
    'clicks':        'clicks',
    'impressions':   'impressions',
    'cost':          'cost',
    'sales_14d':     'sales_14d',
    'purchases_14d': 'purchases_14d',
    'daily_budget':  'daily_budget',
    'campaign_name': 'campaign_name',
    'marketplace':   'marketplace',
    'campaign_state':'campaign_state',
    'targeting_type':'targeting_type',
    'portfolio_name':'portfolio_name',
}

HAVING_EXPR = {
    'has_clicks':      'HAVING clicks > 0',
    'has_impressions': 'HAVING impressions > 0',
    'no_clicks':       'HAVING clicks = 0',
    'no_impressions':  'HAVING impressions = 0',
}


# ── HTML страница ─────────────────────────────────────────
@analytics_bp.route('/analytics/campaigns')
def analytics_campaigns_page():
    return send_from_directory(BASE_DIR, 'campaigns_analytics.html')


# ── API ───────────────────────────────────────────────────
@analytics_bp.route('/analytics/campaigns/data')
def analytics_campaigns_data():
    account_type   = request.args.get('account_type', 'MERCH').upper()
    date_from      = request.args.get('date_from', '')
    date_to        = request.args.get('date_to', '')
    marketplace    = request.args.get('marketplace', '')
    portfolio_id   = request.args.get('portfolio_id', '')
    targeting_type = request.args.get('targeting_type', '')
    campaign_state = request.args.get('campaign_state', '')
    activity       = request.args.get('activity', '')
    name_filter    = request.args.get('name', '').strip()
    # Числовые фильтры для всех числовых колонок
    NUM_FIELDS = ['impressions','clicks','cost','ctr','sales_14d','purchases_14d','acos']
    nf = {}
    for f in NUM_FIELDS:
        nf[f] = {
            'op':  request.args.get(f + '_op', ''),
            'val': request.args.get(f + '_val', ''),
            'min': request.args.get(f + '_min', ''),
            'max': request.args.get(f + '_max', ''),
        }
    sort_by        = request.args.get('sort_by', 'clicks')
    sort_dir       = request.args.get('sort_dir', 'desc').upper()

    try:
        page     = max(1, int(request.args.get('page', 1)))
        per_page = min(100, max(1, int(request.args.get('per_page', 25))))
    except ValueError:
        page, per_page = 1, 25

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400
    if sort_by not in ALLOWED_SORT:
        sort_by = 'clicks'
    if sort_dir not in ('ASC', 'DESC'):
        sort_dir = 'DESC'

    suffix     = account_type.lower()
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    stat_table = f"{PROJECT_ID}.{DATASET}.targets_stats_{suffix}"

    # ── Фильтры для кампаний (subquery) ───────────────────
    camp_conds = []
    if marketplace:
        camp_conds.append(f"marketplace = '{marketplace}'")
    portfolio_ids = request.args.get('portfolio_ids', '')  # через запятую
    if portfolio_ids:
        ids = [i.strip() for i in portfolio_ids.split(',') if i.strip()]
        safe_ids = ','.join(f"'{i}'" for i in ids)
        camp_conds.append(f"portfolio_id IN ({safe_ids})")
    elif portfolio_id:
        camp_conds.append(f"portfolio_id = '{portfolio_id}'")
    if targeting_type:
        camp_conds.append(f"targeting_type = '{targeting_type}'")
    if campaign_state:
        camp_conds.append(f"campaign_state = '{campaign_state}'")
    if name_filter:
        safe = name_filter.replace("'", "''")
        camp_conds.append(f"LOWER(campaign_name) LIKE LOWER('%{safe}%')")

    camp_filter = ('AND ' + ' AND '.join(camp_conds)) if camp_conds else ''

    # ── Фильтры для статистики (в ON клаузе LEFT JOIN) ────
    stat_on_conds = []
    if date_from:
        stat_on_conds.append(f"s.date >= '{date_from}'")
    if date_to:
        stat_on_conds.append(f"s.date <= '{date_to}'")
    stat_on_extra = (' AND ' + ' AND '.join(stat_on_conds)) if stat_on_conds else ''

    # HAVING: активность + числовые фильтры
    OP_MAP = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<=', 'eq': '='}

    def num_cond(col, d):
        parts = []
        op, val, mn, mx = d['op'], d['val'], d['min'], d['max']
        if op and val != '' and op in OP_MAP:
            try: parts.append(f'{col} {OP_MAP[op]} {float(val)}')
            except ValueError: pass
        if mn != '':
            try: parts.append(f'{col} >= {float(mn)}')
            except ValueError: pass
        if mx != '':
            try: parts.append(f'{col} <= {float(mx)}')
            except ValueError: pass
        return parts

    having_parts = []
    base_having = HAVING_EXPR.get(activity, '')
    if base_having:
        having_parts.append(base_having.replace('HAVING ', ''))

    for field in NUM_FIELDS:
        having_parts += num_cond(field, nf[field])

    having    = ('HAVING ' + ' AND '.join(having_parts)) if having_parts else ''
    order_col  = SORT_EXPR.get(sort_by, 'clicks')
    offset     = (page - 1) * per_page

    portfolio_table = f"{PROJECT_ID}.{DATASET}.portfolio_labels"

    # ── CTE: дедупликация + JOIN с portfolio_labels для актуальных имён ───────
    cte = f"""
    WITH campaigns_dedup AS (
        SELECT *
        FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY campaign_id, marketplace
                    ORDER BY synced_at DESC
                ) AS rn
            FROM `{camp_table}`
            WHERE entity_type = 'campaign'
            {camp_filter}
        )
        WHERE rn = 1
    ),
    camp_stats AS (
        SELECT
            c.campaign_id,
            c.campaign_name,
            c.marketplace,
            c.campaign_state,
            c.targeting_type,
            c.portfolio_id,
            COALESCE(pl.portfolio_name, c.portfolio_name) AS portfolio_name,
            c.daily_budget,
            c.start_date,
            COALESCE(SUM(s.impressions),   0) AS impressions,
            COALESCE(SUM(s.clicks),        0) AS clicks,
            COALESCE(SUM(s.cost),          0) AS cost,
            COALESCE(SUM(s.sales_14d),     0) AS sales_14d,
            COALESCE(SUM(s.purchases_14d), 0) AS purchases_14d,
            CASE WHEN SUM(s.impressions) > 0
                 THEN ROUND(SUM(s.clicks) / SUM(s.impressions), 5)
                 ELSE NULL END AS ctr,
            CASE WHEN SUM(s.sales_14d) > 0
                 THEN ROUND(SUM(s.cost) / SUM(s.sales_14d) * 100, 2)
                 ELSE NULL END AS acos
        FROM campaigns_dedup c
        LEFT JOIN `{stat_table}` s
            ON  s.campaign_id = c.campaign_id
            AND s.marketplace = c.marketplace
            {stat_on_extra}
        LEFT JOIN `{portfolio_table}` pl
            ON  pl.portfolio_id  = c.portfolio_id
            AND pl.marketplace   = c.marketplace
            AND pl.account_type  = '{suffix.upper()}'
        GROUP BY
            c.campaign_id, c.campaign_name, c.marketplace,
            c.campaign_state, c.targeting_type, c.portfolio_id,
            pl.portfolio_name, c.portfolio_name, c.daily_budget, c.start_date
    )
    """

    try:
        client = bigquery.Client(project=PROJECT_ID)

        # Два запроса: summary + paginated rows.
        # Оконные функции поверх GROUP BY не работают в BigQuery
        # ("Aggregations of aggregations are not allowed").
        # having применяется как WHERE к внешнему запросу
        # (HAVING внутри CTE с агрегатами → "Aggregations of aggregations" в BigQuery)
        having_where = having.replace('HAVING ', 'WHERE ', 1) if having else ''

        summary_sql = cte + f"""
        SELECT
            COUNT(*)                  AS total_campaigns,
            SUM(impressions)          AS total_impressions,
            SUM(clicks)               AS total_clicks,
            ROUND(SUM(cost), 2)       AS total_cost,
            ROUND(SUM(sales_14d), 2)  AS total_sales_14d,
            SUM(purchases_14d)        AS total_purchases
        FROM camp_stats
        {having_where}
        """
        sr = list(client.query(summary_sql).result())[0]
        total   = int(sr.total_campaigns or 0)
        summary = {
            "total_campaigns":   total,
            "total_impressions": int(sr.total_impressions or 0),
            "total_clicks":      int(sr.total_clicks      or 0),
            "total_cost":        float(sr.total_cost      or 0),
            "total_sales_14d":   float(sr.total_sales_14d or 0),
            "total_purchases":   int(sr.total_purchases   or 0),
        }

        data_sql = cte + f"""
        SELECT * FROM camp_stats
        {having_where}
        ORDER BY {order_col} {sort_dir} NULLS LAST
        LIMIT {per_page} OFFSET {offset}
        """
        rows_raw = list(client.query(data_sql).result())

        rows = []
        for row in rows_raw:
            r = dict(row)
            for k, v in r.items():
                if isinstance(v, decimal.Decimal):
                    r[k] = float(v)
                elif hasattr(v, 'isoformat'):
                    r[k] = v.isoformat()
            rows.append(r)

        return jsonify({
            "rows":     rows,
            "total":    total,
            "page":     page,
            "per_page": per_page,
            "summary":  summary,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Уникальные портфолио для текущего набора фильтров ─────
@analytics_bp.route('/analytics/campaigns/portfolios')
def analytics_portfolios():
    """
    Возвращает уникальные portfolio_id + portfolio_name
    для текущих фильтров (account_type, marketplace, targeting_type, campaign_state).
    Не зависит от пагинации — всегда по всем кампаниям.
    """
    account_type   = request.args.get('account_type', 'MERCH').upper()
    marketplace    = request.args.get('marketplace', '')
    targeting_type = request.args.get('targeting_type', '')
    campaign_state = request.args.get('campaign_state', '')

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"portfolios": []})

    suffix          = account_type.lower()
    camp_table      = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    portfolio_table = f"{PROJECT_ID}.{DATASET}.portfolio_labels"

    conds = ["entity_type = 'campaign'", "portfolio_id IS NOT NULL"]
    if marketplace:    conds.append(f"marketplace = '{marketplace}'")
    if targeting_type: conds.append(f"targeting_type = '{targeting_type}'")
    if campaign_state: conds.append(f"campaign_state = '{campaign_state}'")
    where = 'WHERE ' + ' AND '.join(conds)

    sql = f"""
    SELECT DISTINCT
        c.portfolio_id,
        COALESCE(pl.portfolio_name, c.portfolio_name, c.portfolio_id) AS portfolio_name
    FROM `{camp_table}` c
    LEFT JOIN `{portfolio_table}` pl
        ON  pl.portfolio_id  = c.portfolio_id
        AND pl.marketplace   = c.marketplace
        AND pl.account_type  = '{account_type}'
    {where}
    ORDER BY portfolio_name
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        rows   = [{"id": r.portfolio_id, "name": r.portfolio_name}
                  for r in client.query(sql).result()]
        return jsonify({"portfolios": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@analytics_bp.route('/analytics/campaigns/portfolios')
def analytics_campaigns_portfolios():
    """
    Возвращает уникальные портфолио из результата с учётом текущих фильтров
    (без пагинации и числовых фильтров — только основные).
    """
    account_type   = request.args.get('account_type', 'MERCH').upper()
    marketplace    = request.args.get('marketplace', '')
    targeting_type = request.args.get('targeting_type', '')
    campaign_state = request.args.get('campaign_state', '')

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"portfolios": []})

    suffix     = account_type.lower()
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    portfolio_table = f"{PROJECT_ID}.{DATASET}.portfolio_labels"

    camp_conds = ["entity_type = 'campaign'", "portfolio_id IS NOT NULL"]
    if marketplace:    camp_conds.append(f"marketplace = '{marketplace}'")
    if targeting_type: camp_conds.append(f"targeting_type = '{targeting_type}'")
    if campaign_state: camp_conds.append(f"campaign_state = '{campaign_state}'")
    where = 'WHERE ' + ' AND '.join(camp_conds)

    sql = f"""
    SELECT DISTINCT
        c.portfolio_id AS id,
        COALESCE(pl.portfolio_name, c.portfolio_name, c.portfolio_id) AS name
    FROM `{camp_table}` c
    LEFT JOIN `{portfolio_table}` pl
        ON  pl.portfolio_id  = c.portfolio_id
        AND pl.marketplace   = c.marketplace
        AND pl.account_type  = '{account_type}'
    {where}
    ORDER BY name
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        rows = list(client.query(sql).result())
        portfolios = [{"id": r.id, "name": r.name or r.id} for r in rows]
        return jsonify({"portfolios": portfolios})
    except Exception as e:
        return jsonify({"error": str(e), "portfolios": []}), 500

@analytics_bp.route('/analytics/campaigns/structure')
def analytics_campaign_structure():
    """
    Возвращает структуру кампании + статистику за период.
    GET /analytics/campaigns/structure?campaign_id=...&account_type=MERCH&date_from=...&date_to=...
    """
    campaign_id  = request.args.get('campaign_id', '')
    account_type = request.args.get('account_type', 'MERCH').upper()
    date_from    = request.args.get('date_from', '')
    date_to      = request.args.get('date_to', '')

    if not campaign_id or account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверные параметры"}), 400

    suffix     = account_type.lower()
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    stat_table = f"{PROJECT_ID}.{DATASET}.targets_stats_{suffix}"

    # ── Запрос структуры ──────────────────────────────────
    struct_sql = f"""
    SELECT
        entity_type, ad_group_id, ad_group_name,
        ad_group_default_bid, ad_group_state,
        keyword_id, keyword_text, match_type,
        keyword_bid, keyword_state,
        target_id, targeting_expression,
        target_bid, target_state,
        placement, placement_percentage,
        campaign_name
    FROM `{camp_table}`
    WHERE campaign_id = '{campaign_id}'
      AND entity_type IN ('ad_group','keyword','negative_keyword','product_targeting','bidding_adjustment')
    ORDER BY entity_type, ad_group_id, keyword_text, targeting_expression
    """

    # ── Запрос статистики по keyword_id + ad_group ────────
    date_conds = []
    if date_from: date_conds.append(f"date >= '{date_from}'")
    if date_to:   date_conds.append(f"date <= '{date_to}'")
    date_where = ('AND ' + ' AND '.join(date_conds)) if date_conds else ''

    stats_sql = f"""
    SELECT
        ad_group_id,
        keyword_id,
        keyword_type,
        targeting,
        SUM(impressions)                AS impressions,
        SUM(clicks)                     AS clicks,
        SUM(cost)                       AS cost,
        SUM(purchases_14d)              AS purchases_14d,
        SUM(sales_14d)                  AS sales_14d,
        CASE WHEN SUM(impressions) > 0
             THEN SUM(top_of_search_impression_share * impressions) / SUM(impressions)
             ELSE NULL END AS top_of_search_pct
    FROM `{stat_table}`
    WHERE campaign_id = '{campaign_id}'
    {date_where}
    GROUP BY ad_group_id, keyword_id, keyword_type, targeting
    """


    try:
        client = bigquery.Client(project=PROJECT_ID)
        search_table = f"{PROJECT_ID}.{DATASET}.search_terms_{suffix}"
        search_sql = f"""
        SELECT
            ad_group_id,
            keyword_id,
            keyword_type,
            keyword,
            targeting,
            match_type,
            search_term,
            SUM(impressions)   AS impressions,
            SUM(clicks)        AS clicks,
            SUM(cost)          AS cost,
            SUM(purchases_14d) AS purchases_14d,
            SUM(sales_14d)     AS sales_14d
        FROM `{search_table}`
        WHERE campaign_id = '{campaign_id}'
        {date_where}
        GROUP BY ad_group_id, keyword_id, keyword_type, keyword, targeting, match_type, search_term
        ORDER BY clicks DESC
        """

        # Статистика по плейсментам — top_of_search_impression_share
        placement_sql = f"""
        SELECT
            SUM(impressions)   AS impressions,
            SUM(clicks)        AS clicks,
            SUM(cost)          AS cost,
            SUM(sales_14d)     AS sales_14d,
            SUM(purchases_14d) AS purchases_14d,
            AVG(CASE WHEN top_of_search_impression_share > 0
                THEN top_of_search_impression_share ELSE NULL END) AS top_of_search_share
        FROM `{stat_table}`
        WHERE campaign_id = '{campaign_id}'
        {date_where}
        """

        struct_rows    = list(client.query(struct_sql).result())
        stats_rows     = list(client.query(stats_sql).result())
        search_rows    = list(client.query(search_sql).result())
        placement_rows = list(client.query(placement_sql).result())

        campaign_stats = {}
        if placement_rows:
            pr = placement_rows[0]
            impr  = float(pr.impressions or 0)
            clks  = float(pr.clicks or 0)
            cost  = float(pr.cost or 0)
            sales = float(pr.sales_14d or 0)
            campaign_stats = {
                'impressions':   int(impr),
                'clicks':        int(clks),
                'cost':          round(cost, 2),
                'sales_14d':     round(sales, 2),
                'purchases_14d': int(pr.purchases_14d or 0),
                'ctr':           round(clks/impr*100, 3) if impr > 0 else None,
                'acos':          round(cost/sales*100, 1) if sales > 0 else None,
                'top_of_search_share': round(float(pr.top_of_search_share or 0)*100, 1) if pr.top_of_search_share else None,
            }

        # Индексируем статистику
        kw_stats   = {}   # keyword_id → stats
        ag_stats   = {}   # ad_group_id → stats (суммарно)
        tgt_stats  = {}   # (ad_group_id, targeting) → stats
        st_by_kw   = {}   # (ad_group_id, keyword_id) → [search terms]
        st_by_ag   = {}   # ad_group_id → [search terms] (auto)

        def to_stat(r):
            d = dict(r)
            for k, v in d.items():
                if isinstance(v, decimal.Decimal): d[k] = float(v)
            # Считаем ctr и acos в Python
            impr = d.get('impressions') or 0
            clks = d.get('clicks') or 0
            cost = d.get('cost') or 0
            sales = d.get('sales_14d') or 0
            d['ctr']  = round(clks / impr * 100, 3) if impr > 0 else None
            d['acos'] = round(cost / sales * 100, 1) if sales > 0 else None
            # Обнуляем None
            for m in ('impressions','clicks','cost','purchases_14d','sales_14d'):
                if d.get(m) is None: d[m] = 0
            return d

        for r in stats_rows:
            s = to_stat(r)
            ag = s.get('ad_group_id') or ''
            kw_id = s.get('keyword_id') or ''
            tgt   = s.get('targeting') or ''

            # Суммируем по группе
            if ag not in ag_stats:
                ag_stats[ag] = {'impressions':0,'clicks':0,'cost':0,'purchases_14d':0,'sales_14d':0}
            for m in ('impressions','clicks','cost','purchases_14d','sales_14d'):
                ag_stats[ag][m] = round(ag_stats[ag][m] + (s.get(m) or 0), 2)

            if kw_id:
                kw_stats[kw_id] = s  # top_of_search_pct уже в s через to_stat
            if tgt:
                # Маппинг из targets_stats.targeting → campaigns_merch.targeting_expression
                # Проверено по debug: targeting в stats = "close-match","loose-match","substitutes","complements"
                NORM = {
                    'close-match':  'KEYWORDS_CLOSE_MATCH',
                    'loose-match':  'KEYWORDS_LOOSE_MATCH',
                    'substitutes':  'PRODUCT_SUBSTITUTES',
                    'complements':  'PRODUCT_COMPLEMENTS',
                    'same-as':      'PRODUCT_SUBSTITUTES',
                    'keyword':      'KEYWORDS_CLOSE_MATCH',  # fallback
                }
                # Суммируем статистику по (ag, norm_key) — несколько keyword_id на один тип
                for key in [(ag, tgt), (ag, NORM.get(tgt.lower(), ''))]:
                    if not key[1]: continue
                    if key not in tgt_stats:
                        tgt_stats[key] = {'impressions':0,'clicks':0,'cost':0,
                                          'purchases_14d':0,'sales_14d':0}
                    for m in ('impressions','clicks','cost','purchases_14d','sales_14d'):
                        tgt_stats[key][m] = round(tgt_stats[key].get(m,0) + (s.get(m) or 0), 4)
                # top_of_search_pct — среднее (уже вычислено AVG в SQL, берём последнее)
                if s.get('top_of_search_pct') is not None:
                    tgt_stats[key]['top_of_search_pct'] = s.get('top_of_search_pct')

        # Индексируем поисковые запросы
        for r in search_rows:
            s = to_stat(r)
            ag    = s.get('ad_group_id') or ''
            kw_id = s.get('keyword_id') or ''
            kw_type = s.get('keyword_type') or ''
            term  = s.get('search_term') or ''
            if not term: continue
            entry = {
                'term':         term,
                'match_type':   s.get('match_type'),
                'keyword_type': kw_type,
                'keyword':      s.get('keyword') or s.get('targeting') or '',
                'impressions':  s.get('impressions'),
                'clicks':       s.get('clicks'),
                'cost':         s.get('cost'),
                'purchases_14d':s.get('purchases_14d'),
                'sales_14d':    s.get('sales_14d'),
                'ctr':          s.get('ctr'),
                'acos':         s.get('acos'),
            }
            # Auto-таргеты: keyword_type = TARGETING_EXPRESSION_PREDEFINED
            # У них keyword_id заполнен, но это не ключевое слово — группируем по ag
            is_auto = kw_type in ('TARGETING_EXPRESSION_PREDEFINED', 'TARGETING_EXPRESSION')
            if kw_id and not is_auto:
                st_by_kw.setdefault((ag, kw_id), []).append(entry)
            else:
                # Auto и неизвестные — к группе
                st_by_ag.setdefault(ag, []).append(entry)

        # Добавляем ACOS/CTR к суммам группы и таргетов
        for ag, s in ag_stats.items():
            s['ctr']  = round(s['clicks']/s['impressions']*100, 3) if s['impressions'] > 0 else None
            s['acos'] = round(s['cost']/s['sales_14d']*100, 1)     if s['sales_14d']  > 0 else None

        for key, s in tgt_stats.items():
            if isinstance(s, dict) and 'clicks' in s:
                s['ctr']  = round(s['clicks']/s['impressions']*100, 3) if s.get('impressions',0) > 0 else None
                s['acos'] = round(s['cost']/s['sales_14d']*100, 1)     if s.get('sales_14d',0)  > 0 else None

        # ── Группируем структуру ──────────────────────────
        groups = {}
        adjustments = []

        for row in struct_rows:
            r = dict(row)
            for k, v in r.items():
                if isinstance(v, decimal.Decimal): r[k] = float(v)

            et    = r['entity_type']
            ag_id = r.get('ad_group_id') or '__none__'

            if et == 'bidding_adjustment':
                adjustments.append({
                    'placement':  r.get('placement'),
                    'percentage': r.get('placement_percentage'),
                })
                continue

            if ag_id not in groups:
                gs = ag_stats.get(ag_id, {})
                groups[ag_id] = {
                    'id':           ag_id,
                    'name':         r.get('ad_group_name') or ag_id,
                    'bid':          r.get('ad_group_default_bid'),
                    'state':        r.get('ad_group_state'),
                    'stats':        gs,
                    'search_terms': st_by_ag.get(ag_id, []),
                    'keywords':     [],
                    'targets':      [],
                    'negatives':    [],
                }

            if et == 'keyword':
                kw_id = r.get('keyword_id') or ''
                st = kw_stats.get(kw_id, {})
                groups[ag_id]['keywords'].append({
                    'id':           kw_id,
                    'text':         r.get('keyword_text'),
                    'match_type':   r.get('match_type'),
                    'bid':          r.get('keyword_bid'),
                    'state':        r.get('keyword_state'),
                    'stats':        st,
                    'search_terms': st_by_kw.get((ag_id, kw_id), []),
                })
            elif et == 'negative_keyword':
                groups[ag_id]['negatives'].append({
                    'text':       r.get('keyword_text'),
                    'match_type': r.get('match_type'),
                })
            elif et == 'product_targeting':
                tgt_expr = r.get('targeting_expression') or ''
                # Ищем по targeting_expression (уже нормализовано при индексации)
                st = tgt_stats.get((ag_id, tgt_expr)) or {}
                groups[ag_id]['targets'].append({
                    'id':         r.get('target_id'),
                    'expression': tgt_expr,
                    'bid':        r.get('target_bid'),
                    'state':      r.get('target_state'),
                    'stats':      st,
                })

        # Берём campaign_name из первой строки структуры
        campaign_name = ''
        for row in struct_rows:
            n = dict(row).get('campaign_name')
            if n:
                campaign_name = n
                break

        return jsonify({
            'campaign_name': campaign_name,
            'groups':        list(groups.values()),
            'adjustments':   adjustments,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@analytics_bp.route('/analytics/debug/targeting')
def debug_targeting():
    """Debug: посмотреть что лежит в targets_stats для кампании"""
    campaign_id  = request.args.get('campaign_id', '')
    account_type = request.args.get('account_type', 'MERCH').upper()
    date_from    = request.args.get('date_from', '')
    date_to      = request.args.get('date_to', '')

    suffix     = account_type.lower()
    stat_table = f"{PROJECT_ID}.{DATASET}.targets_stats_{suffix}"
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"

    date_conds = []
    if date_from: date_conds.append(f"date >= '{date_from}'")
    if date_to:   date_conds.append(f"date <= '{date_to}'")
    date_where = ('AND ' + ' AND '.join(date_conds)) if date_conds else ''

    sql_stats = f"""
    SELECT DISTINCT keyword_type, targeting, keyword_id,
           SUM(clicks) as clicks, SUM(impressions) as impressions
    FROM `{stat_table}`
    WHERE campaign_id = '{campaign_id}' {date_where}
    GROUP BY keyword_type, targeting, keyword_id
    ORDER BY clicks DESC
    LIMIT 20
    """

    sql_struct = f"""
    SELECT DISTINCT entity_type, targeting_expression, keyword_text, keyword_id, ad_group_id
    FROM `{camp_table}`
    WHERE campaign_id = '{campaign_id}'
      AND entity_type IN ('product_targeting','keyword')
    LIMIT 20
    """

    try:
        client = bigquery.Client(project=PROJECT_ID)
        stats  = [dict(r) for r in client.query(sql_stats).result()]
        struct = [dict(r) for r in client.query(sql_struct).result()]
        return jsonify({'stats_rows': stats, 'struct_rows': struct})
    except Exception as e:
        return jsonify({'error': str(e)}), 500