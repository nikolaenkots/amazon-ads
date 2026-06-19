from bq_client import get_client
"""
kdp_earnings_routes.py — Blueprint для импорта KDP Sales Report

Читает из отдельных вкладок: Paperback Royalty, Hardcover Royalty, eBook Royalty
(не Combined Sales — там нет ASIN для paperback/hardcover).

Таблица BigQuery: amazon_ads.earnings_kdp
"""

import os
import hashlib
import threading
from datetime import datetime, timezone

import pandas as pd
from flask import Blueprint, request, jsonify
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig, SchemaField

kdp_earnings_bp = Blueprint('kdp_earnings', __name__)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
PROJECT_ID    = "amazon-ads-api-494412"
DATASET       = "amazon_ads"
TABLE         = "earnings_kdp"
CHUNK_SIZE    = 1000

# Листы и их специфика
SHEETS = [
    {"name": "Paperback Royalty",  "has_isbn": True,  "has_order_date": True},
    {"name": "Hardcover Royalty",  "has_isbn": True,  "has_order_date": True},
    {"name": "eBook Royalty",      "has_isbn": False, "has_order_date": False},
]

BQ_SCHEMA = [
    SchemaField("row_hash",         "STRING",  mode="REQUIRED"),
    SchemaField("royalty_date",     "DATE",    mode="NULLABLE"),
    SchemaField("order_date",       "DATE",    mode="NULLABLE"),
    SchemaField("asin",             "STRING",  mode="NULLABLE"),
    SchemaField("asin_isbn",        "STRING",  mode="NULLABLE"),  # ISBN-13 for books
    SchemaField("title",            "STRING",  mode="NULLABLE"),
    SchemaField("author",           "STRING",  mode="NULLABLE"),
    SchemaField("marketplace",      "STRING",  mode="NULLABLE"),
    SchemaField("royalty_type",     "STRING",  mode="NULLABLE"),
    SchemaField("transaction_type", "STRING",  mode="NULLABLE"),
    SchemaField("units_sold",       "INTEGER", mode="NULLABLE"),
    SchemaField("units_refunded",   "INTEGER", mode="NULLABLE"),
    SchemaField("net_units_sold",   "INTEGER", mode="NULLABLE"),
    SchemaField("list_price",       "FLOAT",   mode="NULLABLE"),
    SchemaField("offer_price",      "FLOAT",   mode="NULLABLE"),
    SchemaField("manufacturing_cost","FLOAT",  mode="NULLABLE"),
    SchemaField("royalty",          "FLOAT",   mode="NULLABLE"),
    SchemaField("currency",         "STRING",  mode="NULLABLE"),
    SchemaField("imported_at",      "TIMESTAMP", mode="NULLABLE"),
]


def _get_progress_store():
    import app
    return app.progress_store


def emit(job_id, event, data):
    ps = _get_progress_store()
    if job_id not in ps:
        ps[job_id] = []
    ps[job_id].append({"event": event, "data": data})


def make_row_hash(*args):
    key = "|".join(str(a or '') for a in args)
    return hashlib.md5(key.encode('utf-8')).hexdigest()


def safe_float(v):
    try:
        return float(v) if v is not None and str(v).strip() not in ('', 'nan') else None
    except Exception:
        return None


def safe_int(v):
    try:
        return int(float(v)) if v is not None and str(v).strip() not in ('', 'nan') else 0
    except Exception:
        return 0


def safe_date(v):
    if not v:
        return None
    if isinstance(v, str):
        return v.strip() or None
    try:
        return pd.Timestamp(v).date().isoformat()
    except Exception:
        return None


