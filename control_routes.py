"""
control_routes.py — Blueprint для записи изменений в pending_changes.

Все изменения НЕ отправляются сразу в Amazon.
Они пишутся в pending_changes со статусом PENDING.
После одобрения через /control/approve — запускается send.py.

Endpoints:
  POST /control/add          — добавить изменение
  POST /control/approve      — одобрить (PENDING → APPROVED)
  POST /control/reject       — отклонить (PENDING → REJECTED)
  POST /control/send         — запустить send.py для APPROVED
  GET  /control/pending      — список ожидающих изменений
  GET  /control/log          — история отправленных
"""

import os
import json
import uuid
import subprocess
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from google.cloud import bigquery

control_bp = Blueprint('control', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"

AMZ_SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'amazon_secrets.json')
with open(AMZ_SECRETS_PATH) as _f:
    _AMZ = json.load(_f)

PENDING_TABLES = {
    "MERCH": f"{PROJECT_ID}.{DATASET}.pending_changes_merch",
    "KDP":   f"{PROJECT_ID}.{DATASET}.pending_changes_kdp",
}
CHANGELOG_TABLES = {
    "MERCH": f"{PROJECT_ID}.{DATASET}.change_log_merch",
    "KDP":   f"{PROJECT_ID}.{DATASET}.change_log_kdp",
}
CAMPAIGNS_TABLES = {
    "MERCH": f"{PROJECT_ID}.{DATASET}.campaigns_merch",
    "KDP":   f"{PROJECT_ID}.{DATASET}.campaigns_kdp",
}

# Допустимые операции: entity_type → [field_name]
ALLOWED_OPS = {
    "campaign":       ["state", "name", "daily_budget", "portfolio_id", "end_date"],
    "ad_group":       ["state", "name", "default_bid"],
    "keyword":        ["state", "bid"],
    "target":         ["state", "bid"],   # авто-таргеты (KEYWORDS_CLOSE_MATCH и т.д.)
    "keyword_add":    ["—"],   # new_value = JSON {text, match_type, bid, ad_group_id, campaign_id}
    "negative_add":   ["—"],   # new_value = JSON {text, match_type, ad_group_id, campaign_id}
    "negative_delete":    ["—"],   # entity_id = keyword_id минус слова
    "negative_product_add":["—"], # new_value = JSON {asin, ad_group_id, campaign_id}
    "ad_group_add":       ["—"],  # new_value = JSON {name, default_bid, campaign_id}
    "product_ad_add":     ["—"],  # new_value = JSON {asin, campaign_id, ad_group_id?, ad_group_name?}
    "product_ad":         ["state"],
    "campaign_delete":    ["—"],   # entity_id = campaign_id, удаление кампании целиком
}

LABELS = {
    ("campaign",  "state"):        lambda nv: "▶ Запуск" if nv == "ENABLED" else "⏸ Пауза",
    ("campaign",  "name"):         lambda nv: f'✏️ Переименовать → "{nv}"',
    ("campaign",  "daily_budget"): lambda nv: f'💰 Бюджет → ${nv}',
    ("campaign",  "portfolio_id"): lambda nv: f'📁 Портфолио → {nv}',
    ("campaign",  "end_date"):     lambda nv: f'📅 Дата окончания → {nv if nv else "без даты"}',
    ("ad_group",  "state"):        lambda nv: "▶ Запуск группы" if nv == "ENABLED" else "⏸ Пауза группы",
    ("ad_group",  "name"):         lambda nv: f'✏️ Переименовать группу → "{nv}"',
    ("ad_group",  "default_bid"):  lambda nv: f'🎯 Ставка группы → ${nv}',
    ("keyword",   "state"):        lambda nv: "▶ Включить kw" if nv == "ENABLED" else "⏸ Выключить kw",
    ("keyword",   "bid"):          lambda nv: f'🎯 Ставка kw → ${nv}',
    ("target",    "state"):        lambda nv: "▶ Включить таргет" if nv == "ENABLED" else "⏸ Выключить таргет",
    ("target",    "bid"):          lambda nv: f'🎯 Ставка таргета → ${nv}',
    ("keyword_add",    "—"):       lambda nv: f'➕ Добавить kw: {nv[:60]}',
    ("negative_add",   "—"):       lambda nv: f'🚫 Добавить минус: {nv[:60]}',
    ("negative_delete","—"):       lambda nv: '🗑️ Удалить минус слово',
    ("negative_product_add","—"):  lambda nv: f'🚫 Минус ASIN: {nv[:60]}',
    ("ad_group_add","—"):          lambda nv: f'➕ Новая группа: {nv[:60]}',
    ("product_ad",  "state"):       lambda nv: "▶ Включить объявление" if nv == "ENABLED" else "⏸ Выключить объявление",
    ("product_ad_add","—"):         lambda nv: f'🖼 Объявление ASIN: {nv[:60]}',
    ("campaign_delete","—"):        lambda nv: '🗑️ Удалить кампанию',
}


