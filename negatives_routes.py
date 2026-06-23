from bq_client import get_client
import os
import decimal
from flask import Blueprint, request, jsonify, send_from_directory

negatives_bp = Blueprint('negatives', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


def _suffix(account_type):
    return 'kdp' if account_type == 'KDP' else 'merch'


# ── HTML page ─────────────────────────────────────────────
@negatives_bp.route('/negatives')
def negatives_page():
    return send_from_directory(BASE_DIR, 'negatives.html')


# ── Campaigns list with neg counts ────────────────────────
@negatives_bp.route('/negatives/campaigns')
def negatives_campaigns():
    try:
        account_type   = request.args.get('account_type', 'MERCH').upper()
        marketplace    = request.args.get('marketplace', '')
        portfolio_ids  = request.args.get('portfolio_ids', '')
        targeting_type = request.args.get('targeting_type', 'all')
        active_only    = request.args.get('active_only', '') in ('1', 'true', 'True')
        search         = request.args.get('search', '').strip()

        suffix     = _suffix(account_type)
        camp_table = f'`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`'

        where_clauses = ''
        if marketplace:
            where_clauses += f"\n      AND marketplace = '{marketplace}'"
        if portfolio_ids:
            ids = [p.strip() for p in portfolio_ids.split(',') if p.strip()]
            if ids:
                id_list = ', '.join(f"'{i}'" for i in ids)
                where_clauses += f'\n      AND portfolio_id IN ({id_list})'
        if targeting_type in ('AUTO', 'MANUAL'):
            where_clauses += f"\n      AND targeting_type = '{targeting_type}'"
        if active_only:
            where_clauses += "\n      AND campaign_state = 'ENABLED'"
        if search:
            safe_search = search.replace("'", "''")
            where_clauses += f"\n      AND LOWER(campaign_name) LIKE LOWER('%{safe_search}%')"

        query = f"""
WITH camp AS (
  SELECT campaign_id, campaign_name, campaign_state, targeting_type,
         marketplace, portfolio_id, portfolio_name, daily_budget
  FROM {camp_table}
  WHERE entity_type = 'campaign'
    {where_clauses}
),
neg_counts AS (
  SELECT campaign_id, COUNT(*) AS neg_count
  FROM {camp_table}
  WHERE entity_type = 'negative_keyword'
    AND (ad_group_id IS NULL OR ad_group_id = '')
  GROUP BY campaign_id
)
SELECT c.*, COALESCE(n.neg_count, 0) AS neg_count
FROM camp c
LEFT JOIN neg_counts n USING (campaign_id)
ORDER BY campaign_name
LIMIT 500
"""
        client = get_client()
        rows = list(client.query(query).result())

        campaigns = []
        for r in rows:
            campaigns.append({
                'campaign_id':    r['campaign_id'],
                'campaign_name':  r['campaign_name'],
                'campaign_state': r['campaign_state'],
                'targeting_type': r['targeting_type'],
                'marketplace':    r['marketplace'],
                'portfolio_id':   r['portfolio_id'] or '',
                'portfolio_name': r['portfolio_name'] or '',
                'neg_count':      int(r['neg_count']),
            })

        return jsonify({'campaigns': campaigns})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Keywords for a single campaign ────────────────────────
@negatives_bp.route('/negatives/campaign/keywords')
def negatives_campaign_keywords():
    try:
        campaign_id  = request.args.get('campaign_id', '').strip()
        account_type = request.args.get('account_type', 'MERCH').upper()

        if not campaign_id:
            return jsonify({'error': 'campaign_id required'}), 400

        suffix     = _suffix(account_type)
        camp_table = f'`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`'
        safe_cid   = campaign_id.replace("'", "''")

        query = f"""
SELECT keyword_id, keyword_text, match_type
FROM {camp_table}
WHERE campaign_id = '{safe_cid}'
  AND entity_type = 'negative_keyword'
  AND (ad_group_id IS NULL OR ad_group_id = '')
ORDER BY keyword_text
"""
        client = get_client()
        rows = list(client.query(query).result())

        keywords = [
            {
                'keyword_id':   r['keyword_id'],
                'keyword_text': r['keyword_text'],
                'match_type':   r['match_type'],
            }
            for r in rows
        ]

        return jsonify({'keywords': keywords})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Portfolios for filter dropdown ────────────────────────
@negatives_bp.route('/negatives/portfolios')
def negatives_portfolios():
    try:
        account_type = request.args.get('account_type', 'MERCH').upper()
        suffix       = _suffix(account_type)
        camp_table   = f'`{PROJECT_ID}.{DATASET}.campaigns_{suffix}`'

        query = f"""
SELECT DISTINCT portfolio_id, portfolio_name
FROM {camp_table}
WHERE entity_type = 'campaign'
  AND portfolio_id IS NOT NULL
  AND portfolio_id != ''
ORDER BY portfolio_name
"""
        client = get_client()
        rows = list(client.query(query).result())

        portfolios = [
            {'id': r['portfolio_id'], 'name': r['portfolio_name'] or r['portfolio_id']}
            for r in rows
        ]

        return jsonify({'portfolios': portfolios})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