def parse_row(row, sheet_meta):
    royalty_date = safe_date(row.get("Royalty Date"))
    marketplace  = str(row.get("Marketplace") or "").strip() or None

    # ASIN: direct column for all sheets
    asin = str(row.get("ASIN") or "").strip() or None

    # ISBN: only for Paperback/Hardcover
    isbn = None
    if sheet_meta["has_isbn"]:
        raw_isbn = row.get("ISBN")
        if raw_isbn is not None and str(raw_isbn).strip() not in ('', 'nan'):
            isbn = str(raw_isbn).strip().split('.')[0]

    if not royalty_date or not marketplace or not asin:
        return None

    order_date = None
    if sheet_meta["has_order_date"]:
        order_date = safe_date(row.get("Order Date"))

    tx_type        = str(row.get("Transaction Type") or "").strip() or None
    units_sold     = safe_int(row.get("Units Sold"))
    units_refunded = safe_int(row.get("Units Refunded"))
    royalty        = safe_float(row.get("Royalty"))
    currency       = str(row.get("Currency") or "").strip() or None

    row_hash = make_row_hash(
        royalty_date, asin, isbn or '', marketplace,
        tx_type, units_sold, units_refunded, royalty, currency
    )

    # Manufacturing/delivery cost field name differs by sheet
    mfg_cost = safe_float(
        row.get("Avg. Manufacturing Cost") or
        row.get("Avg. Delivery Cost") or
        row.get("Avg. Delivery/Manufacturing cost")
    )

    return {
        "row_hash":          row_hash,
        "royalty_date":      royalty_date,
        "order_date":        order_date,
        "asin":              asin,
        "asin_isbn":         isbn,
        "title":             str(row.get("Title") or "").strip() or None,
        "author":            str(row.get("Author Name") or "").strip() or None,
        "marketplace":       marketplace,
        "royalty_type":      str(row.get("Royalty Type") or "").strip() or None,
        "transaction_type":  tx_type,
        "units_sold":        units_sold,
        "units_refunded":    units_refunded,
        "net_units_sold":    safe_int(row.get("Net Units Sold")),
        "list_price":        safe_float(row.get("Avg. List Price without tax")),
        "offer_price":       safe_float(row.get("Avg. Offer Price without tax")),
        "manufacturing_cost": mfg_cost,
        "royalty":           royalty,
        "currency":          currency,
        "imported_at":       datetime.now(tz=timezone.utc).isoformat(),
    }


def ensure_table_schema(client, table_ref):
    """Create or update table schema to include new asin column."""
    try:
        table = client.get_table(table_ref)
        existing_cols = {f.name for f in table.schema}
        new_fields = [f for f in BQ_SCHEMA if f.name not in existing_cols]
        if new_fields:
            table.schema = list(table.schema) + new_fields
            client.update_table(table, ["schema"])
        return True
    except Exception:
        # Table doesn't exist yet — will be created on first load
        return False


