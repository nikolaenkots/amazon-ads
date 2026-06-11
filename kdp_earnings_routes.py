from bq_client import get_client
"""
kdp_earnings_routes.py — Blueprint для импорта KDP Sales Report (Combined Sales)

Таблица BigQuery: amazon_ads.earnings_kdp
Формат файла: Excel (.xlsx), вкладка "Combined Sales"

Endpoints:
  POST /kdp-earnings/upload          — загрузить файл
  GET  /kdp-earnings/progress/<job_id> — polling (возвращает JSON список событий)
  GET  /kdp-earnings/count           — кол-во строк в таблице
"""

import os
import hashlib
import threading
from datetime import datetime, timezone

import pandas as pd
from flask import Blueprint, request, jsonify
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig

kdp_earnings_bp = Blueprint('kdp_earnings', __name__)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
PROJECT_ID    = "amazon-ads-api-494412"
DATASET       = "amazon_ads"
TABLE         = "earnings_kdp"
CHUNK_SIZE    = 1000
SHEET_NAME    = "Combined Sales"

# ── Утилиты ───────────────────────────────────────────────

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


# ── Парсинг строки ────────────────────────────────────────

def parse_row(row):
    royalty_date = row.get("Royalty Date")
    asin_isbn    = row.get("ASIN/ISBN")
    marketplace  = row.get("Marketplace")

    if not royalty_date or not asin_isbn or not marketplace:
        return None

    if isinstance(royalty_date, str):
        sale_date = royalty_date.strip()
    else:
        try:
            sale_date = pd.Timestamp(royalty_date).date().isoformat()
        except Exception:
            return None

    asin_isbn_str = str(asin_isbn).strip().split('.')[0]  # убираем .0 если float

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

    units_sold     = safe_int(row.get("Units Sold"))
    units_refunded = safe_int(row.get("Units Refunded"))
    net_units      = safe_int(row.get("Net Units Sold"))
    list_price     = safe_float(row.get("Avg. List Price without tax"))
    offer_price    = safe_float(row.get("Avg. Offer Price without tax"))
    delivery_cost  = safe_float(row.get("Avg. Delivery/Manufacturing cost"))
    royalty        = safe_float(row.get("Royalty"))
    currency       = str(row.get("Currency") or "").strip() or None
    title          = str(row.get("Title") or "").strip() or None
    author         = str(row.get("Author Name") or "").strip() or None
    royalty_type   = str(row.get("Royalty Type") or "").strip() or None
    tx_type        = str(row.get("Transaction Type") or "").strip() or None

    row_hash = make_row_hash(
        sale_date, asin_isbn_str, marketplace,
        tx_type, units_sold, units_refunded, royalty, currency
    )

    return {
        "row_hash":         row_hash,
        "royalty_date":     sale_date,
        "asin_isbn":        asin_isbn_str,
        "title":            title,
        "author":           author,
        "marketplace":      marketplace,
        "royalty_type":     royalty_type,
        "transaction_type": tx_type,
        "units_sold":       units_sold,
        "units_refunded":   units_refunded,
        "net_units_sold":   net_units,
        "list_price":       list_price,
        "offer_price":      offer_price,
        "delivery_cost":    delivery_cost,
        "royalty":          royalty,
        "currency":         currency,
        "imported_at":      datetime.now(tz=timezone.utc).isoformat(),
    }


# ── Импорт ────────────────────────────────────────────────

def run_kdp_earnings_import(filepath, job_id):
    try:
        client    = get_client()
        table_ref = f"{PROJECT_ID}.{DATASET}.{TABLE}"

        # Шаг 1: парсинг
        emit(job_id, "step", {"step": 1, "msg": "Читаем Excel файл (вкладка Combined Sales)..."})
        try:
            df = pd.read_excel(filepath, sheet_name=SHEET_NAME, dtype=str)
        except Exception as e:
            emit(job_id, "error", {"msg": f"Не удалось прочитать файл: {e}"})
            return

        all_records  = []
        parse_errors = 0
        for _, row in df.iterrows():
            rec = parse_row(row.to_dict())
            if rec:
                all_records.append(rec)
            else:
                parse_errors += 1

        total = len(all_records)
        emit(job_id, "step", {"step": 1, "msg": f"Парсинг завершён. Строк: {total}, ошибок: {parse_errors}"})
        emit(job_id, "progress", {"total": total, "inserted": 0, "skipped": 0,
                                  "errors": parse_errors, "pct": 20})

        # Шаг 2: дедупликация
        emit(job_id, "step", {"step": 2, "msg": "Проверяем дубли по хэшу..."})
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

        # Шаг 3: загрузка
        emit(job_id, "step", {"step": 3, "msg": f"Загружаем {len(new_records)} новых строк в BigQuery..."})
        inserted  = 0
        bq_errors = []
        for i in range(0, len(new_records), CHUNK_SIZE):
            chunk = new_records[i:i + CHUNK_SIZE]
            job   = client.load_table_from_json(
                chunk, table_ref,
                job_config=LoadJobConfig(write_disposition="WRITE_APPEND")
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

        # Итог
        table_count = 0
        try:
            res = list(client.query(
                f"SELECT COUNT(*) AS cnt FROM `{table_ref}`"
            ).result())
            table_count = res[0].cnt
        except Exception:
            pass

        emit(job_id, "done", {
            "total":        total,
            "inserted":     inserted,
            "skipped":      skipped,
            "errors":       parse_errors + len(bq_errors),
            "table_count":  table_count,
            "bq_errors":    [str(e) for e in bq_errors[:10]],
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