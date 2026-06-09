import gzip
import json
import os
import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_from_directory
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig
import requests as req_lib

ads_bp = Blueprint('ads', __name__)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
PROJECT_ID    = "amazon-ads-api-494412"
DATASET       = "amazon_ads"
CHUNK_SIZE    = 1000
REPORTS_LOG   = os.path.join(BASE_DIR, 'reports_log.json')

AMZ_SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'amazon_secrets.json')
with open(AMZ_SECRETS_PATH) as _f:
    _AMZ = json.load(_f)

_log_lock = threading.Lock()

def _get_progress_store():
    import app
    return app.progress_store

def emit(job_id, event, data):
    ps = _get_progress_store()
    if job_id not in ps:
        ps[job_id] = []
    ps[job_id].append({"event": event, "data": data})

def _read_log():
    try:
        with open(REPORTS_LOG) as f:
            return json.load(f)
    except:
        return []

def _write_log(entries):
    with _log_lock:
        with open(REPORTS_LOG, 'w') as f:
            json.dump(entries, f, indent=2, default=str)

def _update_log_entry(entry_id, updates):
    with _log_lock:
        entries = _read_log()
        for e in entries:
            if e['id'] == entry_id:
                e.update(updates)
                break
        with open(REPORTS_LOG, 'w') as f:
            json.dump(entries, f, indent=2, default=str)

def _get_profile(account_type, marketplace):
    for p in _AMZ.get("profiles", []):
        if p["type"] == account_type and p["marketplace"] == marketplace:
            return p
    for p in _AMZ.get("profiles", []):
        if p["type"] == account_type:
            return p
    return None

def _get_table(account_type, report_type="spTargeting"):
    suffix = "kdp" if account_type == "KDP" else "merch"
    if report_type == "spAdvertisedProduct":
        return f"{PROJECT_ID}.{DATASET}.asin_stats_{suffix}"
    if report_type == "spSearchTerm":
        return f"{PROJECT_ID}.{DATASET}.search_terms_{suffix}"
    return f"{PROJECT_ID}.{DATASET}.targets_stats_{suffix}"

def _amz_token():
    r = req_lib.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": _AMZ["refresh_token"],
            "client_id":     _AMZ["client_id"],
            "client_secret": _AMZ["client_secret"],
        }
    )
    r.raise_for_status()
    return r.json()["access_token"]

def _amz_headers(token, profile_id):
    return {
        "Authorization":                   f"Bearer {token}",
        "Amazon-Advertising-API-ClientId":  _AMZ["client_id"],
        "Amazon-Advertising-API-Scope":     str(profile_id),
    }

REPORT_CONFIGS = {
    "spTargeting": {
        "label":   "Targeting (ключевые слова)",
        "groupBy": ["targeting"],
        "columns": [
            "date", "campaignId", "adGroupId",
            "keywordId", "keyword", "keywordType", "targeting",
            "adKeywordStatus", "impressions", "clicks", "cost",
            "topOfSearchImpressionShare",
            "purchases1d", "purchases7d", "purchases14d",
            "sales1d", "sales7d", "sales14d",
            "unitsSoldClicks1d", "unitsSoldClicks7d", "unitsSoldClicks14d"
        ]
    },
    "spAdvertisedProduct": {
        "label":   "Advertised Product (по ASIN)",
        "groupBy": ["advertiser"],
        "columns": [
            "date", "campaignId", "adGroupId",
            "advertisedAsin", "advertisedSku",
            "impressions", "clicks", "cost",
            "purchases1d", "purchases7d", "purchases14d",
            "sales1d", "sales7d", "sales14d",
            "unitsSoldClicks1d", "unitsSoldClicks7d", "unitsSoldClicks14d"
        ]
    },
    "spSearchTerm": {
        "label":   "Search Term (поисковые запросы)",
        "groupBy": ["searchTerm"],
        "columns": [
            "date", "campaignId", "adGroupId",
            "keywordId", "keyword", "keywordType", "matchType", "targeting",
            "searchTerm", "impressions", "clicks", "cost",
            "purchases1d", "purchases7d", "purchases14d",
            "sales1d", "sales7d", "sales14d",
            "unitsSoldClicks1d", "unitsSoldClicks7d", "unitsSoldClicks14d"
        ]
    },
}