def get_label(entity_type, field_name, new_value):
    fn = LABELS.get((entity_type, field_name))
    if fn:
        try: return fn(new_value)
        except: pass
    return f"{entity_type}/{field_name} → {new_value[:40]}"


# ── POST /control/add ────────────────────────────────────
@control_bp.route('/control')
def control_page():
    from flask import send_from_directory
    return send_from_directory(BASE_DIR, 'control.html')


@control_bp.route('/control/profiles')
def get_profiles():
    """Возвращает маппинг acct_marketplace → profile_id для фронтенда"""
    profiles = {}
    for p in _AMZ.get("profiles", []):
        key = f"{p['type']}_{p['marketplace']}"
        profiles[key] = str(p["id"])
    return jsonify({"profiles": profiles})


@control_bp.route('/control/add', methods=['POST'])
def add_change():
    """
    Добавить изменение в очередь.

    Body JSON:
      account_type  MERCH | KDP
      marketplace   US | UK | ...
      profile_id    STRING
      entity_type   campaign | ad_group | keyword | keyword_add | negative_add | negative_delete
      entity_id     STRING  (campaign_id / ad_group_id / keyword_id)
      field_name    state | name | daily_budget | bid | — (для add/delete)
      old_value     STRING  (текущее значение, для отображения)
      new_value     STRING  (новое значение, для keyword_add/negative_add — JSON строка)
    """
    data = request.get_json()

    account_type = (data.get('account_type') or '').upper()
    marketplace  = (data.get('marketplace')  or '').upper()
    profile_id   = str(data.get('profile_id') or '')
    entity_type  = data.get('entity_type', '')
    entity_id    = str(data.get('entity_id') or '')
    field_name   = data.get('field_name', '—')
    old_value    = str(data.get('old_value') or '')
    new_value    = str(data.get('new_value') or '')

    # Валидация
    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400
    if entity_type not in ALLOWED_OPS:
        return jsonify({"error": f"Неизвестный entity_type: {entity_type}"}), 400
    if not entity_id:
        return jsonify({"error": "entity_id обязателен"}), 400
    # Для end_date пустое значение = удалить дату, это допустимо
    if not new_value and not (entity_type == "campaign" and field_name == "end_date"):
        return jsonify({"error": "new_value обязателен"}), 400

    bq = bigquery.Client(project=PROJECT_ID)
    table = PENDING_TABLES[account_type]

    # Для операций добавления разрешаем несколько записей (несколько минусов/ключей в одну группу)
    NO_DUP_CHECK = {'keyword_add', 'negative_add', 'negative_product_add', 'ad_group_add', 'product_ad_add', 'campaign_delete'}
    if entity_type not in NO_DUP_CHECK:
        fn_clause = f"AND field_name = '{field_name}'" if field_name != '—' else ''
        dup_sql = f"""
        SELECT COUNT(*) as cnt FROM `{table}`
        WHERE entity_id = '{entity_id}'
          AND entity_type = '{entity_type}'
          {fn_clause}
          AND status IN ('PENDING', 'APPROVED')
        """
        dup_count = list(bq.query(dup_sql).result())[0].cnt
        if dup_count > 0:
            return jsonify({"error": "Уже есть ожидающее изменение для этого объекта"}), 409

    row = {
        "id":          str(uuid.uuid4()),
        "created_at":  datetime.now(tz=timezone.utc).isoformat(),
        "entity_type": entity_type,
        "entity_id":   entity_id,
        "profile_id":  profile_id,
        "marketplace": marketplace,
        "field_name":  field_name,
        "old_value":   old_value,
        "new_value":   new_value,
        "status":      "PENDING",
        "error_msg":   None,
        "retry_count": 0,
    }

    job = bq.load_table_from_json(
        [row], table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    )
    job.result()

    return jsonify({
        "success": True,
        "id": row["id"],
        "label": get_label(entity_type, field_name, new_value),
    })


