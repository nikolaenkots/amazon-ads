import os
import json
import threading
from datetime import datetime, timezone
from flask import Flask, send_from_directory

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 МБ


# ── Auth ──────────────────────────────────────────────────
import base64
from flask import Response, request

AUTH_USERNAME = "Artem"
AUTH_PASSWORD = "KjubcN*123"

def check_auth(auth_header):
    if not auth_header or not auth_header.startswith('Basic '):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        user, pwd = decoded.split(':', 1)
        return user == AUTH_USERNAME and pwd == AUTH_PASSWORD
    except Exception:
        return False

@app.before_request
def require_auth():
    if not check_auth(request.headers.get('Authorization')):
        return Response(
            'Требуется авторизация',
            401,
            {'WWW-Authenticate': 'Basic realm="Amazon Ads"'}
        )



BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PROJECT_ID = "amazon-ads-api-494412"
KEY_FILE   = os.path.join(BASE_DIR, "config", "bigquery_key.json")
DATASET    = "amazon_ads"

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_FILE

# Хранилище прогресса (shared между blueprints)
progress_store = {}

# ── Blueprints ────────────────────────────────────────────
from catalog_routes   import catalog_bp
from earnings_routes  import earnings_bp
from ads_routes       import ads_bp
from campaigns_routes import campaigns_bp
from portfolios       import portfolios_bp
from analytics_routes import analytics_bp
from control_routes import control_bp
from products_routes  import products_bp
from kdp_earnings_routes import kdp_earnings_bp


app.register_blueprint(catalog_bp)
app.register_blueprint(earnings_bp)
app.register_blueprint(ads_bp)
app.register_blueprint(campaigns_bp)
app.register_blueprint(portfolios_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(control_bp)
app.register_blueprint(products_bp)
app.register_blueprint(kdp_earnings_bp)

# ── Главная страница ──────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/earnings-kdp')
def earnings_kdp():
    return send_from_directory(BASE_DIR, 'earnings_kdp.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)