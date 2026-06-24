from bq_client import get_client
import os
from flask import Blueprint, jsonify, request, send_from_directory

campaign_copy_bp = Blueprint('campaign_copy', __name__)
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


@campaign_copy_bp.route('/campaign-copy')
def campaign_copy_page():
    return send_from_directory(BASE_DIR, 'campaign_copy.html')


@campaign_copy_bp.route('/campaign-copy/campaigns')
def campaign_copy_list():
    account_type = request.args.get('account_type', 'MERCH').upper()
    marketplace  = request.args.get('marketplace', 'US').upper()
    tbl = 'campaigns_merch' if account_type == 'MERCH' else 'campaigns_kdp'
    client = get_client()
    q = f"""
SELECT DISTINCT
  campaign_id, campaign_name, targeting_type, daily_budget,
  bidding_strategy, portfolio_id, portfolio_name, campaign_state
FROM `{PROJECT_ID}.{DATASET}.{tbl}`
WHERE entity_type = 'campaign'
  AND marketplace = '{marketplace}'
ORDER BY campaign_name
"""
    rows = list(client.query(q).result())
    out = []
    for r in rows:
        out.append({
            'id':             r['campaign_id'],
            'name':           r['campaign_name'],
            'targeting_type': r['targeting_type'],
            'budget':         float(r['daily_budget'] or 0),
            'bid_strategy':   r['bidding_strategy'],
            'portfolio_id':   r['portfolio_id'],
            'portfolio_name': r['portfolio_name'],
            'state':          r['campaign_state'],
        })
    return jsonify({'campaigns': out})