def run_kdp_earnings_import(filepath, job_id):
    try:
        client    = get_client()
        table_ref = f"{PROJECT_ID}.{DATASET}.{TABLE}"

        # Шаг 1: парсинг всех листов
        emit(job_id, "step", {"step": 1, "msg": "Читаем Excel (Paperback, Hardcover, eBook)..."})

        all_records  = []
        parse_errors = 0

        for sheet_meta in SHEETS:
            sheet_name = sheet_meta["name"]
            try:
                df = pd.read_excel(filepath, sheet_name=sheet_name, dtype=str)
            except Exception as e:
                emit(job_id, "step", {"step": 1, "msg": f"Вкладка '{sheet_name}' не найдена: {e}"})
                continue

            for _, row in df.iterrows():
                rec = parse_row(row.to_dict(), sheet_meta)
                if rec:
                    all_records.append(rec)
                else:
                    parse_errors += 1

        # Дедупликация внутри файла по row_hash
        seen = set()
        deduped = []
        for r in all_records:
            if r["row_hash"] not in seen:
                seen.add(r["row_hash"])
                deduped.append(r)
        all_records = deduped

        total = len(all_records)
        emit(job_id, "step", {"step": 1, "msg": f"Парсинг завершён. Строк: {total}, ошибок: {parse_errors}"})
        emit(job_id, "progress", {"total": total, "inserted": 0, "skipped": 0,
                                  "errors": parse_errors, "pct": 20})

        # Шаг 2: обновить схему таблицы (добавить asin если нет)
        emit(job_id, "step", {"step": 2, "msg": "Проверяем схему таблицы..."})
        ensure_table_schema(client, table_ref)

        # Шаг 3: дедупликация с БД
        emit(job_id, "step", {"step": 3, "msg": "Проверяем дубли по хэшу..."})
        incoming_hashes = [r["row_hash"] for r in all_records]
        existing_hashes = set()
        for i in range(0, len(incoming_hashes), 10000):
            batch = incoming_hashes[i:i + 10000]
            placeholders = ", ".join(f"'{h}'" for h in batch)
            try:
                rows = list(client.query(
                    f"SELECT row_hash FROM `{table_ref}` WHERE row_hash IN ({placeholders})"
                ).result())
                for r in rows:
                    existing_hashes.add(r.row_hash)
            except Exception as e:
                if "Not found" in str(e) or "not found" in str(e):
                    break
                raise

        new_records = [r for r in all_records if r["row_hash"] not in existing_hashes]
        skipped     = total - len(new_records)
        emit(job_id, "progress", {"total": total, "inserted": 0, "skipped": skipped,
                                  "errors": parse_errors, "pct": 50})

        # Шаг 4: загрузка
        emit(job_id, "step", {"step": 4, "msg": f"Загружаем {len(new_records)} новых строк в BigQuery..."})
        inserted  = 0
        bq_errors = []
        for i in range(0, len(new_records), CHUNK_SIZE):
            chunk = new_records[i:i + CHUNK_SIZE]
            job   = client.load_table_from_json(
                chunk, table_ref,
                job_config=LoadJobConfig(
                    write_disposition="WRITE_APPEND",
                    schema=BQ_SCHEMA,
                )
            )
            errs = job.result().errors
            if errs:
                bq_errors.extend(errs)
            else:
                inserted += len(chunk)
            pct = 50 + int(50 * inserted / max(len(new_records), 1))
            emit(job_id, "progress", {"total": total, "inserted": inserted,
                                      "skipped": skipped,
                                      "errors": parse_errors + len(bq_errors),
                                      "pct": pct})

        table_count = 0
        try:
            res = list(client.query(
                f"SELECT COUNT(*) AS cnt FROM `{table_ref}`"
            ).result())
            table_count = res[0].cnt
        except Exception:
            pass

        emit(job_id, "done", {
            "total":       total,
            "inserted":    inserted,
            "skipped":     skipped,
            "errors":      parse_errors + len(bq_errors),
            "table_count": table_count,
            "bq_errors":   [str(e) for e in bq_errors[:10]],
        })

    except Exception as e:
        emit(job_id, "error", {"msg": str(e)})


# ── Routes ────────────────────────────────────────────────

@kdp_earnings_bp.route('/kdp-earnings/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files['file']
    if not f.filename.endswith('.xlsx'):
        return jsonify({"error": "Только .xlsx файлы"}), 400

    import uuid as _uuid
    job_id   = _uuid.uuid4().hex
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filepath = os.path.join(UPLOAD_FOLDER, f"kdp_earnings_{job_id}.xlsx")
    f.save(filepath)

    t = threading.Thread(target=run_kdp_earnings_import, args=(filepath, job_id), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@kdp_earnings_bp.route('/kdp-earnings/progress/<job_id>')
def progress(job_id):
    ps = _get_progress_store()
    if job_id not in ps:
        return jsonify([])
    msgs = list(ps[job_id])
    ps[job_id] = []
    return jsonify(msgs)


@kdp_earnings_bp.route('/kdp-earnings/count')
def count():
    try:
        client = get_client()
        res    = list(client.query(
            f"SELECT COUNT(*) AS cnt FROM `{PROJECT_ID}.{DATASET}.{TABLE}`"
        ).result())
        return jsonify({"count": res[0].cnt})
    except Exception as e:
        return jsonify({"count": 0, "error": str(e)})