# ── POST /control/add_batch ──────────────────────────────
@control_bp.route('/control/add_batch', methods=['POST'])
def add_change_batch():
    """
    Добавить несколько изменений одним запросом.
    Body: {"items": [...]}  — каждый элемент как в /control/add
    Только для NO_DUP_CHECK типов (keyword_add, negative_add, negative_product_add, product_ad_add).
    """
    data  = request.get_json()
    items = data.get('items', [])
    if not items:
        return jsonify({"error": "items обязателен"}), 400
    if len(items) > 500:
        return jsonify({"error": "Максимум 500 элементов за раз"}), 400

    NO_DUP_CHECK = {'keyword_add', 'negative_add', 'negative_product_add', 'ad_group_add', 'product_ad_add', 'campaign_delete'}

    rows = []
    now  = datetime.now(tz=timezone.utc).isoformat()
    account_type = None
    errors = []

    for i, item in enumerate(items):
        at  = (item.get('account_type') or '').upper()
        et  = item.get('entity_type', '')
        eid = str(item.get('entity_id') or '')
        pid = str(item.get('profile_id') or '')
        mkt = (item.get('marketplace') or '').upper()
        fn  = item.get('field_name', '—')
        ov  = str(item.get('old_value') or '')
        nv  = str(item.get('new_value') or '')

        if at not in ('MERCH', 'KDP'):
            errors.append({"index": i, "error": "Неверный account_type"})
            continue
        if et not in ALLOWED_OPS:
            errors.append({"index": i, "error": f"Неизвестный entity_type: {et}"})
            continue
        if et not in NO_DUP_CHECK:
            errors.append({"index": i, "error": f"{et} не поддерживается в batch"})
            continue
        if not eid or not nv:
            errors.append({"index": i, "error": "entity_id и new_value обязательны"})
            continue

        account_type = at
        rows.append({
            "id":          str(uuid.uuid4()),
            "created_at":  now,
            "entity_type": et,
            "entity_id":   eid,
            "profile_id":  pid,
            "marketplace": mkt,
            "field_name":  fn,
            "old_value":   ov,
            "new_value":   nv,
            "status":      "PENDING",
            "error_msg":   None,
            "retry_count": 0,
        })

    if not rows:
        return jsonify({"error": "Нет валидных элементов", "errors": errors}), 400

    table = PENDING_TABLES[account_type]
    bq    = bigquery.Client(project=PROJECT_ID)
    job   = bq.load_table_from_json(
        rows, table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    )
    job.result()

    return jsonify({
        "success":   True,
        "inserted":  len(rows),
        "errors":    errors,
        "ids":       [r["id"] for r in rows],
    })


# ── POST /control/approve ─────────────────────────────────
@control_bp.route('/control/approve', methods=['POST'])
def approve_changes():
    """
    Одобрить изменения (PENDING → APPROVED).
    Body: {account_type, ids: [id1, id2, ...]}
    """
    data = request.get_json()
    account_type = (data.get('account_type') or '').upper()
    ids = data.get('ids', [])

    if not ids:
        return jsonify({"error": "ids обязателен"}), 400

    bq    = bigquery.Client(project=PROJECT_ID)
    table = PENDING_TABLES[account_type]
    id_list = ','.join(f"'{i}'" for i in ids)
    bq.query(f"UPDATE `{table}` SET status='APPROVED' WHERE id IN ({id_list}) AND status='PENDING'").result()

    return jsonify({"success": True, "approved": len(ids)})


# ── POST /control/reject ──────────────────────────────────
@control_bp.route('/control/reject', methods=['POST'])
def reject_changes():
    """
    Отклонить изменения (PENDING/APPROVED → REJECTED).
    Body: {account_type, ids: [id1, id2, ...]}
    """
    data = request.get_json()
    account_type = (data.get('account_type') or '').upper()
    ids = data.get('ids', [])

    if not ids:
        return jsonify({"error": "ids обязателен"}), 400

    bq    = bigquery.Client(project=PROJECT_ID)
    table = PENDING_TABLES[account_type]
    id_list = ','.join(f"'{i}'" for i in ids)
    bq.query(f"UPDATE `{table}` SET status='REJECTED' WHERE id IN ({id_list})").result()

    return jsonify({"success": True, "rejected": len(ids)})


