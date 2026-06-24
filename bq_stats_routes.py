from bq_client import get_client
import os
from flask import Blueprint, jsonify, send_from_directory, request, Response

bq_stats_bp = Blueprint('bq_stats', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


@bq_stats_bp.route('/bq-stats')
def bq_stats_page():
    return send_from_directory(BASE_DIR, 'bq_stats.html')


@bq_stats_bp.route('/bq-stats/sql')
def bq_sql():
    """Run a read-only SELECT query and return results as JSON."""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': 'q param required'}), 400
    q_upper = q.upper()
    if any(kw in q_upper for kw in ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE', 'MERGE', 'CREATE')):
        return jsonify({'error': 'Only SELECT queries allowed'}), 400
    try:
        client = get_client()
        rows = list(client.query(q).result())
        if not rows:
            return jsonify({'columns': [], 'rows': [], 'count': 0})
        columns = list(rows[0].keys())
        data = []
        for r in rows:
            row = {}
            for k in columns:
                v = r[k]
                row[k] = str(v) if v is not None else None
            data.append(row)
        return jsonify({'columns': columns, 'rows': data, 'count': len(data)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bq_stats_bp.route('/bq-stats/storage')
def bq_storage():
    """Размер таблиц через __TABLES__ (быстро, без INFORMATION_SCHEMA)"""
    try:
        client = get_client()
        query = f"""
SELECT
  table_id              AS table_name,
  row_count             AS total_rows,
  size_bytes            AS total_logical_bytes,
  TIMESTAMP_MILLIS(last_modified_time) AS last_modified_time
FROM `{PROJECT_ID}.{DATASET}.__TABLES__`
ORDER BY size_bytes DESC
"""
        rows = list(client.query(query).result())
        tables = []
        total_bytes = 0
        for r in rows:
            lb = int(r['total_logical_bytes'] or 0)
            total_bytes += lb
            tables.append({
                'name':          r['table_name'],
                'rows':          int(r['total_rows'] or 0),
                'logical_bytes': lb,
                'logical_gb':    round(lb / 1e9, 3),
                'last_modified': r['last_modified_time'].isoformat() if r['last_modified_time'] else None,
            })
        return jsonify({
            'tables':             tables,
            'total_logical_gb':   round(total_bytes / 1e9, 3),
            'total_logical_bytes': total_bytes,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bq_stats_bp.route('/bq-stats/jobs')
def bq_jobs():
    """История запросов — пробуем несколько источников."""
    client = get_client()

    def try_query(q):
        return list(client.query(q).result())

    # Candidates: JOBS_BY_PROJECT (needs jobUser or viewer), then JOBS_BY_USER, then JOBS
    regions = ['region-us', 'region-eu', 'US', 'EU']
    views   = ['JOBS_BY_PROJECT', 'JOBS_BY_USER', 'JOBS']

    daily_rows = None
    top_rows   = None
    used_src   = None

    for region in regions:
        for view in views:
            src = f'`{PROJECT_ID}.{region}.INFORMATION_SCHEMA.{view}`'
            daily_q = f"""
SELECT
  DATE(creation_time) AS day,
  COUNT(*)                             AS query_count,
  COUNTIF(error_result IS NOT NULL)    AS error_count,
  SUM(total_bytes_processed)           AS bytes_processed,
  SUM(total_bytes_billed)              AS bytes_billed,
  SUM(total_slot_ms)                   AS slot_ms
FROM {src}
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND job_type = 'QUERY'
GROUP BY 1
ORDER BY 1 DESC
"""
            try:
                daily_rows = try_query(daily_q)
                used_src = f'{region}/{view}'
                break
            except Exception:
                continue
        if daily_rows is not None:
            break

    if daily_rows is None:
        return jsonify({
            'daily': [], 'top_queries': [],
            'totals': {'query_count': 0, 'bytes_processed': 0, 'bytes_billed': 0, 'cost_usd': 0},
            'no_permission': True,
        })

    region_used = used_src.split('/')[0]
    view_used   = used_src.split('/')[1]
    src2 = f'`{PROJECT_ID}.{region_used}.INFORMATION_SCHEMA.{view_used}`'
    top_q = f"""
SELECT
  DATE(creation_time) AS day,
  LEFT(query, 150)    AS query_preview,
  total_bytes_billed,
  total_bytes_processed,
  TIMESTAMP_DIFF(end_time, start_time, MILLISECOND) AS duration_ms
FROM {src2}
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND job_type = 'QUERY'
  AND error_result IS NULL
  AND total_bytes_billed > 0
ORDER BY total_bytes_billed DESC
LIMIT 20
"""
    try:
        top_rows = try_query(top_q)
    except Exception:
        top_rows = []

    total_billed  = sum(int(r['bytes_billed']   or 0) for r in daily_rows)
    total_proc    = sum(int(r['bytes_processed'] or 0) for r in daily_rows)
    total_queries = sum(int(r['query_count']     or 0) for r in daily_rows)
    cost_usd = round(total_billed / 1e12 * 6.25, 4)

    daily = []
    for r in daily_rows:
        bb = int(r['bytes_billed'] or 0)
        daily.append({
            'day':         str(r['day']),
            'query_count': int(r['query_count'] or 0),
            'error_count': int(r['error_count'] or 0),
            'bytes_proc':  int(r['bytes_processed'] or 0),
            'bytes_billed': bb,
            'cost_usd':    round(bb / 1e12 * 6.25, 5),
        })

    top = []
    for r in (top_rows or []):
        bb = int(r['total_bytes_billed'] or 0)
        top.append({
            'day':          str(r['day']),
            'query':        r['query_preview'] or '',
            'bytes_billed': bb,
            'bytes_proc':   int(r['total_bytes_processed'] or 0),
            'cost_usd':     round(bb / 1e12 * 6.25, 5),
            'duration_ms':  int(r['duration_ms'] or 0),
        })

    return jsonify({
        'daily': daily,
        'top_queries': top,
        'totals': {
            'query_count':     total_queries,
            'bytes_processed': total_proc,
            'bytes_billed':    total_billed,
            'cost_usd':        cost_usd,
        },
        'source': used_src,
    })
