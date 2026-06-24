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


@campaign_copy_bp.route('/campaign-copy/debug')
def campaign_copy_debug():
    """Diagnostic: show raw entity counts and sample product_ad rows for a campaign."""
    account_type = request.args.get('account_type', 'MERCH').upper()
    marketplace  = request.args.get('marketplace', 'US').upper()
    campaign_id  = request.args.get('campaign_id', '')
    tbl = f"`{PROJECT_ID}.{DATASET}.{'campaigns_merch' if account_type=='MERCH' else 'campaigns_kdp'}`"
    client = get_client()

    counts_q = f"""
SELECT entity_type, COUNT(*) as cnt
FROM {tbl}
WHERE campaign_id = '{campaign_id}' AND marketplace = '{marketplace}'
GROUP BY entity_type
"""
    ads_q = f"""
SELECT entity_type, campaign_id, ad_group_id, ad_id, asin, sku, ad_state
FROM {tbl}
WHERE entity_type = 'product_ad' AND marketplace = '{marketplace}'
  AND campaign_id = '{campaign_id}'
LIMIT 20
"""
    tgt_q = f"""
SELECT ad_group_id, targeting_expression, target_bid, target_state
FROM {tbl}
WHERE entity_type = 'product_targeting' AND marketplace = '{marketplace}'
  AND campaign_id = '{campaign_id}'
LIMIT 30
"""
    ag_q = f"""
SELECT ad_group_id, ad_group_name, ad_group_default_bid, ad_group_state
FROM {tbl}
WHERE entity_type = 'ad_group' AND marketplace = '{marketplace}'
  AND campaign_id = '{campaign_id}'
LIMIT 30
"""
    counts   = [dict(r) for r in client.query(counts_q).result()]
    ads      = [dict(r) for r in client.query(ads_q).result()]
    targets  = [dict(r) for r in client.query(tgt_q).result()]
    adgroups = [dict(r) for r in client.query(ag_q).result()]
    return jsonify({'counts': counts, 'product_ads': ads, 'targeting': targets, 'ad_groups': adgroups})


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

    import re
    from collections import Counter
    counts = Counter(r['entity_type'] for r in rows)
    print(f"  [DEBUG] structure entity counts: {dict(counts)}")

    # ASIN pattern: 10 chars starting with B
    ASIN_RE = re.compile(r'\bB[0-9A-Z]{9}\b')

    def extract_asin(text):
        if not text:
            return None
        m = ASIN_RE.search(str(text).upper())
        return m.group(0) if m else None

    campaign   = None
    groups     = {}
    # ad_group_id → [asin, ...] from product_ad rows (even if asin is null — track gid)
    ad_ids_by_ag = {}   # gid → [ad_id, ...]

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
                    'id':        gid,
                    'name':      r['ad_group_name'],
                    'bid':       float(r['ad_group_default_bid'] or 0),
                    'state':     r['ad_group_state'],
                    'keywords':  [],
                    'negatives': [],
                    'targets':   [],
                    'neg_targets': [],
                    'asins':     [],
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
                # Fallback: extract ASIN from targeting expression (e.g. asin="B0XXXXXX")
                asin_from_expr = extract_asin(r['targeting_expression'])
                if asin_from_expr:
                    seen = [a['asin'] for a in groups[gid]['asins']]
                    if asin_from_expr not in seen:
                        groups[gid]['asins'].append({'asin': asin_from_expr, 'sku': None, 'src': 'targeting'})
        elif et == 'negative_product_targeting':
            gid = str(r['ad_group_id']) if r['ad_group_id'] else None
            if gid in groups:
                groups[gid]['neg_targets'].append({
                    'expression': r['targeting_expression'],
                })
        elif et == 'product_ad':
            gid  = str(r['ad_group_id']) if r['ad_group_id'] else None
            asin = r['asin']
            if gid:
                if asin:
                    # Primary source: product_ad.asin
                    if gid not in groups:
                        groups[gid] = {
                            'id': gid, 'name': gid, 'bid': 0, 'state': 'ENABLED',
                            'keywords': [], 'negatives': [], 'targets': [], 'neg_targets': [], 'asins': [],
                        }
                    seen = [a['asin'] for a in groups[gid]['asins']]
                    if asin not in seen:
                        groups[gid]['asins'].append({'asin': asin, 'sku': r['sku'], 'src': 'product_ad'})
                else:
                    # Track that this group HAS an ad — we'll try name fallback later
                    if gid not in ad_ids_by_ag:
                        ad_ids_by_ag[gid] = True

    # Fallback: extract ASIN from ad_group name for groups that still have no ASIN
    for gid, g in groups.items():
        if not g['asins']:
            asin_from_name = extract_asin(g['name'])
            if asin_from_name:
                g['asins'].append({'asin': asin_from_name, 'sku': None, 'src': 'group_name'})
                print(f"  [DEBUG] ASIN from group name: {g['name']} → {asin_from_name}")

    print(f"  [DEBUG] groups asin summary: { {g['name']: [a['asin'] for a in g['asins']] for g in groups.values()} }")

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

    # Match source ASIN against both catalog.asin and catalog.ad_asin,
    # then join to target marketplace by design_id + product_type.
    # Step 1: find source entries in catalog
    src_q = f"""
SELECT
  asin, ad_asin, design_id, product_type, title
FROM `{PROJECT_ID}.{DATASET}.catalog`
WHERE marketplace = '{from_mkt}'
  AND (asin IN ({asin_sql}) OR ad_asin IN ({asin_sql}))
LIMIT 50
"""
    src_rows = list(client.query(src_q).result())
    print(f"  [DEBUG] asin-map src found: {len(src_rows)} rows for {len(asin_list)} ASINs")
    for r in src_rows:
        print(f"    asin={r['asin']} ad_asin={r['ad_asin']} design_id={r['design_id']} product_type={r['product_type']}")

    debug = {
        'src_count': len(src_rows),
        'src_sample': [{'asin': r['asin'], 'ad_asin': r['ad_asin'], 'design_id': r['design_id'], 'product_type': r['product_type']} for r in src_rows[:3]],
    }
    if not src_rows:
        debug['error'] = f'ASINs not found in catalog for {from_mkt}'
        return jsonify({'mapping': {}, 'debug': debug})

    # Build design_id+product_type list
    design_pairs = list({(str(r['design_id']), str(r['product_type'])) for r in src_rows if r['design_id'] and r['product_type']})
    # Also try without product_type (design_id only) as fallback
    design_ids = list({str(r['design_id']) for r in src_rows if r['design_id']})
    if not design_pairs:
        debug['error'] = 'design_id or product_type missing in catalog entries'
        return jsonify({'mapping': {}, 'debug': debug})

    pairs_sql = ', '.join(f"('{d}', '{pt}')" for d, pt in design_pairs)

    # Step 2: find target ASINs by design_id + product_type
    tgt_q = f"""
SELECT
  COALESCE(NULLIF(ad_asin, ''), asin) AS target_asin,
  design_id, product_type, title, image_url
FROM `{PROJECT_ID}.{DATASET}.catalog`
WHERE marketplace = '{to_mkt}'
  AND (design_id, product_type) IN ({pairs_sql})
"""
    tgt_rows = list(client.query(tgt_q).result())
    print(f"  [DEBUG] asin-map tgt found: {len(tgt_rows)} rows for {to_mkt}")
    debug['tgt_count'] = len(tgt_rows)
    debug['design_pairs_count'] = len(design_pairs)
    if not tgt_rows:
        # Try without product_type to diagnose
        if design_ids:
            did_sql = ', '.join(f"'{d}'" for d in design_ids[:5])
            probe_q = f"""
SELECT asin, ad_asin, design_id, product_type, marketplace
FROM `{PROJECT_ID}.{DATASET}.catalog`
WHERE design_id IN ({did_sql})
LIMIT 10
"""
            probe = [dict(r) for r in client.query(probe_q).result()]
            debug['probe'] = probe

    # Build lookup: (design_id, product_type) → target
    tgt_map = {}
    for r in tgt_rows:
        key = (str(r['design_id']), str(r['product_type']))
        if key not in tgt_map:
            tgt_map[key] = {'target_asin': r['target_asin'], 'title': r['title'], 'image_url': r['image_url']}

    mapping = {}
    for r in src_rows:
        # figure out which input ASIN this row matched
        matched = None
        if r['asin'] in asin_list:
            matched = r['asin']
        elif r['ad_asin'] and r['ad_asin'] in asin_list:
            matched = r['ad_asin']
        if not matched or matched in mapping:
            continue
        key = (str(r['design_id']), str(r['product_type']))
        if key in tgt_map:
            mapping[matched] = tgt_map[key]

    debug['mapped_count'] = len(mapping)
    return jsonify({'mapping': mapping, 'debug': debug})