# ── POST /control/send ────────────────────────────────────
@control_bp.route('/control/send', methods=['POST'])
def send_approved():
    """
    Запустить send.py для APPROVED изменений.
    Body: {account_type, marketplace?}
    Запускает в фоновом потоке, возвращает job_id.
    """
    import threading

    data         = request.get_json() or {}
    account_type = (data.get('account_type') or 'MERCH').upper()
    marketplace  = data.get('marketplace', '')

    import app as main_app
    job_id = str(uuid.uuid4())

    def run():
        try:
            main_app.progress_store[job_id] = {"status": "running", "log": []}
            cmd = ["python3", os.path.join(BASE_DIR, "send.py"),
                   "--account", account_type]
            if marketplace:
                cmd += ["--marketplace", marketplace]

            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=BASE_DIR
            )
            output = result.stdout + result.stderr
            main_app.progress_store[job_id] = {
                "status": "done" if result.returncode == 0 else "error",
                "log":    output.strip().split("\n"),
                "returncode": result.returncode,
            }
        except Exception as e:
            main_app.progress_store[job_id] = {"status": "error", "log": [str(e)]}

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── GET /control/send/status/<job_id> ─────────────────────
@control_bp.route('/control/send/status/<job_id>')
def send_status(job_id):
    import app as main_app
    info = main_app.progress_store.get(job_id)
    if not info:
        return jsonify({"status": "not_found"}), 404
    return jsonify(info)


