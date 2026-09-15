"""
dashboard_routes.py — данные для сводки на главной.

Главная страница показывает сводную таблицу по портфолио: сколько каждое
портфолио потратило и заработало за период, с изменением к предыдущему такому
же периоду. Переключатели — аккаунт (MERCH/KDP) и страна («все страны одной
строкой», «разбить по странам» или конкретный маркетплейс).

Endpoints:
  GET /dashboard/portfolios — сводка по портфолио + итоги + статус загрузок
"""

import decimal
import json
import os
from datetime import date, timedelta

from flask import Blueprint, request, jsonify

from bq_client import get_client
from settings import PROJECT_ID, DATASET

dashboard_bp = Blueprint('dashboard', __name__)

PAGE_DIR   = os.path.dirname(os.path.abspath(__file__))
BASE_DIR   = os.path.dirname(PAGE_DIR)
# PROJECT_ID и DATASET берутся из settings.py (config/settings.json)

AUTO_LOG = os.path.join(BASE_DIR, 'auto_collect_log.json')
SYNC_LOG = os.path.join(BASE_DIR, 'campaigns_sync_log.json')


def _cvt(v):
    return float(v) if isinstance(v, decimal.Decimal) else v


def _rows(job):
    return [{k: _cvt(v) for k, v in dict(r).items()} for r in job.result()]


def _q(s):
    return str(s).replace("'", "''")


def _parse_date(s, default):
    try:
        y, m, d = (int(x) for x in str(s).split('-'))
        return date(y, m, d)
    except Exception:
        return default


