from bq_client import get_client
import os
from flask import Blueprint, request, jsonify, send_from_directory

asin_merge_bp = Blueprint('asin_merge', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


@asin_merge_bp.route('/asin-merge')
def asin_merge_page():
    return send_from_directory(BASE_DIR, 'asin_merge.html')


@asin_merge_bp.route('/asin-merge/lookup')
def asin_merge_lookup():
    asin = request.args.get('asin', '').strip().upper()
    if not asin:
        return jsonify({'error': 'ASIN required'}), 400
    safe = asin.replace("'", "''")
    sql = f"""
    SELECT asin, design_id, title, product_type, marketplace, status, image_url
    FROM `{PROJECT_ID}.{DATASET}.catalog`
    WHERE asin = '{safe}'
    ORDER BY imported_at DESC
    LIMIT 1
    """
    try:
        client = get_client()
        rows = list(client.query(sql).result())
        if not rows:
            return jsonify({'error': f'ASIN {asin} не найден в каталоге'}), 404
        return jsonify({'data': dict(rows[0])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@asin_merge_bp.route('/asin-merge/add', methods=['POST'])
def asin_merge_add():
    body       = request.json or {}
    source_asin = body.get('source_asin', '').strip().upper()
    new_asin    = body.get('new_asin', '').strip().upper()
    if not source_asin or not new_asin:
        return jsonify({'error': 'Оба ASIN обязательны'}), 400
    if source_asin == new_asin:
        return jsonify({'error': 'ASINы совпадают'}), 400

    safe_src = source_asin.replace("'", "''")
    safe_new = new_asin.replace("'", "''")

    try:
        client = get_client()

        # Check new ASIN doesn't already exist
        existing = list(client.query(f"""
            SELECT COUNT(*) AS cnt FROM `{PROJECT_ID}.{DATASET}.catalog`
            WHERE asin = '{safe_new}'
        """).result())
        if existing[0]['cnt'] > 0:
            return jsonify({'error': f'{new_asin} уже существует в каталоге'}), 409

        # Fetch source row (all columns)
        rows = list(client.query(f"""
            SELECT * FROM `{PROJECT_ID}.{DATASET}.catalog`
            WHERE asin = '{safe_src}'
            ORDER BY imported_at DESC
            LIMIT 1
        """).result())
        if not rows:
            return jsonify({'error': f'{source_asin} не найден в каталоге'}), 404

        src = dict(rows[0])
        src['asin'] = new_asin

        def sql_val(v):
            if v is None:
                return 'NULL'
            if isinstance(v, bool):
                return 'TRUE' if v else 'FALSE'
            if isinstance(v, (int, float)):
                return str(v)
            return "'" + str(v).replace("'", "''") + "'"

        cols = ', '.join(f'`{k}`' for k in src.keys())
        vals = ', '.join(sql_val(v) for v in src.values())
        client.query(f"INSERT INTO `{PROJECT_ID}.{DATASET}.catalog` ({cols}) VALUES ({vals})").result()

        return jsonify({'ok': True, 'inserted': new_asin})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@asin_merge_bp.route('/asin-merge/list')
def asin_merge_list():
    """Return all design groups with multiple ASINs (for review)."""
    sql = f"""
    SELECT design_id, product_type,
           STRING_AGG(asin ORDER BY asin) AS asins,
           COUNT(*) AS cnt,
           MAX(title) AS title,
           MAX(marketplace) AS marketplace
    FROM `{PROJECT_ID}.{DATASET}.catalog`
    WHERE design_id IS NOT NULL
    GROUP BY design_id, product_type
    HAVING COUNT(*) > 1
    ORDER BY cnt DESC, design_id
    LIMIT 200
    """
    try:
        client = get_client()
        rows = list(client.query(sql).result())
        return jsonify({'groups': [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
