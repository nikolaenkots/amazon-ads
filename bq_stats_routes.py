from bq_client import get_client
import os
from flask import Blueprint, jsonify, send_from_directory

bq_stats_bp = Blueprint('bq_stats', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"
REGION     = "us"  # INFORMATION_SCHEMA uses region-us prefix


@bq_stats_bp.route('/bq-stats')
def bq_stats_page():
    return send_from_directory(BASE_DIR, 'bq_stats.html')


@bq_stats_bp.route('/bq-stats/storage')
def bq_storage():
    """Размер таблиц в датасете"""
    try:
        client = get_client()
        query = f"""
SELECT
  table_name,
  total_rows,
  total_logical_bytes,
  total_physical_bytes,
  last_modified_time
FROM `{PROJECT_ID}.region-{REGION}.INFORMATION_SCHEMA.TABLE_STORAGE`
WHERE table_schema = '{DATASET}'
ORDER BY total_logical_bytes DESC
"""
        rows = list(client.query(query).result())
        tables = []
        total_logical = 0
        total_physical = 0
        for r in rows:
            lb = int(r['total_logical_bytes'] or 0)
            pb = int(r['total_physical_bytes'] or 0)
            total_logical  += lb
            total_physical += pb
            tables.append({
                'name':           r['table_name'],
                'rows':           int(r['total_rows'] or 0),
                'logical_bytes':  lb,
                'physical_bytes': pb,
                'logical_gb':     round(lb / 1e9, 3),
                'physical_gb':    round(pb / 1e9, 3),
                'last_modified':  r['last_modified_time'].isoformat() if r['last_modified_time'] else None,
            })
        return jsonify({
            'tables': tables,
            'total_logical_gb':  round(total_logical  / 1e9, 3),
            'total_physical_gb': round(total_physical / 1e9, 3),
            'total_logical_bytes':  total_logical,
            'total_physical_bytes': total_physical,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bq_stats_bp.route('/bq-stats/jobs')
def bq_jobs():
    """История запросов за последние 30 дней из INFORMATION_SCHEMA.JOBS"""
    try:
        client = get_client()
        # Дневная агрегация
        daily_query = f"""
SELECT
  DATE(creation_time, 'America/New_York') AS day,
  COUNT(*) AS query_count,
  COUNTIF(error_result IS NOT NULL) AS error_count,
  SUM(total_bytes_processed) AS bytes_processed,
  SUM(total_bytes_billed)    AS bytes_billed,
  SUM(total_slot_ms)         AS slot_ms,
  AVG(TIMESTAMP_DIFF(end_time, start_time, MILLISECOND)) AS avg_duration_ms
FROM `{PROJECT_ID}.region-{REGION}.INFORMATION_SCHEMA.JOBS`
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND job_type = 'QUERY'
  AND statement_type != 'SCRIPT'
GROUP BY 1
ORDER BY 1 DESC
"""
        daily_rows = list(client.query(daily_query).result())

        # Топ 20 самых дорогих запросов за 7 дней
        top_query = f"""
SELECT
  DATE(creation_time, 'America/New_York') AS day,
  LEFT(query, 120) AS query_preview,
  total_bytes_billed,
  total_bytes_processed,
  total_slot_ms,
  TIMESTAMP_DIFF(end_time, start_time, MILLISECOND) AS duration_ms,
  user_email
FROM `{PROJECT_ID}.region-{REGION}.INFORMATION_SCHEMA.JOBS`
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND job_type = 'QUERY'
  AND statement_type != 'SCRIPT'
  AND error_result IS NULL
  AND total_bytes_billed > 0
ORDER BY total_bytes_billed DESC
LIMIT 20
"""
        top_rows = list(client.query(top_query).result())

        # Итого за 30 дней
        total_bytes  = sum(int(r['bytes_billed'] or 0) for r in daily_rows)
        total_proc   = sum(int(r['bytes_processed'] or 0) for r in daily_rows)
        total_queries = sum(int(r['query_count'] or 0) for r in daily_rows)
        # $6.25 per TB on-demand (us region)
        cost_usd = round(total_bytes / 1e12 * 6.25, 4)

        daily = []
        for r in daily_rows:
            bb = int(r['bytes_billed'] or 0)
            daily.append({
                'day':          str(r['day']),
                'query_count':  int(r['query_count'] or 0),
                'error_count':  int(r['error_count'] or 0),
                'bytes_billed': bb,
                'bytes_proc':   int(r['bytes_processed'] or 0),
                'tb_billed':    round(bb / 1e12, 6),
                'cost_usd':     round(bb / 1e12 * 6.25, 5),
                'slot_ms':      int(r['slot_ms'] or 0),
                'avg_ms':       round(float(r['avg_duration_ms'] or 0), 0),
            })

        top = []
        for r in top_rows:
            bb = int(r['total_bytes_billed'] or 0)
            top.append({
                'day':          str(r['day']),
                'query':        r['query_preview'] or '',
                'bytes_billed': bb,
                'tb_billed':    round(bb / 1e12, 6),
                'cost_usd':     round(bb / 1e12 * 6.25, 5),
                'duration_ms':  int(r['duration_ms'] or 0),
                'user':         r['user_email'] or '',
            })

        return jsonify({
            'daily': daily,
            'top_queries': top,
            'totals': {
                'query_count':     total_queries,
                'bytes_billed':    total_bytes,
                'bytes_processed': total_proc,
                'tb_billed':       round(total_bytes / 1e12, 6),
                'cost_usd':        cost_usd,
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