@campaign_copy_bp.route('/campaign-copy/structure')
def campaign_copy_structure():
    account_type = request.args.get('account_type', 'MERCH').upper()
    marketplace  = request.args.get('marketplace', 'US').upper()
    campaign_id  = request.args.get('campaign_id', '')
    if not campaign_id:
        return jsonify({'error': 'campaign_id required'}), 400

    tbl = 'campaigns_merch' if account_type == 'MERCH' else 'campaigns_kdp'
    client = get_client()
    q = f"""
SELECT
  entity_type, campaign_id, campaign_name, targeting_type, daily_budget,
  bidding_strategy, portfolio_id, portfolio_name, campaign_state,
  start_date, end_date,
  ad_group_id, ad_group_name, ad_group_default_bid, ad_group_state,
  keyword_id, keyword_text, match_type, keyword_bid, keyword_state,
  target_id, targeting_expression, target_bid, target_state,
  ad_id, asin, sku, ad_state
FROM `{PROJECT_ID}.{DATASET}.{tbl}`
WHERE campaign_id = '{campaign_id}'
  AND marketplace = '{marketplace}'
ORDER BY entity_type, ad_group_id
"""
    rows = list(client.query(q).result())

    # Debug: count entity types
    from collections import Counter
    counts = Counter(r['entity_type'] for r in rows)
    print(f"  [DEBUG] structure entity counts: {dict(counts)}")

    campaign   = None
    groups     = {}
    # asin_by_ag: ad_group_id → [asin, ...] collected from product_ad rows
    asin_by_ag = {}

    for r in rows:
        et = r['entity_type']
        if et == 'campaign':
            campaign = {
                'id':             r['campaign_id'],
                'name':           r['campaign_name'],
                'targeting_type': r['targeting_type'],
                'budget':         float(r['daily_budget'] or 0),
                'bid_strategy':   r['bidding_strategy'],
                'portfolio_id':   r['portfolio_id'],
                'portfolio_name': r['portfolio_name'],
                'state':          r['campaign_state'],
                'start_date':     str(r['start_date']) if r['start_date'] else None,
                'end_date':       str(r['end_date'])   if r['end_date']   else None,
            }
        elif et == 'ad_group':
            gid = str(r['ad_group_id']) if r['ad_group_id'] else None
            if gid and gid not in groups:
                groups[gid] = {
                    'id':       gid,
                    'name':     r['ad_group_name'],
                    'bid':      float(r['ad_group_default_bid'] or 0),
                    'state':    r['ad_group_state'],
                    'keywords': [],
                    'negatives': [],
                    'targets':  [],
                    'neg_targets': [],
                    'asins':    [],
                }
        elif et == 'keyword':
            gid = str(r['ad_group_id']) if r['ad_group_id'] else None
            if gid in groups:
                groups[gid]['keywords'].append({
                    'text':       r['keyword_text'],
                    'match_type': r['match_type'],
                    'bid':        float(r['keyword_bid'] or 0),
                    'state':      r['keyword_state'],
                })
        elif et == 'negative_keyword':
            gid = str(r['ad_group_id']) if r['ad_group_id'] else None
            if gid in groups:
                groups[gid]['negatives'].append({
                    'text':       r['keyword_text'],
                    'match_type': r['match_type'],
                })
        elif et == 'product_targeting':
            gid = str(r['ad_group_id']) if r['ad_group_id'] else None
            if gid in groups:
                groups[gid]['targets'].append({
                    'expression': r['targeting_expression'],
                    'bid':        float(r['target_bid'] or 0),
                    'state':      r['target_state'],
                })
        elif et == 'negative_product_targeting':
            gid = str(r['ad_group_id']) if r['ad_group_id'] else None
            if gid in groups:
                groups[gid]['neg_targets'].append({
                    'expression': r['targeting_expression'],
                })
        elif et == 'product_ad':
            gid  = str(r['ad_group_id']) if r['ad_group_id'] else None
            asin = r['asin']
            if asin:
                if gid:
                    if gid not in asin_by_ag:
                        asin_by_ag[gid] = []
                    if asin not in asin_by_ag[gid]:
                        asin_by_ag[gid].append(asin)
                print(f"  [DEBUG] product_ad asin={asin} ag_id={gid}")

    # Attach ASINs to groups; also ensure groups exist for orphan product_ads
    for gid, asins in asin_by_ag.items():
        if gid not in groups:
            # group entity might be missing — create placeholder
            groups[gid] = {
                'id': gid, 'name': gid, 'bid': 0, 'state': 'ENABLED',
                'keywords': [], 'negatives': [], 'targets': [], 'neg_targets': [], 'asins': [],
            }
        for asin in asins:
            if asin not in [a['asin'] for a in groups[gid]['asins']]:
                groups[gid]['asins'].append({'asin': asin, 'sku': None})

    print(f"  [DEBUG] groups: {[{'id':g['id'],'name':g['name'],'asins':g['asins']} for g in groups.values()]}")

    return jsonify({'campaign': campaign, 'groups': list(groups.values())})


@campaign_copy_bp.route('/campaign-copy/asin-map')
def campaign_copy_asin_map():
    asins    = request.args.get('asins', '')
    from_mkt = request.args.get('from_mkt', 'US').upper()
    to_mkt   = request.args.get('to_mkt', 'UK').upper()

    asin_list = [a.strip() for a in asins.split(',') if a.strip()]
    if not asin_list:
        return jsonify({'mapping': {}})

    client   = get_client()
    asin_sql = ', '.join(f"'{a}'" for a in asin_list)
    q = f"""
WITH src AS (
  SELECT asin, design_id
  FROM `{PROJECT_ID}.{DATASET}.catalog`
  WHERE marketplace = '{from_mkt}'
    AND asin IN ({asin_sql})
    AND design_id IS NOT NULL
),
tgt AS (
  SELECT asin AS target_asin, design_id, title, image_url
  FROM `{PROJECT_ID}.{DATASET}.catalog`
  WHERE marketplace = '{to_mkt}'
    AND design_id IS NOT NULL
)
SELECT src.asin AS source_asin, tgt.target_asin, tgt.title, tgt.image_url
FROM src
JOIN tgt ON src.design_id = tgt.design_id
"""
    rows    = list(client.query(q).result())
    mapping = {}
    for r in rows:
        mapping[r['source_asin']] = {
            'target_asin': r['target_asin'],
            'title':       r['title'],
            'image_url':   r['image_url'],
        }
    return jsonify({'mapping': mapping})