def _map_targeting_row(r, profile_id, marketplace):
    keyword_type = r.get("keywordType", "")
    is_keyword   = keyword_type in ("BROAD", "PHRASE", "EXACT")
    is_auto      = keyword_type in ("TARGETING_EXPRESSION_PREDEFINED", "TARGETING_EXPRESSION")
    return {
        "date":                           r.get("date"),
        "profile_id":                     str(profile_id),
        "marketplace":                    marketplace,
        "campaign_id":                    str(r.get("campaignId", "")),
        "ad_group_id":                    str(r.get("adGroupId", "")),
        "keyword_id":                     str(r["keywordId"]) if r.get("keywordId") else None,
        "keyword":                        r.get("keyword") if is_keyword else None,
        "keyword_type":                   keyword_type or None,
        "targeting":                      r.get("targeting") if is_auto else None,
        "ad_keyword_status":              r.get("adKeywordStatus"),
        "impressions":                    r.get("impressions"),
        "clicks":                         r.get("clicks"),
        "cost":                           float(r["cost"]) if r.get("cost") is not None else None,
        "top_of_search_impression_share": float(r["topOfSearchImpressionShare"]) if r.get("topOfSearchImpressionShare") is not None else None,
        "purchases_1d":                   r.get("purchases1d"),
        "purchases_7d":                   r.get("purchases7d"),
        "purchases_14d":                  r.get("purchases14d"),
        "sales_1d":                       float(r["sales1d"]) if r.get("sales1d") is not None else None,
        "sales_7d":                       float(r["sales7d"]) if r.get("sales7d") is not None else None,
        "sales_14d":                      float(r["sales14d"]) if r.get("sales14d") is not None else None,
        "units_1d":                       r.get("unitsSoldClicks1d"),
        "units_7d":                       r.get("unitsSoldClicks7d"),
        "units_14d":                      r.get("unitsSoldClicks14d"),
        "loaded_at":                      datetime.now(tz=timezone.utc).isoformat(),
    }

def _map_asin_row(r, profile_id, marketplace):
    return {
        "date":            r.get("date"),
        "profile_id":      str(profile_id),
        "marketplace":     marketplace,
        "campaign_id":     str(r.get("campaignId", "")),
        "ad_group_id":     str(r.get("adGroupId", "")),
        "advertised_asin": r.get("advertisedAsin") or "",
        "advertised_sku":  r.get("advertisedSku"),
        "impressions":     r.get("impressions"),
        "clicks":          r.get("clicks"),
        "cost":            float(r["cost"]) if r.get("cost") is not None else None,
        "purchases_1d":    r.get("purchases1d"),
        "purchases_7d":    r.get("purchases7d"),
        "purchases_14d":   r.get("purchases14d"),
        "sales_1d":        float(r["sales1d"]) if r.get("sales1d") is not None else None,
        "sales_7d":        float(r["sales7d"]) if r.get("sales7d") is not None else None,
        "sales_14d":       float(r["sales14d"]) if r.get("sales14d") is not None else None,
        "units_1d":        r.get("unitsSoldClicks1d"),
        "units_7d":        r.get("unitsSoldClicks7d"),
        "units_14d":       r.get("unitsSoldClicks14d"),
        "loaded_at":       datetime.now(tz=timezone.utc).isoformat(),
    }

def _map_search_term_row(r, profile_id, marketplace):
    keyword_type = r.get("keywordType", "")
    is_keyword   = keyword_type in ("BROAD", "PHRASE", "EXACT")
    is_auto      = keyword_type in ("TARGETING_EXPRESSION_PREDEFINED", "TARGETING_EXPRESSION")
    return {
        "date":          r.get("date"),
        "profile_id":    str(profile_id),
        "marketplace":   marketplace,
        "campaign_id":   str(r.get("campaignId", "")),
        "ad_group_id":   str(r.get("adGroupId", "")),
        "keyword_id":    str(r["keywordId"]) if r.get("keywordId") else None,
        "keyword":       r.get("keyword") if is_keyword else None,
        "keyword_type":  keyword_type or None,
        "targeting":     r.get("targeting") if is_auto else None,
        "match_type":    r.get("matchType") if is_keyword else None,
        "search_term":   r.get("searchTerm") or "",
        "impressions":   r.get("impressions"),
        "clicks":        r.get("clicks"),
        "cost":          float(r["cost"]) if r.get("cost") is not None else None,
        "purchases_1d":  r.get("purchases1d"),
        "purchases_7d":  r.get("purchases7d"),
        "purchases_14d": r.get("purchases14d"),
        "sales_1d":      float(r["sales1d"]) if r.get("sales1d") is not None else None,
        "sales_7d":      float(r["sales7d"]) if r.get("sales7d") is not None else None,
        "sales_14d":     float(r["sales14d"]) if r.get("sales14d") is not None else None,
        "units_1d":      r.get("unitsSoldClicks1d"),
        "units_7d":      r.get("unitsSoldClicks7d"),
        "units_14d":     r.get("unitsSoldClicks14d"),
        "loaded_at":     datetime.now(tz=timezone.utc).isoformat(),
    }