# ── GET /control/pending ──────────────────────────────────
@control_bp.route('/control/pending')
def get_pending():
    """
    Список изменений ожидающих одобрения.
    ?account_type=MERCH&status=PENDING&marketplace=US&limit=100
    """
    account_type = request.args.get('account_type', 'MERCH').upper()
    status       = request.args.get('status', 'PENDING')
    marketplace  = request.args.get('marketplace', '')
    limit        = min(int(request.args.get('limit', 200)), 500)

    if account_type not in ('MERCH', 'KDP'):
        return jsonify({"error": "Неверный account_type"}), 400

    bq    = bigquery.Client(project=PROJECT_ID)
    table = PENDING_TABLES[account_type]
    camp_table = CAMPAIGNS_TABLES[account_type]

    where = f"WHERE status = '{status}'"
    if marketplace:
        where += f" AND marketplace = '{marketplace}'"

    sql = f"""
    SELECT id, created_at, entity_type, entity_id, profile_id, marketplace,
           field_name, old_value, new_value, status, error_msg, retry_count
    FROM `{table}`
    {where}
    ORDER BY created_at DESC
    LIMIT {limit}
    """

    rows = []
    for r in bq.query(sql).result():
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, 'isoformat'): d[k] = v.isoformat()
        d["label"] = get_label(d["entity_type"], d.get("field_name","—"), d.get("new_value",""))
        rows.append(d)

    if not rows:
        return jsonify({"rows": [], "total": 0})

    # ── Подтянуть названия объектов из campaigns_merch ──────
    # Группируем entity_id по типу
    by_type = {}
    for r in rows:
        et = r["entity_type"]
        eid = r["entity_id"]
        by_type.setdefault(et, set()).add(eid)

    name_map = {}  # entity_id → display_name

    def fetch_names(id_set, id_col, name_col, extra_where=""):
        if not id_set: return
        ids = ','.join(f"'{i}'" for i in id_set)
        try:
            result = bq.query(f"""
                SELECT DISTINCT {id_col} AS eid, {name_col} AS name
                FROM `{camp_table}`
                WHERE {id_col} IN ({ids}) {extra_where}
                LIMIT 500
            """).result()
            for row in result:
                if row.eid and row.name:
                    name_map[row.eid] = row.name
        except Exception:
            pass

    # Кампании → campaign_name
    camp_ids = by_type.get("campaign", set()) | by_type.get("campaign_delete", set())
    if camp_ids:
        fetch_names(camp_ids, "campaign_id", "campaign_name",
                    "AND entity_type = 'campaign'")

    # Группы → ad_group_name
    ag_ids = by_type.get("ad_group", set())
    if ag_ids:
        fetch_names(ag_ids, "ad_group_id", "ad_group_name",
                    "AND entity_type = 'ad_group'")

    # Ключевые слова → keyword_text
    kw_ids = by_type.get("keyword", set()) | by_type.get("keyword_add", set())
    # Для keyword_add entity_id = ad_group_id, поэтому new_value содержит текст
    # Для keyword → keyword_id
    real_kw_ids = by_type.get("keyword", set())
    if real_kw_ids:
        fetch_names(real_kw_ids, "keyword_id", "keyword_text",
                    "AND entity_type = 'keyword'")

    # Минус слова → keyword_text
    neg_ids = by_type.get("negative_delete", set())
    if neg_ids:
        fetch_names(neg_ids, "keyword_id", "keyword_text",
                    "AND entity_type = 'negative_keyword'")

    # Авто-таргеты → targeting_expression
    tgt_ids = by_type.get("target", set())
    if tgt_ids:
        fetch_names(tgt_ids, "target_id", "targeting_expression",
                    "AND entity_type = 'product_targeting'")

    # Объявления → asin
    ad_ids = by_type.get("product_ad", set())
    if ad_ids:
        fetch_names(ad_ids, "ad_id", "asin",
                    "AND entity_type = 'product_ad'")

    # _add типы: entity_id = ad_group_id → подтягиваем ad_group_name
    neg_add_ids = (by_type.get("keyword_add", set()) |
                   by_type.get("negative_add", set()) |
                   by_type.get("negative_product_add", set()) |
                   by_type.get("product_ad_add", set()))
    if neg_add_ids:
        fetch_names(neg_add_ids, "ad_group_id", "ad_group_name",
                    "AND entity_type = 'ad_group'")

    # ad_group_add: entity_id = campaign_id → campaign_name
    add_camp_ids = by_type.get("ad_group_add", set()) - camp_ids
    if add_camp_ids:
        fetch_names(add_camp_ids, "campaign_id", "campaign_name",
                    "AND entity_type = 'campaign'")

    # ── context_map: campaign_name для кампаний, ad_group_name для остального ──
    # Сущности уровня кампании
    CAMP_LEVEL = {"campaign", "ad_group_add"}
    # Сущности уровня группы (entity_id = ad_group_id)
    GROUP_LEVEL = {"ad_group", "keyword", "target",
                   "keyword_add", "negative_add", "negative_product_add", "product_ad_add",
                   "negative_keyword", "negative_product_targeting", "negative_delete"}

    context_map = {}  # entity_id → context_name

    # Для кампаний: entity_id = campaign_id → campaign_name
    ctx_camp_ids = set()
    for r in rows:
        et = r["entity_type"]
        if et in CAMP_LEVEL:
            ctx_camp_ids.add(r["entity_id"])
        elif et in GROUP_LEVEL:
            # для group-level entity_id может быть keyword_id/target_id/ad_group_id
            # нужно найти campaign через ad_group
            pass

    def fetch_context_names(id_set, id_col, name_col, extra_where=""):
        if not id_set: return {}
        ids = ','.join(f"'{i}'" for i in id_set)
        result = {}
        try:
            for row in bq.query(f"""
                SELECT DISTINCT {id_col} AS eid, {name_col} AS name
                FROM `{camp_table}`
                WHERE {id_col} IN ({ids}) {extra_where}
                LIMIT 500
            """).result():
                if row.eid and row.name:
                    result[row.eid] = row.name
        except Exception:
            pass
        return result

    # campaign-level: campaign_name
    if ctx_camp_ids:
        context_map.update(fetch_context_names(
            ctx_camp_ids, "campaign_id", "campaign_name", "AND entity_type='campaign'"))

    # group-level: ad_group_name (когда entity_id = ad_group_id)
    ctx_ag_direct = set()
    for r in rows:
        et = r["entity_type"]
        if et in {"ad_group", "keyword_add", "negative_add",
                  "negative_product_add", "product_ad_add"}:
            ctx_ag_direct.add(r["entity_id"])
    if ctx_ag_direct:
        context_map.update(fetch_context_names(
            ctx_ag_direct, "ad_group_id", "ad_group_name", "AND entity_type='ad_group'"))

    # keyword/target/negative_delete: entity_id = keyword_id/target_id
    # нужно найти их ad_group через campaigns таблицу
    ctx_kw_ids = set()
    ctx_tgt_ids = set()
    ctx_neg_ids = set()
    for r in rows:
        et = r["entity_type"]
        if et == "keyword":      ctx_kw_ids.add(r["entity_id"])
        elif et == "target":     ctx_tgt_ids.add(r["entity_id"])
        elif et == "negative_delete": ctx_neg_ids.add(r["entity_id"])

    def fetch_parent_group(id_set, id_col, extra_where=""):
        """Для keyword_id/target_id найти ad_group_name через ad_group_id в campaigns таблицу"""
        if not id_set: return {}
        ids = ','.join(f"'{i}'" for i in id_set)
        result = {}
        try:
            for row in bq.query(f"""
                SELECT DISTINCT t.{id_col} AS eid, ag.ad_group_name AS name
                FROM `{camp_table}` t
                JOIN `{camp_table}` ag
                  ON ag.ad_group_id = t.ad_group_id
                 AND ag.entity_type = 'ad_group'
                 AND ag.marketplace = t.marketplace
                WHERE t.{id_col} IN ({ids}) {extra_where}
                LIMIT 500
            """).result():
                if row.eid and row.name:
                    result[row.eid] = row.name
        except Exception:
            pass
        return result

    if ctx_kw_ids:
        context_map.update(fetch_parent_group(
            ctx_kw_ids, "keyword_id", "AND t.entity_type='keyword'"))
    if ctx_tgt_ids:
        context_map.update(fetch_parent_group(
            ctx_tgt_ids, "target_id", "AND t.entity_type='product_targeting'"))
    if ctx_neg_ids:
        context_map.update(fetch_parent_group(
            ctx_neg_ids, "keyword_id", "AND t.entity_type='negative_keyword'"))

    # ── Добавляем entity_name и context_name в каждую строку ──
    for r in rows:
        et  = r["entity_type"]
        eid = r["entity_id"]
        name = name_map.get(eid)

        # Для keyword_add / negative_add / negative_product_add — берём текст из new_value JSON
        if not name and et in ("keyword_add", "negative_add", "negative_product_add", "product_ad_add"):
            try:
                v = json.loads(r.get("new_value", "{}"))
                name = v.get("text") or v.get("asin")
            except Exception:
                pass

        r["entity_name"]   = name or ""
        r["context_name"]  = context_map.get(eid) or ""

    return jsonify({"rows": rows, "total": len(rows)})


