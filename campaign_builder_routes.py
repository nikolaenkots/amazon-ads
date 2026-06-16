import os
import json
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_from_directory
from google.cloud import bigquery

campaign_builder_bp = Blueprint('campaign_builder', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

PENDING_TABLES = {
    "MERCH": f"{PROJECT_ID}.{DATASET}.pending_changes_merch",
    "KDP":   f"{PROJECT_ID}.{DATASET}.pending_changes_kdp",
}


def _get_client():
    try:
        from bq_client import get_client
        return get_client()
    except ImportError:
        return bigquery.Client(project=PROJECT_ID)


def _get_profile_id(account_type, marketplace):
    secrets_path = os.path.join(BASE_DIR, 'config', 'amazon_secrets.json')
    with open(secrets_path) as f:
        amz = json.load(f)
    mkt = marketplace.upper()
    for p in amz.get('profiles', []):
        if p['type'] == account_type and p['marketplace'] == mkt:
            return str(p['id'])
    return ''


def _insert_pending(bq, table, rows):
    if not rows:
        return
    job = bq.load_table_from_json(
        rows, table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    )
    job.result()


@campaign_builder_bp.route('/campaign-builder')
def campaign_builder_page():
    return send_from_directory(BASE_DIR, 'campaign_builder.html')


@campaign_builder_bp.route('/campaign-builder/queue', methods=['POST'])
def campaign_builder_queue():
    """
    Принимает список кампаний (структура из таблицы Campaign Builder)
    и добавляет их в pending_changes как campaign_create.

    Каждая кампания → 1 строка в pending_changes:
      entity_type = 'campaign_create'
      new_value   = JSON:
        {
          type: 'auto'|'manual',
          name, budget, bidadj, portfolio, start, end,
          compneg: ['phrase1', 'phrase2', ...],   // campaign-level negatives
          groups: [{
            name, asin, bid,
            matchType: 'exact'|'phrase'|'broad',
            keywords: ['kw1','kw2',...],
            negatives: ['neg1','neg2',...]          // group-level negatives
          }]
        }

    send.py читает campaign_create и создаёт:
      1. POST /adsApi/v1/create/campaigns
      2. POST /adsApi/v1/create/campaigns/bidAdjustments (placementTop, если bidadj>0)
      3. POST /adsApi/v1/create/adGroups
      4. POST /adsApi/v1/create/ads (product ad на ASIN группы)
      5. POST /adsApi/v1/create/targets — keywords (MANUAL, matchType per group)
      6. POST /adsApi/v1/create/negativeTargets — group negatives (negativePhrase)
      7. POST /adsApi/v1/create/campaignNegativeTargets — campaign negatives
    """
    data         = request.get_json() or {}
    account_type = (data.get('account_type') or 'MERCH').upper()
    marketplace  = (data.get('marketplace')  or 'US').upper()
    campaigns    = data.get('campaigns', [])

    if not campaigns:
        return jsonify({"error": "Нет кампаний"}), 400

    profile_id = _get_profile_id(account_type, marketplace)
    if not profile_id:
        return jsonify({"error": f"Профиль {account_type}/{marketplace} не найден"}), 400

    bq    = _get_client()
    table = PENDING_TABLES.get(account_type)
    if not table:
        return jsonify({"error": f"Неизвестный account_type: {account_type}"}), 400

    now = datetime.now(tz=timezone.utc).isoformat()
    pending_rows = []
    names = []

    VALID_MT = {"exact", "phrase", "broad"}

    def _norm_date(v):
        """'20260520' or '2026-05-20' -> '2026-05-20'; '' -> ''"""
        from datetime import date as _date
        v = (v or '').strip()
        if not v:
            return ''
        s = v.replace('-', '')
        if not (len(s) == 8 and s.isdigit()):
            raise ValueError(f"Неверный формат даты: «{v}» — ожидается YYYYMMDD или YYYY-MM-DD")
        try:
            _date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            raise ValueError(f"Невалидная дата: «{v}»")
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"

    for camp in campaigns:
        camp_name = (camp.get('name') or '').strip()
        if not camp_name:
            continue

        groups = camp.get('groups') or []
        if not groups:
            continue

        clean_groups = []
        for g in groups:
            asin = (g.get('asin') or '').strip().upper()
            if not asin:
                continue
            mt = (g.get('matchType') or 'broad').lower()
            if mt not in VALID_MT:
                mt = 'broad'
            clean_groups.append({
                "name":      (g.get('name') or asin).strip(),
                "asin":      asin,
                "bid":       float(g.get('bid') or 0),
                "matchType": mt,
                "keywords":  [k.strip() for k in (g.get('keywords') or []) if k.strip()],
                "negatives": [n.strip() for n in (g.get('negatives') or []) if n.strip()],
            })

        if not clean_groups:
            continue

        try:
            start_date = _norm_date(camp.get('start'))
            end_date   = _norm_date(camp.get('end'))
        except ValueError as e:
            return jsonify({"error": f"Кампания «{camp_name}»: {e}"}), 400

        camp_obj = {
            "type":     "auto" if (camp.get('type') or '').lower() == "auto" else "manual",
            "name":     camp_name,
            "bidStrategy": camp.get('bidStrategy') or 'Dynamic bids - down only',
            "budget":   float(camp.get('budget') or 0),
            "bidadj":   int(camp.get('bidadj') or 0),
            "portfolio": camp.get('portfolio') or '',
            "start":    start_date,
            "end":      end_date,
            "compneg":  [n.strip() for n in (camp.get('compneg') or []) if n.strip()],
            "groups":   clean_groups,
        }

        row = {
            "id":           uuid.uuid4().hex,
            "created_at":   now,
            "entity_type":  "campaign_create",
            "entity_id":    uuid.uuid4().hex,
            "profile_id":   profile_id,
            "marketplace":  marketplace,
            "field_name":   "—",
            "old_value":    "",
            "new_value":    json.dumps(camp_obj, ensure_ascii=False),
            "status":       "PENDING",
            "error_msg":    "",
            "retry_count":  0,
        }
        pending_rows.append(row)
        names.append(f"{camp_obj['type'].upper()} — {camp_name} ({len(clean_groups)} групп)")

    if not pending_rows:
        return jsonify({"error": "Нет валидных кампаний (проверьте ASIN и группы)"}), 400

    try:
        _insert_pending(bq, table, pending_rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "ok":    True,
        "camps": len(pending_rows),
        "total": len(pending_rows),
        "names": names,
    })