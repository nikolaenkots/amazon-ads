import os
import re
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
from data_import.catalog_routes   import catalog_bp
from data_import.earnings_routes  import earnings_bp
from data_import.ads_routes       import ads_bp
from data_import.campaigns_routes import campaigns_bp
from management.portfolios       import portfolios_bp
from analytics.analytics_routes import analytics_bp
from management.control_routes import control_bp
from analytics.products_routes  import products_bp
from data_import.kdp_earnings_routes import kdp_earnings_bp
from management.campaign_builder_routes import campaign_builder_bp
from analytics.targets_routes import targets_bp
from analytics.search_terms_routes import search_terms_bp
from analytics.sales_comparison_routes import sales_comparison_bp
from management.asin_merge_routes import asin_merge_bp
from management.negatives_routes import negatives_bp
from resources.bq_stats_routes import bq_stats_bp
from management.campaign_copy_routes import campaign_copy_bp
from automation.search_terms_optimizer_routes import st_optimizer_bp
from automation.bid_automation_routes import bid_automation_bp
from automation.placements_routes import placements_bp
from automation.pause_asins_routes import pause_asins_bp


app.register_blueprint(catalog_bp)
app.register_blueprint(earnings_bp)
app.register_blueprint(ads_bp)
app.register_blueprint(campaigns_bp)
app.register_blueprint(portfolios_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(control_bp)
app.register_blueprint(products_bp)
app.register_blueprint(kdp_earnings_bp)
app.register_blueprint(campaign_builder_bp)
app.register_blueprint(targets_bp)
app.register_blueprint(search_terms_bp)
app.register_blueprint(sales_comparison_bp)
app.register_blueprint(asin_merge_bp)
app.register_blueprint(negatives_bp)
app.register_blueprint(bq_stats_bp)
app.register_blueprint(campaign_copy_bp)
app.register_blueprint(st_optimizer_bp)
app.register_blueprint(bid_automation_bp)
app.register_blueprint(placements_bp)
app.register_blueprint(pause_asins_bp)

# ── Общее оформление ──────────────────────────────────────
# Отдаём своим роутом, а не через /static/: на PythonAnywhere путь /static/
# перехватывается настройками Static files на вкладке Web, и запрос до Flask
# не доходит.
@app.route('/assets/<path:filename>')
def assets(filename):
    resp = send_from_directory(os.path.join(BASE_DIR, 'static'), filename)
    # явный MIME: при text/plain или text/html браузер игнорирует стили
    if filename.endswith('.css'):
        resp.headers['Content-Type'] = 'text/css; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


# ── Подстановка общего CSS прямо в страницу ───────────────
# Домен начинается с "ads.", и блокировщики рекламы режут отдельный запрос
# за common.css (в DevTools это видно как blocked:other), из-за чего страница
# остаётся без оформления. Поэтому <link> заменяется на <style> с содержимым
# файла: отдельного запроса нет — блокировать нечего. Источник оформления
# по-прежнему один: static/common.css.
COMMON_CSS_PATH = os.path.join(BASE_DIR, 'static', 'common.css')
_css_cache = {"mtime": None, "text": ""}

def _common_css():
    try:
        mtime = os.path.getmtime(COMMON_CSS_PATH)
    except OSError:
        return ""
    if _css_cache["mtime"] != mtime:
        with open(COMMON_CSS_PATH, encoding='utf-8') as f:
            _css_cache["text"] = f.read()
        _css_cache["mtime"] = mtime
    return _css_cache["text"]

CSS_LINK_RE = re.compile(r'<link[^>]+href="/assets/common\.css[^"]*"[^>]*>')

# ── Общая шапка с меню ────────────────────────────────────
# Разметка меню лежит в partials/nav.html — единственном месте, где её нужно
# править. Страница ставит маркер <!--HEADER--> (или <!--HEADER:текст справа-->),
# сервер подставляет шапку и помечает активный пункт по текущему адресу.
NAV_PATH  = os.path.join(BASE_DIR, 'partials', 'nav.html')
_nav_cache = {"mtime": None, "text": ""}

def _nav_html():
    try:
        mtime = os.path.getmtime(NAV_PATH)
    except OSError:
        return ""
    if _nav_cache["mtime"] != mtime:
        with open(NAV_PATH, encoding='utf-8') as f:
            _nav_cache["text"] = f.read()
        _nav_cache["mtime"] = mtime
    return _nav_cache["text"]

HEADER_MARK_RE = re.compile(r'<!--\s*HEADER(?::(.*?))?\s*-->', re.S)

def _mark_active(nav, path):
    """Пометить пункт меню, соответствующий текущему адресу."""
    def link(m):
        href = m.group(1)
        cls  = m.group(2)
        if href == path or (href != '/' and path.startswith(href + '/')):
            return f'<a href="{href}" class="{cls} active"'
        return m.group(0)
    nav = re.sub(r'<a href="([^"]+)" class="(nav-link|nav-home)"', link, nav)
    return nav

@app.after_request
def inline_common_parts(resp):
    """Подставить общий CSS и общую шапку прямо в HTML-ответ."""
    if not (resp.content_type or '').startswith('text/html'):
        return resp
    if resp.direct_passthrough:          # ответы send_from_directory отдают файл потоком
        resp.direct_passthrough = False
    html = resp.get_data(as_text=True)
    changed = False

    css = _common_css()
    if css and '/assets/common.css' in html:
        html = CSS_LINK_RE.sub(lambda _: f'<style>\n{css}\n</style>', html, count=1)
        changed = True

    nav = _nav_html()
    if nav and HEADER_MARK_RE.search(html):
        def put(m):
            right = (m.group(1) or '').strip()
            block = nav.replace('{{RIGHT}}',
                                f'<span class="header-right">{right}</span>' if right else '')
            return _mark_active(block, request.path)
        html = HEADER_MARK_RE.sub(put, html, count=1)
        changed = True

    if changed:
        resp.set_data(html)
    return resp

@app.route('/assets-check')
def assets_check():
    """Диагностика: видит ли приложение файл оформления."""
    path = os.path.join(BASE_DIR, 'static', 'common.css')
    return {
        "base_dir":   BASE_DIR,
        "css_path":   path,
        "exists":     os.path.exists(path),
        "size":       os.path.getsize(path) if os.path.exists(path) else None,
        "static_dir": sorted(os.listdir(os.path.join(BASE_DIR, 'static')))
                      if os.path.isdir(os.path.join(BASE_DIR, 'static')) else "нет папки static",
    }

# ── Главная страница ──────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/earnings-kdp')
def earnings_kdp():
    return send_from_directory(os.path.join(BASE_DIR, 'data_import'), 'earnings_kdp.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