# ── GET /control/log ──────────────────────────────────────
@control_bp.route('/control/log')
def get_log():
    """
    История отправленных изменений.
    ?account_type=MERCH&marketplace=US&limit=100&result=SUCCESS
    """
    account_type = request.args.get('account_type', 'MERCH').upper()
    marketplace  = request.args.get('marketplace', '')
    result_filter= request.args.get('result', '')
    limit        = min(int(request.args.get('limit', 100)), 500)

    bq    = bigquery.Client(project=PROJECT_ID)
    table = CHANGELOG_TABLES[account_type]

    conds = []
    if marketplace:    conds.append(f"marketplace = '{marketplace}'")
    if result_filter:  conds.append(f"result = '{result_filter}'")
    where = ('WHERE ' + ' AND '.join(conds)) if conds else ''

    sql = f"""
    SELECT id, pending_id, sent_at, entity_type, entity_id, marketplace,
           field_name, old_value, new_value, result, error_msg
    FROM `{table}`
    {where}
    ORDER BY sent_at DESC
    LIMIT {limit}
    """

    rows = []
    for r in bq.query(sql).result():
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, 'isoformat'): d[k] = v.isoformat()
        d["label"] = get_label(d["entity_type"], d.get("field_name","—"), d.get("new_value",""))
        d["entity_name"] = ""
        rows.append(d)

    # Подтянуть названия из campaigns
    if rows:
        camp_table_log = CAMPAIGNS_TABLES[account_type]
        by_type_log = {}
        for r in rows:
            by_type_log.setdefault(r["entity_type"], set()).add(r["entity_id"])

        name_map_log = {}
        TYPE_QUERY = {
            "campaign":        ("campaign_id",   "campaign_name",        "entity_type = 'campaign'"),
            "ad_group":        ("ad_group_id",   "ad_group_name",        "entity_type = 'ad_group'"),
            "keyword":         ("keyword_id",    "keyword_text",         "entity_type = 'keyword'"),
            "target":          ("target_id",     "targeting_expression", "entity_type = 'product_targeting'"),
            "negative_delete": ("keyword_id",    "keyword_text",         "entity_type = 'negative_keyword'"),
            "product_ad":      ("ad_id",         "asin",                 "entity_type = 'product_ad'"),
            # _add types: entity_id = campaign_id → lookup campaign_name
            "ad_group_add":    ("campaign_id",   "campaign_name",        "entity_type = 'campaign'"),
            "keyword_add":     ("campaign_id",   "campaign_name",        "entity_type = 'campaign'"),
            "negative_add":    ("campaign_id",   "campaign_name",        "entity_type = 'campaign'"),
            "negative_product_add": ("campaign_id", "campaign_name",     "entity_type = 'campaign'"),
            "product_ad_add":  ("campaign_id",   "campaign_name",        "entity_type = 'campaign'"),
        }
        for et, ids in by_type_log.items():
            if et not in TYPE_QUERY or not ids: continue
            id_col, name_col, w = TYPE_QUERY[et]
            id_list = ','.join(f"'{i}'" for i in ids)
            try:
                for row in bq.query(f"""
                    SELECT DISTINCT {id_col} AS eid, {name_col} AS name
                    FROM `{camp_table_log}` WHERE {id_col} IN ({id_list}) AND {w}
                    LIMIT 500
                """).result():
                    if row.eid and row.name:
                        name_map_log[row.eid] = row.name
            except Exception:
                pass

        # context_map_log: campaign_name для кампаний, ad_group_name для групп/ключей
        context_map_log = {}

        # campaign-level
        ctx_c = {r["entity_id"] for r in rows if r["entity_type"] in ("campaign", "ad_group_add")}
        if ctx_c:
            id_list = ','.join(f"'{i}'" for i in ctx_c)
            try:
                for row in bq.query(f"""
                    SELECT DISTINCT campaign_id AS eid, campaign_name AS name
                    FROM `{camp_table_log}` WHERE campaign_id IN ({id_list}) AND entity_type='campaign'
                    LIMIT 500
                """).result():
                    if row.eid and row.name: context_map_log[row.eid] = row.name
            except Exception: pass

        # group-level (entity_id = ad_group_id)
        ctx_ag = {r["entity_id"] for r in rows if r["entity_type"] in (
            "ad_group", "keyword_add", "negative_add", "negative_product_add", "product_ad_add")}
        if ctx_ag:
            id_list = ','.join(f"'{i}'" for i in ctx_ag)
            try:
                for row in bq.query(f"""
                    SELECT DISTINCT ad_group_id AS eid, ad_group_name AS name
                    FROM `{camp_table_log}` WHERE ad_group_id IN ({id_list}) AND entity_type='ad_group'
                    LIMIT 500
                """).result():
                    if row.eid and row.name: context_map_log[row.eid] = row.name
            except Exception: pass

        # keyword/target (entity_id = keyword_id/target_id → ad_group_name)
        ctx_kw = {r["entity_id"] for r in rows if r["entity_type"] == "keyword"}
        ctx_tg = {r["entity_id"] for r in rows if r["entity_type"] == "target"}
        ctx_nd = {r["entity_id"] for r in rows if r["entity_type"] == "negative_delete"}
        for id_set, id_col, ew in [
            (ctx_kw, "keyword_id", "entity_type='keyword'"),
            (ctx_tg, "target_id",  "entity_type='product_targeting'"),
            (ctx_nd, "keyword_id", "entity_type='negative_keyword'"),
        ]:
            if not id_set: continue
            id_list = ','.join(f"'{i}'" for i in id_set)
            try:
                for row in bq.query(f"""
                    SELECT DISTINCT t.{id_col} AS eid, ag.ad_group_name AS name
                    FROM `{camp_table_log}` t
                    JOIN `{camp_table_log}` ag
                      ON ag.ad_group_id = t.ad_group_id
                     AND ag.entity_type = 'ad_group'
                     AND ag.marketplace = t.marketplace
                    WHERE t.{id_col} IN ({id_list}) AND t.{ew}
                    LIMIT 500
                """).result():
                    if row.eid and row.name: context_map_log[row.eid] = row.name
            except Exception: pass

        for r in rows:
            et  = r["entity_type"]
            eid = r["entity_id"]
            name = name_map_log.get(eid)
            if not name and et in ("keyword_add", "negative_add", "negative_product_add", "product_ad_add"):
                try:
                    v = json.loads(r.get("new_value","{}"))
                    name = v.get("text") or v.get("asin")
                except Exception:
                    pass
            r["entity_name"]  = name or ""
            r["context_name"] = context_map_log.get(eid) or ""

    return jsonify({"rows": rows, "total": len(rows)})