def _map_row(r, profile_id, marketplace, report_type):
    if report_type == "spAdvertisedProduct":
        return _map_asin_row(r, profile_id, marketplace)
    if report_type == "spSearchTerm":
        return _map_search_term_row(r, profile_id, marketplace)
    return _map_targeting_row(r, profile_id, marketplace)


@ads_bp.route('/ads')
def ads_page():
    return send_from_directory(BASE_DIR, 'ads.html')

@ads_bp.route('/ads/profiles', methods=['GET'])
def ads_profiles():
    return jsonify({"profiles": _AMZ.get("profiles", [])})

@ads_bp.route('/ads/reports_log', methods=['GET'])
def ads_reports_log():
    return jsonify(_read_log())

@ads_bp.route('/ads/create_report', methods=['POST'])
def ads_create_report():
    data         = request.json
    start_date   = data.get('start_date')
    end_date     = data.get('end_date', start_date)
    account_type = data.get('account_type', 'MERCH')
    marketplace  = data.get('marketplace', 'US')
    report_type  = data.get('report_type', 'spTargeting')
    try:
        profile = _get_profile(account_type, marketplace)
        if not profile:
            return jsonify({"error": f"Профиль не найден: {account_type} / {marketplace}"}), 400
        cfg      = REPORT_CONFIGS.get(report_type, REPORT_CONFIGS["spTargeting"])
        token    = _amz_token()
        endpoint = profile.get("api_endpoint", "https://advertising-api.amazon.com")
        h = {
            **_amz_headers(token, profile["id"]),
            "Content-Type": "application/vnd.createasyncreportrequest.v3+json"
        }
        body = {
            "name":      f"SP {report_type} {account_type} {marketplace} {start_date}→{end_date}",
            "startDate": start_date, "endDate": end_date,
            "configuration": {
                "adProduct": "SPONSORED_PRODUCTS", "reportTypeId": report_type,
                "groupBy": cfg["groupBy"], "timeUnit": "DAILY",
                "format": "GZIP_JSON", "columns": cfg["columns"],
            }
        }
        r = req_lib.post(f"{endpoint}/reporting/reports", headers=h, json=body)
        r.raise_for_status()
        report_id = r.json()["reportId"]
        entry = {
            "id":           datetime.now().strftime('%Y%m%d%H%M%S%f'),
            "report_id":    report_id, "report_type": report_type,
            "account_type": account_type, "marketplace": marketplace,
            "profile_id":   str(profile["id"]), "profile_name": profile["name"],
            "start_date":   start_date, "end_date": end_date,
            "status":       "PENDING", "report_url": None, "file_id": None,
            "rows": None, "inserted": None,
            "created_at":   datetime.now(tz=timezone.utc).isoformat(),
            "loaded_at": None, "error": None,
        }
        entries = _read_log()
        entries.insert(0, entry)
        _write_log(entries)
        return jsonify({"entry_id": entry["id"], "report_id": report_id, "status": "PENDING"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ads_bp.route('/ads/refresh_statuses', methods=['POST'])
def ads_refresh_statuses():
    try:
        entries = _read_log()
        pending = [e for e in entries if e["status"] == "PENDING"]
        if not pending:
            return jsonify({"updated": 0, "checked": 0})
        token   = _amz_token()
        updated = 0
        for entry in pending:
            try:
                profile  = _get_profile(entry["account_type"], entry["marketplace"])
                endpoint = profile.get("api_endpoint", "https://advertising-api.amazon.com") if profile else "https://advertising-api.amazon.com"
                r = req_lib.get(
                    f"{endpoint}/reporting/reports/{entry['report_id']}",
                    headers=_amz_headers(token, entry["profile_id"])
                )
                d      = r.json()
                status = d.get("status")
                if status == "COMPLETED":
                    _update_log_entry(entry["id"], {"status": "COMPLETED", "report_url": d.get("url"), "file_size": d.get("fileSize")})
                    updated += 1
                elif status == "FAILED":
                    _update_log_entry(entry["id"], {"status": "FAILED", "error": d.get("failureReason", "Unknown")})
                    updated += 1
            except Exception as e:
                _update_log_entry(entry["id"], {"error": str(e)})
        return jsonify({"updated": updated, "checked": len(pending)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ads_bp.route('/ads/download_report', methods=['POST'])
def ads_download_report():
    data     = request.json
    entry_id = data.get('entry_id')
    url      = data.get('url')
    try:
        resp    = req_lib.get(url, timeout=60)
        rows    = json.loads(gzip.decompress(resp.content))
        file_id = datetime.now().strftime('%Y%m%d%H%M%S%f')
        tmp     = os.path.join(UPLOAD_FOLDER, f'ads_{file_id}.json')
        with open(tmp, 'w') as f:
            json.dump(rows, f)
        if entry_id:
            _update_log_entry(entry_id, {"status": "DOWNLOADED", "file_id": file_id, "rows": len(rows)})
        return jsonify({"file_id": file_id, "rows": len(rows), "file_size": os.path.getsize(tmp)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@ads_bp.route('/ads/upload_to_bq', methods=['POST'])
def ads_upload_to_bq():
    data         = request.json
    entry_id     = data.get('entry_id')
    file_id      = data.get('file_id')
    start_date   = data.get('start_date')
    end_date     = data.get('end_date', start_date)
    account_type = data.get('account_type', 'MERCH')
    marketplace  = data.get('marketplace', 'US')
    profile_id   = data.get('profile_id', '')
    report_type  = data.get('report_type', 'spTargeting')
    tmp = os.path.join(UPLOAD_FOLDER, f'ads_{file_id}.json')
    if not os.path.exists(tmp):
        return jsonify({"error": "Файл не найден — сначала скачайте отчёт"}), 400
    job_id = f"ads_{file_id}"
    ps = _get_progress_store()
    ps[job_id] = []

    def run_upload():
        try:
            emit(job_id, "progress", {"msg": "Читаем файл...", "pct": 5})
            with open(tmp) as f:
                rows = json.load(f)
            emit(job_id, "progress", {"msg": f"Маппинг {len(rows):,} строк...", "pct": 15})
            mapped = [_map_row(r, profile_id, marketplace, report_type) for r in rows]
            client = bigquery.Client(project=PROJECT_ID)
            tbl    = _get_table(account_type, report_type)
            emit(job_id, "progress", {"msg": "Удаляем старые данные...", "pct": 20})
            client.query(
                f"DELETE FROM `{tbl}` WHERE date BETWEEN '{start_date}' AND '{end_date}' AND profile_id = '{profile_id}'"
            ).result()
            import time
            total      = len(mapped)
            inserted   = 0
            CHUNK      = 50_000
            BATCH_SIZE = 5
            chunks     = [mapped[i:i+CHUNK] for i in range(0, total, CHUNK)]
            emit(job_id, "progress", {"msg": f"Загружаем {total:,} строк ({len(chunks)} частей)...", "pct": 22})
            for b_start in range(0, len(chunks), BATCH_SIZE):
                batch = chunks[b_start:b_start+BATCH_SIZE]
                jobs  = []
                for ch in batch:
                    j = client.load_table_from_json(
                        ch, tbl,
                        job_config=LoadJobConfig(write_disposition="WRITE_APPEND")
                    )
                    jobs.append((j, len(ch)))
                for j, n in jobs:
                    j.result()
                    inserted += n
                    pct = 22 + int(inserted / total * 73)
                    emit(job_id, "progress", {"msg": f"Загружено {inserted:,}/{total:,}", "pct": pct})
                if b_start + BATCH_SIZE < len(chunks):
                    time.sleep(2)
            try: os.remove(tmp)
            except: pass
            if entry_id:
                _update_log_entry(entry_id, {
                    "status": "LOADED", "inserted": inserted,
                    "loaded_at": datetime.now(tz=timezone.utc).isoformat(), "file_id": None,
                })
            emit(job_id, "done", {"rows": total, "inserted": inserted})
        except Exception as e:
            if entry_id:
                _update_log_entry(entry_id, {"status": "ERROR", "error": str(e)})
            emit(job_id, "error", {"msg": str(e)})
            try: os.remove(tmp)
            except: pass

    threading.Thread(target=run_upload, daemon=True).start()
    return jsonify({"job_id": job_id})

@ads_bp.route('/ads/upload_progress/<job_id>')
def ads_upload_progress(job_id):
    ps = _get_progress_store()
    if job_id not in ps:
        return jsonify([])
    msgs = list(ps[job_id])
    ps[job_id] = []
    return jsonify(msgs)

@ads_bp.route('/ads/delete_log_entry', methods=['POST'])
def ads_delete_log_entry():
    entry_id = request.json.get('entry_id')
    entries  = [e for e in _read_log() if e['id'] != entry_id]
    _write_log(entries)
    return jsonify({"ok": True})