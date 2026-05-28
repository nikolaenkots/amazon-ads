import csv
import os
import hashlib
import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_from_directory
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig

earnings_bp = Blueprint('earnings', __name__)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
PROJECT_ID    = "amazon-ads-api-494412"
DATASET       = "amazon_ads"
EARNINGS      = "earnings"
CHUNK_SIZE    = 1000

def _get_progress_store():
    import app
    return app.progress_store

def emit(job_id, event, data):
    ps = _get_progress_store()
    if job_id not in ps:
        ps[job_id] = []
    ps[job_id].append({"event": event, "data": data})

def load_chunk(client, table_ref, chunk):
    job = client.load_table_from_json(
        chunk, table_ref,
        job_config=LoadJobConfig(write_disposition="WRITE_APPEND")
    )
    job.result()
    return job.errors or []

def detect_earnings_format(header_row):
    h = [c.strip().strip('"').lower() for c in header_row]
    if 'mkt' in h and 'date' in h and 'purchased' in h:
        return 'daily'
    if 'marketplace' in h and 'earning date' in h:
        return 'monthly'
    return None

def parse_sale_date_daily(s):
    try:
        s = s.strip().strip('"')
        dt = datetime.strptime(s, "%m/%d/%y")
        return dt.date().isoformat()
    except:
        return None

def make_row_hash(*args):
    key = "|".join(str(a or '') for a in args)
    return hashlib.md5(key.encode('utf-8')).hexdigest()

def process_earnings_row_daily(row):
    if len(row) < 14: return None
    marketplace = row[0].strip() or None
    sale_date   = parse_sale_date_daily(row[1])
    asin        = row[2].strip() or None
    category_1  = row[4].strip() or None
    category_2  = row[5].strip() or None
    category_3  = row[6].strip() or None
    if not asin or not sale_date: return None
    try: purchased = int(row[8].strip())
    except: purchased = 0
    try: cancelled = int(row[9].strip())
    except: cancelled = 0
    try: returned  = int(row[10].strip())
    except: returned = 0
    try: revenue   = float(row[11].strip()) if row[11].strip() else None
    except: revenue = None
    try: royalties = float(row[12].strip()) if row[12].strip() else None
    except: royalties = None
    row_hash = make_row_hash(marketplace, sale_date, asin, category_1, category_2,
                             category_3, purchased, cancelled, returned, revenue)
    return {
        "row_hash":     row_hash,
        "marketplace":  marketplace,
        "sale_date":    sale_date,
        "asin":         asin,
        "title":        row[3].strip() or None,
        "category_1":   category_1,
        "category_2":   category_2,
        "category_3":   category_3,
        "product_type": row[7].strip() or None,
        "purchased":    purchased,
        "cancelled":    cancelled,
        "returned":     returned,
        "revenue":      revenue,
        "royalties":    royalties,
        "currency":     row[13].strip() or None,
        "imported_at":  datetime.now(tz=timezone.utc).isoformat(),
    }

def run_earnings_import(filepath, job_id):
    errors_log = []
    try:
        client    = bigquery.Client(project=PROJECT_ID)
        table_ref = f"{PROJECT_ID}.{DATASET}.{EARNINGS}"

        emit(job_id, "step", {"step": 1, "msg": "Парсим CSV файл..."})
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            text = f.read()

        lines  = text.split("\n")
        header = next(csv.reader([lines[0]]))
        fmt    = detect_earnings_format(header)

        if fmt == 'daily':
            process_row = process_earnings_row_daily
            emit(job_id, "step", {"step": 1, "msg": "Парсим CSV файл... (формат: Sales Report / daily)"})
        else:
            emit(job_id, "error", {"msg": "Неизвестный формат CSV."})
            return

        all_records  = []
        parse_errors = 0
        for row in csv.reader(lines[1:]):
            if not row: continue
            rec = process_row(row)
            if rec: all_records.append(rec)
            else: parse_errors += 1

        total = len(all_records)
        emit(job_id, "progress", {"total": total, "inserted": 0, "skipped": 0, "errors": parse_errors, "pct": 20})

        emit(job_id, "step", {"step": 2, "msg": "Проверяем дубли по хэшу..."})
        incoming_hashes = [r["row_hash"] for r in all_records]
        existing_hashes = set()
        for i in range(0, len(incoming_hashes), 10000):
            batch = incoming_hashes[i:i+10000]
            placeholders = ", ".join(f"'{h}'" for h in batch)
            try:
                rows = list(client.query(
                    f"SELECT row_hash FROM `{table_ref}` WHERE row_hash IN ({placeholders})"
                ).result())
                for r in rows: existing_hashes.add(r.row_hash)
            except Exception as e:
                if "Not found" in str(e) or "not found" in str(e): break
                raise

        new_records = [r for r in all_records if r["row_hash"] not in existing_hashes]
        skipped     = total - len(new_records)
        emit(job_id, "progress", {"total": total, "inserted": 0, "skipped": skipped, "errors": parse_errors, "pct": 40})

        emit(job_id, "step", {"step": 3, "msg": f"Загружаем {len(new_records)} новых строк..."})
        inserted  = 0
        err_count = parse_errors
        chunk     = []
        for rec in new_records:
            chunk.append(rec)
            if len(chunk) >= CHUNK_SIZE:
                errs = load_chunk(client, table_ref, chunk)
                if errs:
                    err_count += len(errs)
                    for e in errs[:3]: errors_log.append(str(e))
                else:
                    inserted += len(chunk)
                chunk = []
                pct = 40 + int(inserted / max(len(new_records), 1) * 55)
                emit(job_id, "progress", {"total": total, "inserted": inserted, "skipped": skipped, "errors": err_count, "pct": pct})

        if chunk:
            errs = load_chunk(client, table_ref, chunk)
            if errs:
                err_count += len(errs)
                for e in errs[:3]: errors_log.append(str(e))
            else:
                inserted += len(chunk)

        cnt = list(client.query(f"SELECT COUNT(*) as cnt FROM `{table_ref}`").result())[0].cnt
        emit(job_id, "done", {
            "total": total, "inserted": inserted, "skipped": skipped,
            "errors": err_count, "total_in_table": cnt,
            "errors_log": errors_log[:20], "pct": 100
        })
        try: os.remove(filepath)
        except: pass

    except Exception as e:
        emit(job_id, "error", {"msg": str(e)})


@earnings_bp.route('/earnings')
def earnings_page():
    return send_from_directory(BASE_DIR, 'earnings.html')

@earnings_bp.route('/upload_earnings', methods=['POST'])
def upload_earnings():
    f = request.files.get('file')
    if not f:
        return jsonify({"error": "Файл не найден"}), 400
    job_id   = datetime.now().strftime('%Y%m%d%H%M%S%f')
    filepath = os.path.join(UPLOAD_FOLDER, f'earnings_{job_id}.csv')
    f.save(filepath)
    ps = _get_progress_store()
    ps[job_id] = []
    threading.Thread(target=run_earnings_import, args=(filepath, job_id), daemon=True).start()
    return jsonify({"job_id": job_id})

@earnings_bp.route('/earnings_progress/<job_id>')
def earnings_progress(job_id):
    ps = _get_progress_store()
    if job_id not in ps:
        return jsonify([])
    msgs = list(ps[job_id])
    ps[job_id] = []
    return jsonify(msgs)