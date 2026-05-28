from flask import Blueprint, jsonify, request
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig

portfolios_bp = Blueprint('portfolios', __name__)

PROJECT_ID = "amazon-ads-api-494412"
DATASET    = "amazon_ads"


@portfolios_bp.route('/portfolios/sync', methods=['POST'])
def portfolios_sync():
    """Синхронизирует уникальные portfolio_id из кампаний в portfolio_labels.
    Добавляет только новые — существующие не трогает."""
    try:
        client = bigquery.Client(project=PROJECT_ID)

        # Собираем уникальные портфолио из обеих таблиц
        sql = """
        SELECT DISTINCT portfolio_id, marketplace, 'MERCH' as account_type
        FROM `amazon-ads-api-494412.amazon_ads.campaigns_merch`
        WHERE entity_type = 'campaign' AND portfolio_id IS NOT NULL

        UNION DISTINCT

        SELECT DISTINCT portfolio_id, marketplace, 'KDP' as account_type
        FROM `amazon-ads-api-494412.amazon_ads.campaigns_kdp`
        WHERE entity_type = 'campaign' AND portfolio_id IS NOT NULL
        """
        rows = list(client.query(sql).result())

        if not rows:
            return jsonify({"inserted": 0, "total": 0})

        # Получаем уже существующие записи
        existing_sql = """
        SELECT portfolio_id, account_type, marketplace
        FROM `amazon-ads-api-494412.amazon_ads.portfolio_labels`
        """
        existing = set(
            (r.portfolio_id, r.account_type, r.marketplace)
            for r in client.query(existing_sql).result()
        )

        # Вставляем только новые
        new_rows = [
            {
                "portfolio_id":   r.portfolio_id,
                "marketplace":    r.marketplace,
                "account_type":   r.account_type,
                "portfolio_name": "",
                "notes":          "",
            }
            for r in rows
            if (r.portfolio_id, r.account_type, r.marketplace) not in existing
        ]

        if new_rows:
            job = client.load_table_from_json(
                new_rows,
                f"{PROJECT_ID}.{DATASET}.portfolio_labels",
                job_config=LoadJobConfig(write_disposition="WRITE_APPEND")
            )
            job.result()

        return jsonify({"inserted": len(new_rows), "total": len(rows)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@portfolios_bp.route('/portfolios/update', methods=['POST'])
def portfolios_update():
    """Обновляет одну запись portfolio_labels."""
    try:
        data           = request.json
        portfolio_id   = data.get('portfolio_id', '')
        account_type   = data.get('account_type', '')
        marketplace    = data.get('marketplace', '')
        portfolio_name = data.get('portfolio_name', '') or ''
        notes          = data.get('notes', '') or ''

        # Экранируем одинарные кавычки
        portfolio_name = portfolio_name.replace("'", "\\'")
        notes          = notes.replace("'", "\\'")

        client = bigquery.Client(project=PROJECT_ID)

        sql = f"""
        UPDATE `{PROJECT_ID}.{DATASET}.portfolio_labels`
        SET portfolio_name = '{portfolio_name}',
            notes = '{notes}'
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
    """Обновляет массив записей portfolio_labels одним запросом."""
    try:
        data    = request.json
        changes = data.get('changes', [])

        if not changes:
            return jsonify({"ok": True, "updated": 0})

        client = bigquery.Client(project=PROJECT_ID)

        for item in changes:
            portfolio_id   = item.get('portfolio_id', '')
            account_type   = item.get('account_type', '')
            marketplace    = item.get('marketplace', '')
            portfolio_name = (item.get('portfolio_name', '') or '').replace("'", "\\'")
            notes          = (item.get('notes', '') or '').replace("'", "\\'")

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
    """Возвращает все портфолио из portfolio_labels."""
    try:
        client = bigquery.Client(project=PROJECT_ID)

        sql = """
        SELECT portfolio_id, account_type, marketplace, portfolio_name, notes
        FROM `amazon-ads-api-494412.amazon_ads.portfolio_labels`
        ORDER BY account_type, marketplace, portfolio_name
        """
        rows = [dict(r) for r in client.query(sql).result()]

        return jsonify({"portfolios": rows, "total": len(rows)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500