import os
import json
import threading
from datetime import datetime, timezone
from flask import Flask, send_from_directory

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 МБ

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


app.register_blueprint(catalog_bp)
app.register_blueprint(earnings_bp)
app.register_blueprint(ads_bp)
app.register_blueprint(campaigns_bp)
app.register_blueprint(portfolios_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(control_bp)
app.register_blueprint(products_bp)

# ── Главная страница ──────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)