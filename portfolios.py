import os
from flask import Blueprint, jsonify, request, send_from_directory
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig
from bq_client import get_client
import json, requests

portfolios_bp = Blueprint('portfolios', __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


@portfolios_bp.route('/portfolios')
def portfolios_page():
    return send_from_directory(BASE_DIR, 'portfolios.html')




@portfolios_bp.route('/portfolios/update', methods=['POST'])
def portfolios_update():
    try:
        data           = request.json
        portfolio_id   = data.get('portfolio_id', '')
        account_type   = data.get('account_type', '')
        marketplace    = data.get('marketplace', '')
        portfolio_name = (data.get('portfolio_name', '') or '').replace("'", "\\'")

        client = get_client()
        sql = f"""
        UPDATE `{PROJECT_ID}.{DATASET}.portfolio_labels`
        SET portfolio_name = '{portfolio_name}',
        WHERE portfolio_id = '{portfolio_id}'
          AND account_type = '{account_type}'
          AND marketplace  = '{marketplace}'
        """
        client.query(sql).result()
        return jsonify({"ok": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@portfolios_bp.route('/portfolios/bulk-update', methods=['POST'])
def portfolios_bulk_update():
    try:
        data    = request.json
        changes = data.get('changes', [])
        if not changes:
            return jsonify({"ok": True, "updated": 0})

        client = get_client()
        for item in changes:
            portfolio_id   = item.get('portfolio_id', '')
            account_type   = item.get('account_type', '')
            marketplace    = item.get('marketplace', '')
            portfolio_name = (item.get('portfolio_name', '') or '').replace("'", "\\'")
            sql = f"""
            UPDATE `{PROJECT_ID}.{DATASET}.portfolio_labels`
            SET portfolio_name = '{portfolio_name}',
                notes = '{notes}'
            WHERE portfolio_id = '{portfolio_id}'
              AND account_type = '{account_type}'
              AND marketplace  = '{marketplace}'
            """
            client.query(sql).result()

        return jsonify({"ok": True, "updated": len(changes)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@portfolios_bp.route('/portfolios/list', methods=['GET'])
def portfolios_list():
    try:
        client = get_client()
        sql = f"""
        SELECT portfolio_id, account_type, marketplace, portfolio_name
        FROM `{PROJECT_ID}.{DATASET}.portfolio_labels`
        ORDER BY account_type, marketplace, portfolio_name
        """
        rows = [dict(r) for r in client.query(sql).result()]
        return jsonify({"portfolios": rows, "total": len(rows)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ── Получить профили для фронта ───────────────────────────
@portfolios_bp.route('/portfolios/profiles', methods=['GET'])
def portfolios_profiles():
    """Возвращает список профилей из amazon_secrets.json для выбора marketplace."""
    try:
        secrets_path = os.path.join(BASE_DIR, 'config', 'amazon_secrets.json')
        with open(secrets_path) as f:
            amz = json.load(f)
        profiles = [
            {
                'id':          p['id'],
                'name':        p.get('name', ''),
                'marketplace': p['marketplace'],
                'type':        p['type'],
                'api_endpoint': p.get('api_endpoint', 'https://advertising-api.amazon.com'),
            }
            for p in amz.get('profiles', [])
        ]
        return jsonify({'profiles': profiles})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _get_amz_token():
    secrets_path = os.path.join(BASE_DIR, 'config', 'amazon_secrets.json')
    with open(secrets_path) as f:
        amz = json.load(f)
    r = requests.post(
        'https://api.amazon.com/auth/o2/token',
        data={
            'grant_type':    'refresh_token',
            'refresh_token': amz['refresh_token'],
            'client_id':     amz['client_id'],
            'client_secret': amz['client_secret'],
        }
    )
    r.raise_for_status()
    return r.json()['access_token'], amz['client_id'], amz.get('profiles', [])


# ── Создать портфолио в Amazon ────────────────────────────
@portfolios_bp.route('/portfolios/amazon-create', methods=['POST'])
def portfolios_amazon_create():
    """
    Создаёт портфолио через Amazon Ads API и добавляет запись в portfolio_labels.
    Body: {name, account_type, marketplace}
    """
    try:
        data         = request.json
        name         = (data.get('name') or '').strip()
        account_type = (data.get('account_type') or '').upper()
        marketplace  = (data.get('marketplace') or '').upper()

        if not name or not account_type or not marketplace:
            return jsonify({'error': 'name, account_type, marketplace обязательны'}), 400

        token, client_id, profiles = _get_amz_token()

        # Найти профиль
        profile = next(
            (p for p in profiles if p['type'] == account_type and p['marketplace'] == marketplace),
            None
        )
        if not profile:
            return jsonify({'error': f'Профиль {account_type}_{marketplace} не найден'}), 404

        endpoint = profile.get('api_endpoint', 'https://advertising-api.amazon.com')
        headers  = {
            'Authorization':                  f'Bearer {token}',
            'Amazon-Advertising-API-ClientId': client_id,
            'Amazon-Advertising-API-Scope':    str(profile['id']),
            'Content-Type':                    'application/vnd.spPortfolio.v3+json',
            'Accept':                          'application/vnd.spPortfolio.v3+json',
        }

        resp = requests.post(
            f'{endpoint}/portfolios',
            headers=headers,
            json={'portfolios': [{'name': name, 'state': 'ENABLED'}]}
        )
        resp.raise_for_status()
        result = resp.json()

        success = result.get('portfolios', {}).get('success', [])
        errors  = result.get('portfolios', {}).get('error', [])

        if not success and errors:
            return jsonify({'error': errors[0].get('errorMessage', 'Amazon API error')}), 400

        portfolio_id = str(success[0].get('portfolioId', ''))
        if not portfolio_id:
            return jsonify({'error': 'portfolioId не вернулся'}), 500

        # Добавить в portfolio_labels
        bq = get_client()
        job = bq.load_table_from_json(
            [{'portfolio_id': portfolio_id, 'marketplace': marketplace,
              'account_type': account_type, 'portfolio_name': name}],
            f'{PROJECT_ID}.{DATASET}.portfolio_labels',
            job_config=LoadJobConfig(write_disposition='WRITE_APPEND')
        )
        job.result()

        return jsonify({'ok': True, 'portfolio_id': portfolio_id, 'name': name})

    except requests.HTTPError as e:
        return jsonify({'error': f'Amazon API: {e.response.status_code} {e.response.text[:200]}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Переименовать портфолио в Amazon ─────────────────────
@portfolios_bp.route('/portfolios/amazon-update', methods=['POST'])
def portfolios_amazon_update():
    """
    Обновляет имя портфолио через Amazon Ads API и синхронизирует portfolio_labels.
    Body: {portfolio_id, name, account_type, marketplace}
    """
    try:
        data         = request.json
        portfolio_id = (data.get('portfolio_id') or '').strip()
        name         = (data.get('name') or '').strip()
        account_type = (data.get('account_type') or '').upper()
        marketplace  = (data.get('marketplace') or '').upper()

        if not portfolio_id or not name or not account_type or not marketplace:
            return jsonify({'error': 'portfolio_id, name, account_type, marketplace обязательны'}), 400

        token, client_id, profiles = _get_amz_token()

        profile = next(
            (p for p in profiles if p['type'] == account_type and p['marketplace'] == marketplace),
            None
        )
        if not profile:
            return jsonify({'error': f'Профиль {account_type}_{marketplace} не найден'}), 404

        endpoint = profile.get('api_endpoint', 'https://advertising-api.amazon.com')
        headers  = {
            'Authorization':                  f'Bearer {token}',
            'Amazon-Advertising-API-ClientId': client_id,
            'Amazon-Advertising-API-Scope':    str(profile['id']),
            'Content-Type':                    'application/vnd.spPortfolio.v3+json',
            'Accept':                          'application/vnd.spPortfolio.v3+json',
        }

        resp = requests.put(
            f'{endpoint}/portfolios',
            headers=headers,
            json={'portfolios': [{'portfolioId': portfolio_id, 'name': name, 'state': 'ENABLED'}]}
        )
        resp.raise_for_status()
        result = resp.json()

        errors = result.get('portfolios', {}).get('error', [])
        if errors:
            return jsonify({'error': errors[0].get('errorMessage', 'Amazon API error')}), 400

        # Обновить portfolio_labels
        safe_name = name.replace("'", "\'")
        bq = get_client()
        bq.query(f"""
            UPDATE `{PROJECT_ID}.{DATASET}.portfolio_labels`
            SET portfolio_name = '{safe_name}'
            WHERE portfolio_id = '{portfolio_id}'
              AND account_type = '{account_type}'
              AND marketplace  = '{marketplace}'
        """).result()

        return jsonify({'ok': True})

    except requests.HTTPError as e:
        return jsonify({'error': f'Amazon API: {e.response.status_code} {e.response.text[:200]}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Загрузить названия из Amazon API ─────────────────────
@portfolios_bp.route('/portfolios/amazon-sync-names', methods=['POST'])
def portfolios_amazon_sync_names():
    """
    Загружает названия портфолио из Amazon Ads API для всех профилей
    и обновляет portfolio_labels одним MERGE запросом.
    """
    try:
        token, client_id, profiles = _get_amz_token()

        all_rows = []
        errors   = []

        for profile in profiles:
            account_type = profile['type']
            marketplace  = profile['marketplace']
            endpoint     = profile.get('api_endpoint', 'https://advertising-api.amazon.com')
            headers = {
                'Authorization':                  f'Bearer {token}',
                'Amazon-Advertising-API-ClientId': client_id,
                'Amazon-Advertising-API-Scope':    str(profile['id']),
                'Content-Type':                    'application/vnd.spPortfolio.v3+json',
                'Accept':                          'application/vnd.spPortfolio.v3+json',
            }

            next_token = None
            while True:
                body = {'stateFilter': {'include': ['ENABLED']}}
                if next_token:
                    body['nextToken'] = next_token
                resp = requests.post(f'{endpoint}/portfolios/list', headers=headers, json=body)
                if resp.status_code != 200:
                    errors.append(f'{account_type}_{marketplace}: {resp.status_code} {resp.text[:100]}')
                    break
                data = resp.json()
                for p in data.get('portfolios', []):
                    pid  = str(p.get('portfolioId', ''))
                    name = (p.get('name') or '').strip()
                    if pid and name:
                        all_rows.append({
                            'portfolio_id':   pid,
                            'marketplace':    marketplace,
                            'account_type':   account_type,
                            'portfolio_name': name,
                        })
                next_token = data.get('nextToken')
                if not next_token:
                    break

        if not all_rows:
            return jsonify({'ok': True, 'updated': 0, 'errors': errors})

        bq = get_client()
        temp_table = f'{PROJECT_ID}.{DATASET}.portfolio_sync_tmp'

        bq.query(f'DROP TABLE IF EXISTS `{temp_table}`').result()
        bq.query(f'CREATE TABLE `{temp_table}` (portfolio_id STRING NOT NULL, marketplace STRING NOT NULL, account_type STRING NOT NULL, portfolio_name STRING NOT NULL)').result()

        job = bq.load_table_from_json(
            all_rows, temp_table,
            job_config=LoadJobConfig(write_disposition='WRITE_APPEND')
        )
        job.result()

        bq.query(f'''
            MERGE `{PROJECT_ID}.{DATASET}.portfolio_labels` AS target
            USING `{temp_table}` AS source
            ON  target.portfolio_id = source.portfolio_id
            AND target.account_type = source.account_type
            AND target.marketplace  = source.marketplace
            WHEN MATCHED THEN
                UPDATE SET target.portfolio_name = source.portfolio_name
            WHEN NOT MATCHED THEN
                INSERT (portfolio_id, marketplace, account_type, portfolio_name)
                VALUES (source.portfolio_id, source.marketplace, source.account_type, source.portfolio_name)
        ''').result()

        bq.query(f'DROP TABLE IF EXISTS `{temp_table}`').result()

        return jsonify({'ok': True, 'updated': len(all_rows), 'errors': errors})

    except requests.HTTPError as e:
        return jsonify({'error': f'Amazon API: {e.response.status_code} {e.response.text[:200]}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500