def _last_run(path):
    """Когда и чем закончилась последняя запись в файле истории."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    rec = data[0]
    return {
        "at":     rec.get('finished_at') or rec.get('started_at') or rec.get('at'),
        "status": rec.get('status') or '',
        "note":   rec.get('note') or rec.get('message') or '',
        "profile": rec.get('profile') or rec.get('marketplace') or '',
    }


@dashboard_bp.route('/dashboard/portfolios')
def dashboard_portfolios():
    """Сводка по портфолио за период и изменение к предыдущему периоду."""
    account_type = request.args.get('account_type', 'MERCH').upper()
    marketplace  = request.args.get('marketplace', '').upper()   # '' — все страны
    by_country   = request.args.get('by_country', '') == '1'
    active_only  = request.args.get('active_only', '1') == '1'

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400

    today = date.today()
    dt = _parse_date(request.args.get('date_to'),   today - timedelta(days=1))
    df = _parse_date(request.args.get('date_from'), dt - timedelta(days=29))
    if df > dt:
        df, dt = dt, df
    span      = (dt - df).days + 1          # длина периода в днях
    prev_to   = df - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span - 1)

    suffix     = account_type.lower()
    camp_table = f"{PROJECT_ID}.{DATASET}.campaigns_{suffix}"
    stat_table = f"{PROJECT_ID}.{DATASET}.targets_stats_{suffix}"
    pf_table   = f"{PROJECT_ID}.{DATASET}.portfolio_labels"

    camp_conds = []
    if marketplace:
        camp_conds.append(f"marketplace = '{_q(marketplace)}'")
    if active_only:
        camp_conds.append("campaign_state = 'ENABLED'")
    camp_where = ('AND ' + ' AND '.join(camp_conds)) if camp_conds else ''

    # строки: либо портфолио целиком, либо портфолио × страна
    group_key = "c.marketplace" if by_country else "''"

    sql = f"""
    WITH camps AS (
      SELECT campaign_id, marketplace, portfolio_id, portfolio_name, campaign_state FROM (
        SELECT campaign_id, marketplace, portfolio_id, portfolio_name, campaign_state,
               ROW_NUMBER() OVER (PARTITION BY campaign_id, marketplace
                                  ORDER BY synced_at DESC) rn
        FROM `{camp_table}`
        WHERE entity_type = 'campaign' {camp_where}
      ) WHERE rn = 1
    ),
    named AS (
      SELECT c.campaign_id, c.marketplace, c.campaign_state,
             COALESCE(pl.portfolio_name, c.portfolio_name, '— без портфолио —') AS portfolio,
             c.portfolio_id
      FROM camps c
      LEFT JOIN `{pf_table}` pl
        ON pl.portfolio_id = c.portfolio_id
       AND pl.marketplace  = c.marketplace
       AND pl.account_type = '{account_type}'
    )
    SELECT
      c.portfolio,
      {group_key} AS marketplace,
      COUNT(DISTINCT c.campaign_id) AS campaigns,
      -- текущий период
      COALESCE(SUM(IF(s.date >= '{df}', s.impressions,   0)), 0) AS impressions,
      COALESCE(SUM(IF(s.date >= '{df}', s.clicks,        0)), 0) AS clicks,
      ROUND(COALESCE(SUM(IF(s.date >= '{df}', s.cost,      0)), 0), 2) AS cost,
      ROUND(COALESCE(SUM(IF(s.date >= '{df}', s.sales_14d, 0)), 0), 2) AS sales,
      COALESCE(SUM(IF(s.date >= '{df}', s.purchases_14d, 0)), 0) AS orders,
      -- предыдущий период такой же длины
      ROUND(COALESCE(SUM(IF(s.date <  '{df}', s.cost,      0)), 0), 2) AS prev_cost,
      ROUND(COALESCE(SUM(IF(s.date <  '{df}', s.sales_14d, 0)), 0), 2) AS prev_sales,
      COALESCE(SUM(IF(s.date <  '{df}', s.purchases_14d, 0)), 0) AS prev_orders
    FROM named c
    LEFT JOIN `{stat_table}` s
      ON s.campaign_id = c.campaign_id
     AND s.marketplace = c.marketplace
     AND s.date BETWEEN '{prev_from}' AND '{dt}'
    GROUP BY c.portfolio, marketplace
    ORDER BY cost DESC
    """

    try:
        rows = _rows(get_client().query(sql))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # производные показатели считаем на месте: в SQL это лишние CASE
    for r in rows:
        cost, sales = r.get('cost') or 0, r.get('sales') or 0
        impr, clicks = r.get('impressions') or 0, r.get('clicks') or 0
        r['acos'] = round(cost / sales * 100, 1) if sales else None
        r['ctr']  = round(clicks / impr * 100, 3) if impr else None
        r['profit'] = round(sales - cost, 2)

    total = {
        "campaigns":  sum(r.get('campaigns') or 0 for r in rows),
        "impressions": sum(r.get('impressions') or 0 for r in rows),
        "clicks":     sum(r.get('clicks') or 0 for r in rows),
        "cost":       round(sum(r.get('cost') or 0 for r in rows), 2),
        "sales":      round(sum(r.get('sales') or 0 for r in rows), 2),
        "orders":     sum(r.get('orders') or 0 for r in rows),
        "prev_cost":  round(sum(r.get('prev_cost') or 0 for r in rows), 2),
        "prev_sales": round(sum(r.get('prev_sales') or 0 for r in rows), 2),
        "prev_orders": sum(r.get('prev_orders') or 0 for r in rows),
    }
    total['acos'] = round(total['cost'] / total['sales'] * 100, 1) if total['sales'] else None
    total['ctr']  = (round(total['clicks'] / total['impressions'] * 100, 3)
                     if total['impressions'] else None)
    total['profit'] = round(total['sales'] - total['cost'], 2)

    return jsonify({
        "rows":  rows,
        "total": total,
        "period": {"from": str(df), "to": str(dt),
                   "prev_from": str(prev_from), "prev_to": str(prev_to), "days": span},
        "jobs": {                       # когда последний раз обновлялись данные
            "stats": _last_run(AUTO_LOG),
            "sync":  _last_run(SYNC_LOG),
        },
    })
