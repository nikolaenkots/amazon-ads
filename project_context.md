# Amazon Ads Automation — Контекст проекта

## Цель системы
Автоматизация сбора рекламной статистики и управления ставками для Merch by Amazon и KDP рекламы.
Анализ кликов по ключевым словам, управление кампаниями через очередь изменений (pending_changes),
сравнение рекламных расходов с органическими продажами MBA.

---

## Стек

| Сервис | Роль | URL / Доступ |
|---|---|---|
| **BigQuery** | Хранилище — каталог, реклама, продажи | Project: `amazon-ads-api-494412`, Dataset: `amazon_ads` |
| **PythonAnywhere** | Flask веб-приложение + CLI скрипты | `nikolaenkots.pythonanywhere.com` · папка `~/amazon-ads/` |
| **Amazon Ads API** | SP API v1 (управление) + Reporting v3 (статистика) | OAuth2, secrets в `~/amazon-ads/config/` |

---

## Дизайн-система (единый стиль всех страниц)

Все страницы используют единый светлый стиль. При создании новых страниц строго следовать этому описанию.

### CSS-переменные (копировать в каждую страницу)

```css
:root{
  --bg:#f4f4f6;          /* фон страницы */
  --surface:#fff;        /* фон карточек, таблиц */
  --surface2:#f0f0f3;    /* фон thead, hover, filter bar */
  --border:#e2e2e8;      /* основные границы */
  --border2:#ccccd4;     /* акцентированные границы */
  --text:#18181c;        /* основной текст */
  --muted:#6b6b7a;       /* вторичный текст, лейблы */
  --dim:#aaaab8;         /* третичный текст, placeholder */
  --accent:#c84b14;      /* оранжево-красный акцент */
  --accent-bg:rgba(200,75,20,.07);
  --accent-bd:rgba(200,75,20,.22);
  --green:#1a8f5c;
  --green-bg:rgba(26,143,92,.08);
  --green-bd:rgba(26,143,92,.2);
  --red:#d94040;
  --red-bg:rgba(217,64,64,.07);
  --red-bd:rgba(217,64,64,.22);
  --blue:#1a6fd4;
  --blue-bg:rgba(26,111,212,.07);
  --blue-bd:rgba(26,111,212,.2);
  --amber:#b07800;
  --amber-bg:rgba(176,120,0,.07);
  --amber-bd:rgba(176,120,0,.22);
  --purple:#6c3fc9;
  --purple-bg:rgba(108,63,201,.07);
  --purple-bd:rgba(108,63,201,.2);
}
```

### Шрифты

```html
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
```

- **DM Sans** — основной текст, кнопки, навигация
- **DM Mono** — числа, ID, бейджи, лейблы колонок, моно-значения

> **Важно:** старые страницы (`earnings.html`, `portfolios.html`, `catalog.html`) использовали дополнительно `Instrument Serif` и другие CSS токены (`--bg:#f5f2ed`). Новые страницы — только DM Sans + DM Mono, токены из таблицы выше.

### Header (одинаковый на всех страницах)

```css
header {
  display:flex; align-items:center; justify-content:space-between;
  padding:0 32px; height:52px;
  background:var(--surface); border-bottom:1px solid var(--border);
  position:sticky; top:0; z-index:200;
  box-shadow:0 1px 4px rgba(0,0,0,.06);
}
.logo { display:flex; align-items:center; gap:10px; font-size:13px; font-weight:600; }
.logo-dot {
  width:26px; height:26px; border-radius:7px; background:var(--accent);
  display:flex; align-items:center; justify-content:center;
}
nav { display:flex; gap:2px; }
nav a {
  padding:5px 12px; border-radius:6px; font-size:13px; font-weight:500;
  color:var(--muted); text-decoration:none; transition:color .15s,background .15s;
}
nav a:hover { color:var(--text); background:var(--surface2); }
nav a.active { color:var(--accent); background:var(--accent-bg); }
```

```html
<header>
  <div class="logo">
    <div class="logo-dot">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
        <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
      </svg>
    </div>
    Amazon Ads Automation
  </div>
  <nav>
    <a href="/">Главная</a>
    <a href="/analytics/campaigns">Кампании</a>
    <a href="/analytics/products">Продукты</a>
    <a href="/control">Контроль</a>
    <a href="/campaigns">Кампании SP API</a>
    <a href="/portfolios">Портфолио</a>
    <!-- добавить class="active" к текущей странице -->
  </nav>
</header>
```

### Layout

```css
main { padding:18px 32px; max-width:1400px; margin:0 auto; }
/* Для узких страниц (portfolios, campaigns sync): max-width:1200px или 900px */
/* Для страниц импорта: grid 2 колонки 1fr + 360px, max-width:1060px */
```

### Кнопки

```css
.btn {
  height:34px; padding:0 14px; border-radius:6px; border:none;
  font-family:'DM Sans',sans-serif; font-size:13px; font-weight:500;
  cursor:pointer; display:inline-flex; align-items:center; gap:6px;
  transition:all .15s; white-space:nowrap;
}
.btn:disabled { opacity:.45; cursor:not-allowed; }
.btn-p  { background:var(--accent); color:#fff; }
.btn-p:hover:not(:disabled) { background:#a83d10; }
.btn-s  { background:var(--surface); color:var(--text); border:1px solid var(--border); }
.btn-s:hover:not(:disabled) { background:var(--surface2); }
.btn-g  { background:var(--green); color:#fff; }
.btn-g:hover:not(:disabled) { background:#157a4d; }
.btn-d  { background:var(--red-bg); color:var(--red); border:1px solid var(--red-bd); }
```

### Страницы импорта (паттерн)

Layout: двухколоночный grid `1fr 360px`, `max-width:1060px`, `padding:32px`, `gap:24px`.

**Левая колонка:** заголовок, описание, drop-zone, file-info, steps, progress bar, кнопка импорта.
**Правая колонка:** stats-grid (2×2 + span 2), done-banner, error-card, log-card.

```css
/* Drop zone */
.drop-zone { border:1.5px dashed var(--border2); border-radius:12px; padding:36px 24px; text-align:center; cursor:pointer; transition:all .2s; background:var(--surface); }
.drop-zone:hover, .drop-zone.over { border-color:var(--accent); background:var(--accent-bg); }

/* Steps */
.step-circle { width:24px; height:24px; border-radius:50%; border:1.5px solid var(--border2); background:var(--surface); display:flex; align-items:center; justify-content:center; font-family:'DM Mono',monospace; font-size:10px; color:var(--dim); transition:all .3s; }
.step-circle.done     { border-color:var(--green); background:var(--green-bg); color:var(--green); }
.step-circle.spinning { border-color:var(--accent); background:var(--accent-bg); color:var(--accent); animation:pulse .8s ease infinite alternate; }

/* Import button */
.btn-import { width:100%; height:42px; margin-top:18px; background:var(--accent); color:white; border:none; border-radius:8px; font-family:'DM Sans',sans-serif; font-size:14px; font-weight:600; cursor:pointer; }
.btn-import:hover:not(:disabled) { background:#b33d09; }
.btn-import:disabled { opacity:.4; cursor:not-allowed; }

/* Stat cards */
.stat-val { font-size:26px; font-weight:600; letter-spacing:-.02em; }
```

**Polling (JS паттерн для всех import страниц):**
```js
function startPolling(jobId) {
  pollTimer = setInterval(async function() {
    const r = await fetch('/BLUEPRINT/progress/' + jobId);
    const msgs = await r.json();
    msgs.forEach(handleMsg);
  }, 1500);
}
```
Endpoint `/BLUEPRINT/progress/<job_id>` возвращает JSON-массив событий и **очищает** очередь.

### Таблица (стандартная)

```css
.tw { background:var(--surface); border:1px solid var(--border); border-radius:10px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.05); }
.thr { display:flex; align-items:center; justify-content:space-between; padding:11px 16px; border-bottom:1px solid var(--border); }
.tt  { font-size:14px; font-weight:600; }
.tc  { font-family:'DM Mono',monospace; font-size:11px; color:var(--muted); }
table { width:100%; border-collapse:collapse; font-size:13px; }
thead th {
  text-align:left; padding:7px 12px;
  font-family:'DM Mono',monospace; font-size:10px;
  text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  background:var(--surface2); border-bottom:1px solid var(--border); white-space:nowrap;
}
tbody tr { border-bottom:1px solid var(--border); transition:background .1s; }
tbody tr:last-child { border-bottom:none; }
tbody tr:hover { background:#fafafa; }
td { padding:8px 12px; vertical-align:middle; }
```

### Карточки (панели)

```css
.ap { /* action panel — для форм/настроек */
  background:var(--surface); border:1px solid var(--border);
  border-radius:10px; padding:14px 18px; margin-bottom:14px;
  box-shadow:0 1px 3px rgba(0,0,0,.04);
}
```

### Бейджи

```css
.b  { display:inline-block; padding:1px 7px; border-radius:4px; font-size:10px; font-family:'DM Mono',monospace; border:1px solid; }
.be { background:var(--green-bg);  color:var(--green);  border-color:var(--green-bd); }  /* ENABLED */
.bp { background:var(--amber-bg);  color:var(--amber);  border-color:var(--amber-bd); }  /* PAUSED */
.ba { background:var(--blue-bg);   color:var(--blue);   border-color:var(--blue-bd); }   /* AUTO */
.bm { background:var(--accent-bg); color:var(--accent); border-color:var(--accent-bd); } /* MANUAL */
.bk { background:var(--blue-bg);   color:var(--blue);   border-color:var(--blue-bd); }   /* KDP */
.bus{ background:var(--green-bg);  color:var(--green);  border-color:var(--green-bd); }  /* US market */
```

### Toggle (switch) для state

```css
.stog { width:28px; height:16px; border-radius:8px; border:none; cursor:pointer; position:relative; flex-shrink:0; transition:background .2s; }
.stog::after { content:''; position:absolute; top:2px; left:2px; width:12px; height:12px; border-radius:50%; background:#fff; transition:transform .2s; }
.stog.en   { background:var(--green); }
.stog.pa   { background:var(--dim); }
.stog.en::after { transform:translateX(12px); }
.stog.pend { background:var(--amber); }
.stog.pend::after { transform:translateX(6px); }
```

### Inline bid/budget edit

```css
.bid-btn { background:none; border:none; cursor:pointer; font-family:'DM Mono',monospace; font-size:11px; color:var(--accent); padding:1px 4px; border-radius:3px; border:1px solid transparent; transition:all .15s; }
.bid-btn:hover { background:var(--accent-bg); border-color:var(--accent-bd); }
.bid-edit { display:inline-flex; align-items:center; gap:4px; vertical-align:middle; }
.bid-inp  { width:64px; height:28px; border:1px solid var(--accent); border-radius:5px; font-family:'DM Mono',monospace; font-size:12px; padding:0 6px; outline:none; background:var(--surface); color:var(--text); }
.bid-ok   { height:28px; padding:0 10px; border:none; border-radius:5px; background:var(--accent); color:#fff; font-size:12px; font-weight:600; cursor:pointer; }
.bid-cx   { height:28px; padding:0 10px; border:1px solid var(--border); border-radius:5px; background:var(--surface); color:var(--muted); font-size:12px; cursor:pointer; }
```

### Pencil (rename)

```css
.pencil-btn { background:none; border:none; cursor:pointer; color:var(--dim); padding:0 3px; opacity:0; transition:opacity .15s; display:inline-flex; align-items:center; }
.pencil-btn:hover { color:var(--accent); }
/* Показывать при hover родителя: */
.cch:hover .pencil-btn, .ggh:hover .pencil-btn, .dr:hover .pencil-btn { opacity:1; }
.name-edit-wrap { display:none; align-items:center; gap:4px; }
.name-edit-wrap.on { display:inline-flex; }
.name-inp { height:24px; border:1px solid var(--accent); border-radius:4px; font-size:13px; font-weight:500; padding:0 7px; outline:none; background:var(--surface); color:var(--text); min-width:200px; }
```

### Toast

```css
.toast { position:fixed; bottom:24px; right:24px; z-index:9999; display:flex; flex-direction:column; gap:6px; }
.toast-item { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:10px 14px; font-size:13px; box-shadow:0 4px 16px rgba(0,0,0,.1); display:flex; align-items:center; gap:8px; animation:slideIn .2s ease; }
.toast-item.ok  { border-color:var(--green-bd); }
.toast-item.err { border-color:var(--red-bd); color:var(--red); }
@keyframes slideIn { from { opacity:0; transform:translateX(20px); } to { opacity:1; transform:translateX(0); } }
```

```js
function toast(msg, ok=true){
  const w=document.getElementById('toastWrap');
  const d=document.createElement('div');
  d.className='toast-item '+(ok?'ok':'err');
  d.innerHTML=`<span>${ok?'✓':'✕'}</span> ${msg}`;
  w.appendChild(d);
  setTimeout(()=>d.remove(), 3500);
}
```

### Модалки

```css
.modal-bg { display:none; position:fixed; inset:0; background:rgba(0,0,0,.35); z-index:8000; align-items:center; justify-content:center; }
.modal-bg.op { display:flex; }
.modal { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; width:500px; max-width:95vw; box-shadow:0 8px 40px rgba(0,0,0,.15); }
.modal-title { font-size:15px; font-weight:600; margin-bottom:16px; }
.modal-label { font-family:'DM Mono',monospace; font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
.modal-inp { height:34px; border:1px solid var(--border); border-radius:6px; background:var(--surface2); color:var(--text); font-size:13px; padding:0 10px; outline:none; width:100%; }
.modal-inp:focus { border-color:var(--accent); }
.modal-acts { display:flex; gap:8px; justify-content:flex-end; margin-top:16px; }
```

### Spinner

```css
.sp2 { display:inline-block; width:13px; height:13px; border:2px solid rgba(255,255,255,.4); border-top-color:#fff; border-radius:50%; animation:spin .6s linear infinite; }
.sp-dark { border-color:var(--border); border-top-color:var(--accent); }
@keyframes spin { to { transform:rotate(360deg); } }
```

### Info / alert blocks

```css
.info { padding:9px 13px; border-radius:7px; font-family:'DM Mono',monospace; font-size:12px; display:none; }
.info.on  { display:block; }
.info.ok  { background:var(--green-bg); border:1px solid var(--green-bd); color:var(--green); }
.info.err { background:var(--red-bg);   border:1px solid var(--red-bd);   color:var(--red); }
.info.inf { background:var(--blue-bg);  border:1px solid var(--blue-bd);  color:var(--blue); }
```

### Пагинация

```css
.pg  { display:flex; align-items:center; justify-content:space-between; padding:10px 16px; border-top:1px solid var(--border); }
.pi  { font-size:11px; color:var(--muted); font-family:'DM Mono',monospace; }
.pb  { display:flex; gap:4px; }
.pbb { height:28px; min-width:28px; padding:0 7px; border-radius:5px; border:1px solid var(--border); background:var(--surface); font-size:11px; cursor:pointer; transition:all .15s; }
.pbb:hover { background:var(--surface2); }
.pbb.on    { background:var(--accent); border-color:var(--accent); color:#fff; }
.pbb:disabled { opacity:.4; cursor:not-allowed; }
```

### Campaign card (структура кампании в Products/Campaigns analytics)

```css
.cc  { background:var(--surface); border:1px solid var(--border); border-radius:8px; overflow:hidden; transition:border-color .15s; }
.cc.co { border-color:var(--accent); border-width:1.5px; } /* открытая карточка */
.cch { display:flex; align-items:center; gap:10px; padding:10px 14px; cursor:pointer; transition:background .1s; }
.cch:hover { background:var(--surface2); }
.cn  { font-size:13px; font-weight:500; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } /* campaign/group name */
.cm  { display:flex; align-items:center; gap:12px; flex-shrink:0; } /* stats right */
.cs2 { display:flex; flex-direction:column; align-items:flex-end; } /* stat pair */
.csl { font-family:'DM Mono',monospace; font-size:9px; color:var(--dim); text-transform:uppercase; }
.csv { font-family:'DM Mono',monospace; font-size:12px; font-weight:500; }
.cchev { color:var(--muted); flex-shrink:0; transition:transform .2s; }
.cchev.op { transform:rotate(180deg); }
.cst { display:none; border-top:1px solid var(--border); }
.cst.op { display:block; }
.camp-inline-meta { display:flex; align-items:center; gap:4px; flex-shrink:0; padding:0 8px; border-left:1px solid var(--border); }
```

### Tabs (внутри карточек групп)

```css
.tabs { display:flex; border-bottom:1px solid var(--border); background:#fafafa; padding:0 11px; justify-content:space-between; }
.tab  { padding:5px 9px; font-size:11px; font-family:'DM Mono',monospace; cursor:pointer; color:var(--muted); border-bottom:2px solid transparent; margin-bottom:-1px; transition:all .15s; white-space:nowrap; }
.tab:hover { color:var(--text); }
.tab.on    { color:var(--accent); border-bottom-color:var(--accent); }
.tbb { display:inline-block; padding:0 3px; margin-left:3px; border-radius:99px; font-size:9px; background:var(--surface2); color:var(--dim); }
.tab.on .tbb { background:var(--accent-bg); color:var(--accent); }
.tp   { display:none; }
.tp.on { display:block; }
```

---

## Файловая структура (~/amazon-ads/)

### Flask приложение

| Файл | Blueprint | Описание |
|---|---|---|
| `app.py` | — | Flask init, регистрация blueprints, `progress_store = {}`, HTTP Basic Auth |
| `catalog_routes.py` | `catalog_bp` | `/catalog` — импорт каталога из Productor CSV |
| `earnings_routes.py` | `earnings_bp` | `/earnings` — импорт отчётов продаж MBA (CSV) |
| `kdp_earnings_routes.py` | `kdp_earnings_bp` | `/earnings-kdp` — импорт продаж KDP (Excel) |
| `ads_routes.py` | `ads_bp` | `/ads` — сбор рекламной статистики |
| `campaigns_routes.py` | `campaigns_bp` | `/campaigns` — синхронизация структуры кампаний из SP API |
| `portfolios.py` | `portfolios_bp` | `/portfolios` — управление именами портфолио |
| `analytics_routes.py` | `analytics_bp` | `/analytics/campaigns` — аналитика кампаний |
| `products_routes.py` | `products_bp` | `/analytics/products` — аналитика по рекламируемым ASIN |
| `control_routes.py` | `control_bp` | `/control` — управление рекламой через pending_changes |

### HTML страницы

| Файл | URL | Описание |
|---|---|---|
| `index.html` | `/` | Главная — горизонтальные карточки навигации по секциям |
| `campaigns_analytics.html` | `/analytics/campaigns` | Аналитика кампаний с фильтрами, структурой, управлением |
| `products_analytics.html` | `/analytics/products` | Аналитика по рекламируемым ASIN + управление кампаниями |
| `control.html` | `/control` | Очередь изменений: Ожидают / Одобрено / История |
| `campaigns.html` | `/campaigns` | Синхронизация кампаний из SP API |
| `portfolios.html` | `/portfolios` | Управление портфолио |
| `catalog.html` | `/catalog` | Импорт каталога |
| `earnings.html` | `/earnings` | Импорт продаж Merch (CSV) |
| `earnings_kdp.html` | `/earnings-kdp` | Импорт продаж KDP (Excel, вкладка Combined Sales) |
| `ads.html` | `/ads` | Сбор статистики |

### CLI скрипты

| Файл | Описание |
|---|---|
| `collect.py` | Сбор статистики из Amazon Ads API |
| `send.py` | Отправка APPROVED изменений в Amazon API |

### Конфиги (не в git)

| Файл | Описание |
|---|---|
| `config/amazon_secrets.json` | Amazon API ключи, profiles |
| `config/bigquery_key.json` | Google Cloud сервисный аккаунт |

---

## Архитектура Flask

```
app.py
├── catalog_routes.py      → catalog_bp
├── earnings_routes.py     → earnings_bp
├── kdp_earnings_routes.py → kdp_earnings_bp
├── ads_routes.py          → ads_bp
├── campaigns_routes.py    → campaigns_bp
├── portfolios.py          → portfolios_bp
├── analytics_routes.py    → analytics_bp
├── products_routes.py     → products_bp
└── control_routes.py      → control_bp
```

`progress_store = {}` — shared dict в `app.py`, используется всеми blueprints:
```python
def _get_progress_store():
    import app
    return app.progress_store
```

---

## KDP Earnings (kdp_earnings_routes.py)

### Источник данных
**KDP Sales Report** — Excel файл (.xlsx), скачивается из KDP Reports → Sales Dashboard.
Используется вкладка **«Combined Sales»** — содержит все типы: Paperback, Hardcover, eBook.

### Endpoints

| Метод | URL | Описание |
|---|---|---|
| `POST` | `/kdp-earnings/upload` | Принимает `.xlsx`, запускает импорт в фоне, возвращает `{job_id}` |
| `GET` | `/kdp-earnings/progress/<job_id>` | Polling: возвращает JSON-массив событий и очищает очередь |
| `GET` | `/kdp-earnings/count` | Количество строк в таблице `earnings_kdp` |

### Шаги импорта
1. Читаем Excel (`pandas`, вкладка `Combined Sales`, `dtype=str`)
2. Парсим строки → dict, дедупликация по MD5-хэшу `(royalty_date, asin_isbn, marketplace, transaction_type, units_sold, units_refunded, royalty, currency)`
3. Проверяем существующие хэши в BigQuery (батчи по 10 000)
4. Загружаем только новые строки (`WRITE_APPEND`, чанки по 1000)

### Маршрут в app.py
```python
from kdp_earnings_routes import kdp_earnings_bp
app.register_blueprint(kdp_earnings_bp)

@app.route('/earnings-kdp')
def earnings_kdp():
    return send_from_directory(BASE_DIR, 'earnings_kdp.html')
```

---

## Analytics API (analytics_routes.py)

### GET /analytics/campaigns → campaigns_analytics.html
### GET /analytics/campaigns/data
Параметры: `account_type`, `date_from`, `date_to`, `marketplace`, `portfolio_id`, `portfolio_ids`,
`targeting_type`, `campaign_state`, `activity`, `name`, `sort_by`, `sort_dir`, `page`, `per_page`

Числовые фильтры: `clicks_op/val/min/max`, `acos_op/val/min/max`, `cost_*`, `impressions_*`, `sales_14d_*`, `ctr_*`

Возвращает: `rows`, `total`, `page`, `per_page`, `summary`

### GET /analytics/campaigns/portfolios
Уникальные портфолио из `campaigns_merch/kdp` с JOIN на `portfolio_labels`

Параметры: `account_type`, `marketplace`, `targeting_type`, `campaign_state`

Возвращает: `{"portfolios": [{"id": "...", "name": "..."}]}`

**Важно:** endpoint зарегистрирован дважды в `analytics_routes.py` (баг). Flask использует первую функцию.

### GET /analytics/campaigns/structure
Структура кампании: группы → таргеты + ключевые слова + поисковые запросы + минус слова + объявления + статистика

Параметры: `campaign_id`, `account_type`, `date_from`, `date_to`

**Важно:** `targeting_type` **не возвращается** на уровне кампании в ответе. Нужно брать из строки таблицы campaigns (поле `r.targeting_type`) и передавать через `state._expandedTgt` или аргумент функции.

**Оптимизация (июнь 2026):** 5 BigQuery запросов запускаются параллельно (все `client.query()` без `.result()`, потом все `.result()`). Ожидаемое ускорение ~3x по сравнению с последовательным выполнением.

Возвращает:
```json
{
  "campaign_name": "...",
  "campaign_end_date": "2026-06-30",
  "groups": [{
    "id": "...", "name": "...", "bid": 0.5, "state": "ENABLED",
    "stats": {"impressions": 1000, "clicks": 10, "cost": 5.0, "sales_14d": 20.0, "purchases_14d": 2, "acos": 25.0},
    "keywords": [{"id": "...", "text": "...", "match_type": "BROAD", "bid": 0.5, "state": "ENABLED", "stats": {...}, "search_terms": [...]}],
    "targets": [{...}],
    "negatives": [{"text": "...", "match_type": "EXACT", "type": "keyword"}],
    "search_terms": [...],
    "ads": [{"ad_id": "...", "asin": "...", "title": "...", "image_url": "...", "stats": {...}}]
  }],
  "adjustments": [{"placement": "TOP_OF_SEARCH", "percentage": 30}],
  "campaign_negatives": [{"text": "...", "type": "keyword"}]
}
```

**Search terms:**
- AUTO кампании: `search_terms` на уровне группы
- MANUAL кампании: `search_terms` на уровне ключевого слова
- В JS собирать из обоих:
```js
const allSt = [
  ...(g.search_terms || []),
  ...(g.keywords || []).flatMap(kw => kw.search_terms || []),
  ...(g.targets || []).flatMap(t => t.search_terms || []),
];
```

---

## Campaigns Analytics (campaigns_analytics.html)

### Функциональность
- Фильтры: Аккаунт (MERCH/KDP), даты, маркетплейс, портфолио (custom dropdown с чекбоксами), таргетинг, статус, активность, поиск
- Числовые фильтры в заголовках колонок (попап с операторами)
- Сводная статистика (grid 6 карточек)
- Таблица кампаний: сортировка, пагинация, resize колонок
- **Inline редактирование названия кампании** — карандаш при hover, `saveName()`
- **Inline редактирование бюджета** — клик на сумму в колонке Бюджет, `saveBudget()`
- Клик на строку → раскрытие структуры кампании (expand row)

### Структура drill-down
- **Группы** как карточки `.cc` (стиль products): toggle, имя + карандаш, inline ставка группы, статы, бейджи AUTO/MANUAL
- Кнопка **+ Группа** над списком групп
- **Вкладки** группы: Таргеты / Поисковые запросы / Минус слова / Объявления
- Кнопки **+ Ключевое слово** и **+ Минус** в панели вкладок
- **Inline редактирование ставок** ключевых слов и таргетов

### Targeting type
`targeting_type` берётся из строки таблицы (`r.targeting_type`) и сохраняется в `state._expandedTgt`.
`buildCampHtml()` использует как fallback если API не вернул тип:
```js
if(!tgtType) tgtType = (state._expandedTgt || '').toUpperCase();
```

### Портфолио dropdown
Custom dropdown `.pdw` со стрелкой внутри `.pdt` (не абсолютно позиционированной):
```html
<div class="pdt" id="pdtBtn" onclick="togglePd()">
  <span id="pdtLabel">Все</span>
  <span class="pda">▾</span>  <!-- ВНУТРИ .pdt, не снаружи -->
</div>
```

---

## Products API (products_routes.py)

### GET /analytics/products
Возвращает `products_analytics.html`

### GET /analytics/products/data
Список рекламируемых ASIN с агрегированной статистикой.

Параметры: `account_type`, `date_from`, `date_to`, `marketplace`, `portfolio_ids`, `asin`,
`sort_by`, `sort_dir`, `page`, `per_page`

SQL: JOIN `asin_stats_{suffix}` с `campaigns_{suffix}` (фильтр по портфолио/маркетплейсу),
LEFT JOIN `catalog` для названия, изображения, статуса, цены.

**Алиасы в SQL:** CTE использует алиас `camp` (не `c`) чтобы не конфликтовать с `cat` (catalog).

**Оптимизация (июнь 2026):** один запрос вместо трёх — window functions `COUNT(*) OVER()`, `SUM(...) OVER()` возвращают total и summary прямо в строках результата. Python читает из первой строки и удаляет через `pop`.

Возвращает:
```json
{
  "rows": [{"asin": "...", "marketplace": "US", "impressions": ..., "clicks": ...,
            "cost": ..., "sales_14d": ..., "purchases_14d": ..., "campaign_count": ...,
            "ctr": ..., "acos": ..., "title": "...", "image_url": "...",
            "product_type": "STANDARD_TSHIRT", "price": "19.95", "status": "PUBLISHED"}],
  "total": 5752, "page": 1, "per_page": 50,
  "summary": {"total_asins": ..., "impressions": ..., "clicks": ..., "cost": ...,
               "sales_14d": ..., "purchases_14d": ..., "acos": ..., "ctr": ...}
}
```

### GET /analytics/products/campaigns
Кампании для конкретного ASIN за период.

Параметры: `asin`, `marketplace`, `account_type`, `date_from`, `date_to`

Возвращает список кампаний с полями:
`campaign_id`, `campaign_name`, `campaign_state`, `targeting_type`, `portfolio_name`,
`daily_budget`, `campaign_end_date` (добавлены через `MAX(camp.daily_budget)` и `MAX(camp.end_date)`),
`impressions`, `clicks`, `cost`, `sales_14d`, `purchases_14d`, `ctr`, `acos`, `marketplace`

---

## Products Analytics (products_analytics.html)

### Функциональность
- Таблица рекламируемых ASIN с фото из каталога, статистикой, фильтрами
- Клик по строке → inline-панель кампаний
- Клик по кампании → структура групп с вкладками
- Полное управление кампаниями: toggle, inline bid/budget/name, + Группа, + KW, + Минус

### Оптимизация /analytics/products/data (июнь 2026)
Вместо 3 отдельных BigQuery запросов (rows + count + summary) — один запрос с window functions:
```sql
-- filtered CTE применяет WHERE фильтры, потом:
COUNT(*) OVER ()                    AS _total,
SUM(f.impressions) OVER ()          AS _sum_impressions,
SUM(f.clicks) OVER ()               AS _sum_clicks,
ROUND(SUM(f.cost) OVER (), 2)       AS _sum_cost,
ROUND(SUM(f.sales_14d) OVER (), 2)  AS _sum_sales,
SUM(f.purchases_14d) OVER ()        AS _sum_purchases
```
Python читает window-значения из первой строки и удаляет их из rows через `pop`. JSON-ответ идентичен старому.

### Хедер кампании (строка кампании)
Прямо в строке кампании встроены:
- **Toggle** state (ENABLED/PAUSED)
- **Название кампании** + карандашик для переименования (появляется при hover над строкой)
- **Бюджет** — inline-редактирование: кликаешь на значение → появляется поле ввода + ✓/✕, Enter сохраняет
- **Дата окончания** — inline-редактирование: кликаешь → date input + ✓/✕, показывает `∞` если бессрочно
- Бейджи MANUAL/AUTO, ENABLED/PAUSED
- Статистика: Показы · Клики · Расходы · Продажи · Заказы · ACOS · Портфолио
- Стрелка раскрытия структуры

### Структура кампании (после раскрытия)
- **Кнопка + Группа** над списком групп (всегда видна)
- Список групп

### Хедер группы
- **Toggle** state
- **Название группы** + карандашик для переименования (появляется при hover)
- Статистика: Показы · Клики · Расходы · Продажи · Заказы · ACOS
- Стрелка раскрытия вкладок

### Вкладки группы
- **Таргеты** — ключевые слова и авто-таргеты с кнопками + Ключевое слово, + Минус
- **Поисковые запросы** — search terms
- **Минус слова** — негативные ключи и ASIN

### Колонки ключевых слов/таргетов (класс `.ii`)
```
grid-template-columns: 24px 1fr 60px 80px 80px 70px 65px 88px 85px 72px
Toggle · Текст · Тип · Ставка · Показы · Клики · Заказы · Расходы · Продажи · ACOS
```

### Колонки поисковых запросов (класс `.ii.st`)
```
grid-template-columns: 25px 1fr 150px 80px 70px 65px 88px 85px 72px
Чекбокс · Запрос · Таргет/тип · Показы · Клики · Заказы · Расходы · Продажи · ACOS
```
CSS классы `.ih` / `.ii` и `.ih.st` / `.ii.st` задают сетку только через CSS — без inline `style=` переопределений.

### Пакетное добавление минусов из поисковых запросов (июнь 2026)
Вкладка «Поисковые запросы» — чекбоксы слева от каждой строки. При выборе появляется кнопка **«→ Минус (N)»**.

`stCbChange(gid)` — обновляет счётчик и показывает/скрывает кнопку.

`openNegFromSt(groupId, campId, mkt)` — собирает выбранные термины, разделяет на слова и ASINы:
- `isAsin(str)` — паттерн `/^[Bb][0-9A-Za-z]{9}$/`
- Только ASINы → открывает modalNeg в режиме «Продукт»
- Только слова → открывает в режиме «Слово»  
- Смешанный → слова в модалку, ASINы в очередь автоматически после сабмита (`window._pendingNegAsins`)

После `submitAddNeg()` — все чекбоксы в группе снимаются.

### Ставка с fallback на ставку группы
Если у ключевого слова нет своей ставки (bid=null), показывается ставка группы серым курсивом с пометкой `(г)`:
```js
const bidVal = it.bid ? Number(it.bid).toFixed(2) : (g.bid ? Number(g.bid).toFixed(2) : '');
const bidIsGroup = !it.bid && g.bid;
// В HTML: style="${bidIsGroup?'color:var(--dim);font-style:italic':''}"
```

### Inline-редактирование ставки
Кликаешь на ставку → появляется поле + ✓/✕. Функции: `openBidEdit`, `closeBidEdit`, `saveBid`.
`saveBid(event, containerId, entityType, entityId, oldBid, mkt)` — отправляет через `ctrlAdd`.

### Inline-редактирование бюджета и даты
`openBudgetEdit(event, wrapId)` — показывает поле, скрывает кнопку.
`closeBudgetEdit(wrapId, dispId)` — скрывает поле, показывает кнопку.
`saveBudget(campId, mkt, oldBudget)` — обновляет текст кнопки после сохранения.
`saveEndDate(campId, mkt, oldDate)` — то же для даты.

### Inline-редактирование названий (карандашик)
`openNameEdit(e, dispId, wrapId)` — скрывает span с названием, показывает input.
`closeNameEdit(dispId, wrapId)` — обратно.
`saveName(e, entityType, entityId, dispId, wrapId, mkt)` — отправляет через `ctrlAdd`, обновляет текст.
Карандашик: CSS `.pencil-btn { opacity: 0 }`, `.cch:hover .pencil-btn { opacity: 1 }`.

### Модал + Ключевое слово
Поля: текст слов (по одному на строку), Match Type (BROAD/PHRASE/EXACT), Ставка KW.
Создаёт по одному `keyword_add` для каждого слова.

### Модал + Минус
Тип: **Слово** или **Продукт (ASIN)**.
- Слово: текст + Match Type → `negative_add`
- Продукт: ASIN (по одному на строку) → `negative_product_add`
`onNegTypeChange(radio)` — переключает label и placeholder, скрывает/показывает Match Type.

**Отправка пачкой:** `submitAddNeg` использует `ctrlAddBatch(payloads)` — один запрос для всех строк вместо N параллельных. Аналогично `submitAddKw` и `submitCreateGrp`.

### Модал + Группа
Открывается с параметром `targeting_type` кампании (`openCreateGrp(campId, mkt, targetingType)`).
- **AUTO кампания**: Название + Ставка группы + ASIN объявлений
- **MANUAL кампания**: Название + Ставка группы + ASIN объявлений + Ключевые слова (текст + match type + ставка KW)

`submitCreateGrp()` добавляет в очередь одним пакетом:
1. `ad_group_add` — создание группы
2. `product_ad_add` × N — по одному на каждый ASIN объявления
3. `keyword_add` × N — по одному на каждое ключевое слово (только MANUAL)

### Scroll без прыжков
- `html { overflow-anchor: none }` — отключает браузерный scroll anchoring
- `rowClick` — вставляет expand-строку через `tr.after()`, не перерисовывает таблицу
- `grpClick(this)` — передаёт header-элемент, навигация через `closest('.gg')` + `querySelector('.ggb')`, двойной `requestAnimationFrame` для восстановления `scrollY`
- Вкладки через `tabClick(event, idx)` без ID групп — `closest('.ggb')` для точного контейнера

### Хедер кампании (строка кампании в Products)
```js
// campClick получает targeting_type из карточки кампании:
onclick="campClick('${cid}','${asin}','${c.marketplace||''}','${c.targeting_type||''}')"
// buildStruct получает tgtTypeFallback:
function buildStruct(data, filterAsin, campId='', mkt='', tgtTypeFallback=''){
  const tgtTypeForGrp = (data.targeting_type || data.groups?.[0]?.targeting_type || tgtTypeFallback || '').toUpperCase();
```

### Фильтрация групп по ASIN
```js
const anyHasAsin = groups.some(g => g.ads.some(a => a.asin === filterAsin));
// MANUAL: только группы с совпадающим ASIN в ads
// AUTO: нет ASIN в ads → группы с clicks > 0
// Ads есть но asin null → группы с clicks > 0
```

---

## Control Page (control.html)

### Вкладки
- **Ожидают** — PENDING изменения с чекбоксами для batch approve/reject
- **Одобрено** — APPROVED с кнопкой "Отправить в Amazon"
- **История** — change_log с результатами отправки

### Колонки таблицы
ТИП | МКТ | ID | КАМПАНИЯ/ГРУППА | НАЗВАНИЕ | ПОЛЕ | БЫЛО | СТАЛО | СОЗДАНО/ОТПРАВЛЕНО | ДЕЙСТВИЯ/РЕЗУЛЬТАТ

**КАМПАНИЯ/ГРУППА** (`context_name`) — контекст сущности:
- Действия уровня кампании (`campaign`, `ad_group_add`) → `campaign_name`
- Действия уровня группы (`ad_group`, `keyword_add`, `negative_add`, `negative_product_add`, `product_ad_add`) → `ad_group_name`
- Ключи/таргеты/минусы (`keyword`, `target`, `negative_delete`) → `ad_group_name` через JOIN по `ad_group_id`

**Важно:** `ad_group_name` на строках `product_targeting`/`keyword` в campaigns таблице равен NULL — берётся через JOIN с `entity_type='ad_group'`

### Форматирование значений

**БЫЛО** (`fmtOld(r)`):
- `state` → `▶ ON` / `⏸ OFF` зачёркнутый
- `bid/budget` → `$X.XX` зачёркнутый
- `_add` операции → `—`

**СТАЛО** (`fmtNew(r)`):
- `state` → `▶ Включить` (зелёный) / `⏸ Выключить` (серый)
- `bid/budget` → `$X.XX` синий + дельта `(+0.02)` зелёный/красный
- `name` → новое имя
- `ad_group_add` → карточка: Группа + Ставка
- `keyword_add` → карточка: Фраза + Тип + Ставка + Группа
- `negative_add/product_add` → карточка: 🚫 слово/ASIN + Тип
- `product_ad_add` → карточка: ASIN + Группа

**РЕЗУЛЬТАТ** (`fmtResult(r)`):
- SUCCESS → `✓ OK` зелёный
- FAILED → Amazon error code badge + сообщение

### Фильтрация типов
Фильтрация только на фронте (клиентская) — `/control/log` не поддерживает параметр `entity_type`.
`/control/pending` также фильтрует на клиенте через `.filter(r => !S.typeFilter || r.entity_type === S.typeFilter)`.

### Название и контекст (entity_name + context_name)
`control_routes.py` возвращает два поля:
- `entity_name` — текст ключа / ASIN / название кампании или группы (как было)
- `context_name` — **новое**: кампания или группа в зависимости от уровня сущности

```python
# campaign-level → campaign_name
CAMP_LEVEL = {"campaign", "ad_group_add"}
# group-level (entity_id = ad_group_id) → ad_group_name
GROUP_LEVEL = {"ad_group", "keyword_add", "negative_add", "negative_product_add", "product_ad_add"}
# keyword/target → ad_group_name через JOIN по ad_group_id
# (ad_group_name NULL на строках product_targeting/keyword — нужен JOIN с entity_type='ad_group')
```

JOIN для keyword/target/negative_delete:
```sql
SELECT DISTINCT t.target_id AS eid, ag.ad_group_name AS name
FROM campaigns_merch t
JOIN campaigns_merch ag
  ON ag.ad_group_id = t.ad_group_id
 AND ag.entity_type = 'ad_group'
 AND ag.marketplace = t.marketplace
WHERE t.target_id IN (...) AND t.entity_type='product_targeting'
```

---

## Control API (control_routes.py)

### POST /control/add
```json
{
  "account_type": "MERCH", "marketplace": "US", "profile_id": "2418854071638725",
  "entity_type": "campaign", "entity_id": "313276520414059",
  "field_name": "state", "old_value": "ENABLED", "new_value": "PAUSED"
}
```
Возвращает: `{"success": true, "id": "uuid", "label": "⏸ Пауза"}`
409 если уже есть PENDING (кроме NO_DUP_CHECK типов)

### POST /control/add_batch
Принимает массив NO_DUP_CHECK операций, один `load_table_from_json` на все строки.
```json
{"items": [{...}, {...}]}
```
Возвращает: `{"success": true, "inserted": 20, "errors": [], "ids": [...]}`
Поддерживает только: `keyword_add`, `negative_add`, `negative_product_add`, `ad_group_add`, `product_ad_add`.
Максимум 500 элементов за раз.

**Использование в JS:** `ctrlAddBatch(payloads)` — все submit-функции (submitAddKw, submitAddNeg, submitCreateGrp) используют этот endpoint вместо N параллельных `/control/add`. Скорость: 1 round-trip вместо N.

**ad_group_add дедупликация** — дополнительная проверка по `(campaign_id + имя группы)`:
```python
if entity_type == 'ad_group_add':
    _ag_name = json.loads(new_value).get('name', '')
    # BigQuery: WHERE entity_id=campaign_id AND JSON_VALUE(new_value,'$.name')=ag_name AND status IN ('PENDING','APPROVED')
    # → 409 если дубль
```

### Допустимые операции (ALLOWED_OPS)

| entity_type | field_name | Описание |
|---|---|---|
| `campaign` | `state` / `name` / `daily_budget` / `portfolio_id` / `end_date` | |
| `ad_group` | `state` / `name` / `default_bid` | |
| `keyword` | `state` / `bid` | |
| `target` | `state` / `bid` | Авто-таргеты |
| `product_ad` | `state` | |
| `keyword_add` | `—` | JSON `{text, match_type, bid, ad_group_id?, ad_group_name?, campaign_id}` |
| `negative_add` | `—` | JSON `{text, match_type, ad_group_id, campaign_id}` |
| `negative_product_add` | `—` | JSON `{asin, ad_group_id, campaign_id}` |
| `negative_delete` | `—` | entity_id = keyword_id |
| `ad_group_add` | `—` | JSON `{name, default_bid, campaign_id}` |
| `product_ad_add` | `—` | JSON `{asin, campaign_id, ad_group_id?, ad_group_name?}` |

### NO_DUP_CHECK
```python
NO_DUP_CHECK = {'keyword_add', 'negative_add', 'negative_product_add', 'product_ad_add'}
# ad_group_add убран из NO_DUP_CHECK — имеет собственную проверку по имени
```

---

## send.py

Читает `APPROVED` из `pending_changes`, отправляет в Amazon API, пишет в `change_log`.

```bash
python3 send.py                      # все APPROVED
python3 send.py --account MERCH      # только Merch
python3 send.py --marketplace US     # только US
python3 send.py --all                # MERCH + KDP
python3 send.py --dry-run            # показать без отправки
```

### Схема статусов pending_changes

```
PENDING → APPROVED → SENDING → SENT
                             → FAILED
          REJECTED (вручную)
```

| Статус | Когда |
|---|---|
| `PENDING` | Создано, ждёт одобрения |
| `APPROVED` | Одобрено, ждёт отправки |
| `SENDING` | Скрипт взял в работу прямо сейчас |
| `SENT` | Успешно принято Amazon |
| `FAILED` | Amazon вернул ошибку (см. `error_msg`) |
| `REJECTED` | Отклонено вручную |

### Надёжность (защита от зависания)

**Проблема:** если скрипт завис после отправки в Amazon, но до записи в `change_log` — изменения применены, но нет ни записи в истории, ни смены статуса.

**Три уровня защиты:**

1. **`reset_stale_sending`** — первым делом при запуске: находит все `SENDING` без соответствующей записи `SUCCESS` в `change_log` → сбрасывает в `APPROVED`. Это восстанавливает зависшие записи в очередь.

2. **Запись после каждого батча** — `write_changelog` + `mark_done`/`mark_failed` вызываются сразу после каждой группы операций (`update_campaigns`, `create_targets`, ...), а не в конце всего цикла. Если скрипт упадёт на следующем батче — предыдущие уже сохранены.

3. **Идемпотентный `fetch_pending`** — читает `APPROVED` и `SENDING`, но исключает те, у которых уже есть запись `SUCCESS` в `change_log`. Повторный запуск не отправит уже отправленное.

```python
# fetch_pending исключает уже успешные:
AND p.id NOT IN (
    SELECT pending_id FROM change_log WHERE result = 'SUCCESS'
)

# reset_stale_sending в начале send_changes:
UPDATE pending_changes SET status = 'APPROVED'
WHERE status = 'SENDING'
AND id NOT IN (SELECT pending_id FROM change_log WHERE result = 'SUCCESS')
```

**Ручное восстановление зависших SENDING (если нужно):**
```sql
UPDATE `amazon-ads-api-494412.amazon_ads.pending_changes_merch`
SET status = 'APPROVED'
WHERE status = 'SENDING'
AND id NOT IN (
    SELECT pending_id FROM `amazon-ads-api-494412.amazon_ads.change_log_merch`
    WHERE result = 'SUCCESS'
)
```

**FAILED с ошибкой `Last batch failed`** — артефакт старого кода (писал одно сообщение на весь батч). Это не реальная ошибка Amazon — можно сбросить в `APPROVED` и отправить повторно:
```sql
UPDATE `amazon-ads-api-494412.amazon_ads.pending_changes_merch`
SET status = 'APPROVED'
WHERE status = 'FAILED' AND error_msg = 'Last batch failed'
```

### Ключевые фиксы (актуальные)

**Дедупликация ad_group_add по (name, campaign_id):**
```python
seen_ag_keys = set()
for _, change in ag_changes:
    val = json.loads(change["new_value"])
    camp_id = val.get("campaign_id") or change["entity_id"]
    ag_key = (val["name"], camp_id)
    if ag_key in seen_ag_keys:
        continue
    seen_ag_keys.add(ag_key)
    ag_payloads.append({...})
    ag_camp_id[(val["name"], camp_id)] = camp_id
```

**Матчинг keyword → adGroup по составному ключу (name, campaign_id):**
```python
# При парсинге ответа API используем index для точного campaign_id:
for item in rj.get("success", []):
    ag_id = ag.get("adGroupId"); ag_name = ag.get("name"); idx = item.get("index", -1)
    if 0 <= idx < len(ag_payloads):
        camp_id_for_ag = ag_payloads[idx]["campaignId"]  # точный campaign_id по позиции
    ag_name_to_id[(ag_name, camp_id_for_ag)] = ag_id
    ag_name_to_id[ag_name] = ag_id  # fallback

# При поиске для keyword/product_ad:
ag_id = (ag_name_to_id.get((ag_name, camp_id))
         or ag_name_to_id.get(ag_name)
         or val.get("ad_group_id", ""))
```

### Amazon API endpoints

| Endpoint | Операции |
|---|---|
| `POST /adsApi/v1/update/campaigns` | state, name, budgets, portfolioId, endDateTime |
| `POST /adsApi/v1/update/adGroups` | state, name, bid.defaultBid |
| `POST /adsApi/v1/update/targets` | bid, state (keyword + target) |
| `POST /adsApi/v1/update/ads` | product_ad state |
| `POST /adsApi/v1/create/targets` | keyword_add, negative_add, negative_product_add |
| `POST /adsApi/v1/delete/targets` | negative_delete |
| `POST /adsApi/v1/create/adGroups` | ad_group_add |
| `POST /adsApi/v1/create/ads` | product_ad_add |

### SP API v1 форматы (выверены)

**Бюджет кампании:**
```python
{"budgetType": "MONETARY", "recurrenceTimePeriod": "DAILY",
 "budgetValue": {"monetaryBudgetValue": {
   "monetaryBudget": {"value": float(val)},
   "marketplaceSettings": [{"marketplace": mkt_code, "monetaryBudget": {"value": float(val)}}]
}}}
```

**Дата окончания** (с timezone offset):
```python
MKT_OFFSET = {"US":-5,"CA":-5,"UK":0,"DE":1,"FR":1,"IT":1,"ES":1,"AU":10,...}
item["endDateTime"] = f"{val}T23:59:59{sign}{abs(offset):02d}:00"
# US: "2026-06-30T23:59:59-05:00"
```

**Ставка (update/targets):**
```python
item["bid"] = {"bid": float(val), "currencyCode": currency}
```

**Создание keyword_add:**
```python
{
    "adGroupId": ag_id, "campaignId": camp_id,
    "adProduct": "SPONSORED_PRODUCTS", "negative": False, "state": "ENABLED",
    "targetType": "KEYWORD",
    "targetDetails": {"keywordTarget": {"matchType": "BROAD", "keyword": "pirate shirt"}},
    "bid": {"bid": 0.5, "currencyCode": "USD"}
}
```

**Создание negative_add:**
```python
# matchType БЕЗ префикса NEGATIVE_: "NEGATIVE_EXACT" → "EXACT"
mt = raw_mt.replace("NEGATIVE_", "")
{"adProduct": "SPONSORED_PRODUCTS", "negative": True, "state": "ENABLED",
 "targetType": "KEYWORD",
 "targetDetails": {"keywordTarget": {"matchType": mt, "keyword": val["text"]}}}
```

**Создание negative_product_add (ASIN):**
```python
{"adProduct": "SPONSORED_PRODUCTS", "negative": True, "state": "ENABLED",
 "targetType": "PRODUCT",
 "targetDetails": {"productTarget": {
     "matchType": "PRODUCT_EXACT",
     "productIdType": "ASIN",
     "product": {"productId": val["asin"], "productIdType": "ASIN"}
}}}
```

**Создание ad_group_add:**
```python
{"campaignId": camp_id, "adProduct": "SPONSORED_PRODUCTS",
 "name": val["name"], "state": "ENABLED",
 "bid": {"defaultBid": float(val.get("default_bid", 0.5))}}
```

**Создание product_ad_add:**
```python
{"adGroupId": ag_id, "adProduct": "SPONSORED_PRODUCTS",
 "adType": "PRODUCT_AD", "state": "ENABLED",
 "creative": {"productCreative": {"productCreativeSettings": {
     "advertisedProduct": {"productId": val["asin"], "productIdType": "ASIN"}
}}}}
```

### Мёрдж изменений одной кампании
`send_update_campaigns` группирует state + budget + end_date одной кампании в единый payload.
Иначе Amazon возвращает `DUPLICATE_RESOURCE_ID_FOUND`.

---

## campaigns_routes.py

### _dt_to_date(dt_str, marketplace)
Конвертирует ISO datetime → дату в локальном времени маркетплейса.
```python
# "2026-07-01T04:59:59Z" + marketplace="US" → "2026-06-30"
```

### Синхронизация
- `DELETE FROM campaigns_merch WHERE marketplace = 'US'` — перед вставкой (только по маркетплейсу)
- Статистика (`targets_stats`, `asin_stats`) не затрагивается

---

## Amazon Ads API

### Профили (profile_id)
```
MERCH_US:  2418854071638725  → advertising-api.amazon.com
MERCH_UK:  180261448232436   → advertising-api-eu.amazon.com
MERCH_DE:  2023177291219092  → advertising-api-eu.amazon.com
MERCH_FR:  613747068444603   → advertising-api-eu.amazon.com
MERCH_IT:  1643110315908506  → advertising-api-eu.amazon.com
MERCH_ES:  3571496662552642  → advertising-api-eu.amazon.com
KDP_US:    2138688425253475  → advertising-api.amazon.com
KDP_CA:    216157406396956   → advertising-api.amazon.com
KDP_UK:    3828973734410759  → advertising-api-eu.amazon.com
KDP_DE:    1209740463543490  → advertising-api-eu.amazon.com
KDP_FR:    2062477294536113  → advertising-api-eu.amazon.com
KDP_IT:    2012455889033628  → advertising-api-eu.amazon.com
KDP_ES:    1530105280135495  → advertising-api-eu.amazon.com
KDP_AU:    2089815793960864  → advertising-api-fe.amazon.com
```

### Типы отчётов (Reporting API v3)
| reportTypeId | groupBy | Таблица BQ |
|---|---|---|
| spTargeting | targeting | targets_stats_merch / targets_stats_kdp |
| spAdvertisedProduct | advertiser | asin_stats_merch / asin_stats_kdp |
| spSearchTerm | searchTerm | search_terms_merch / search_terms_kdp |

---

## Таблицы BigQuery (dataset: amazon_ads)

### campaigns_merch / campaigns_kdp
```sql
entity_type     -- campaign / ad_group / keyword / negative_keyword /
                -- negative_product_targeting / product_targeting /
                -- product_ad / bidding_adjustment
campaign_id, campaign_name, targeting_type, campaign_state
daily_budget, start_date, end_date
portfolio_id, portfolio_name
ad_group_id, ad_group_name, ad_group_default_bid, ad_group_state
keyword_id, keyword_text, match_type, keyword_bid, keyword_state
target_id, targeting_expression, target_bid, target_state
ad_id, sku, asin, ad_state
placement, placement_percentage
marketplace, synced_at
```

### targets_stats_merch / targets_stats_kdp
```sql
date, campaign_id, ad_group_id, keyword_id, keyword, keyword_type, targeting
impressions, clicks, cost, top_of_search_impression_share
purchases_1d/7d/14d, sales_1d/7d/14d
marketplace
```

### asin_stats_merch / asin_stats_kdp
```sql
date, campaign_id, ad_group_id, advertised_asin, advertised_sku
impressions, clicks, cost
purchases_1d/7d/14d, sales_1d/7d/14d
marketplace
```

### search_terms_merch / search_terms_kdp
```sql
date, campaign_id, ad_group_id, keyword_id, keyword, keyword_type
targeting, match_type, search_term
impressions, clicks, cost
purchases_1d/7d/14d, sales_1d/7d/14d
marketplace
```

### pending_changes_merch / pending_changes_kdp
```sql
id, created_at, entity_type, entity_id, profile_id, marketplace
field_name, old_value, new_value
status   -- PENDING → APPROVED → SENDING → SENT / FAILED / REJECTED
error_msg, retry_count
```

### change_log_merch / change_log_kdp
```sql
id, pending_id, sent_at
entity_type, entity_id, profile_id, marketplace
field_name, old_value, new_value
result    -- SUCCESS / FAILED
error_msg
```

### portfolio_labels
```sql
portfolio_id, portfolio_name, account_type, marketplace, notes
```

### catalog
```sql
listing_id, asin, marketplace, design_id, brand, title
product_type, price, status
image_url, live_url, edit_url
bullet_point_1, bullet_point_2
```

### earnings (Merch)
```sql
row_hash, sale_date, asin, marketplace, product_type
purchased, cancelled, returned, royalties, revenue, currency
imported_at
```

### earnings_kdp
```sql
row_hash          -- MD5 ключ дедупликации
royalty_date      -- DATE, партиция по этому полю
asin_isbn         -- ASIN или ISBN-13 (STRING)
title             -- название книги
author            -- имя автора
marketplace       -- Amazon.com / Amazon.co.uk / etc.
royalty_type      -- 60% / 50%
transaction_type  -- Standard - Paperback / Hardcover / eBook
units_sold        -- INT64
units_refunded    -- INT64
net_units_sold    -- INT64
list_price        -- средняя цена листинга без налогов
offer_price       -- средняя цена предложения без налогов
delivery_cost     -- средняя стоимость доставки/производства
royalty           -- роялти в валюте
currency          -- USD / GBP / EUR / AUD / CAD / JPY / ...
imported_at       -- TIMESTAMP
-- Партиция: royalty_date; Кластеризация: marketplace, asin_isbn
```

---

## Авто-таргеты — маппинг

| `targets_stats.targeting` | `campaigns_merch.targeting_expression` |
|---|---|
| `close-match` | `KEYWORDS_CLOSE_MATCH` |
| `loose-match` | `KEYWORDS_LOOSE_MATCH` |
| `substitutes` | `PRODUCT_SUBSTITUTES` |
| `complements` | `PRODUCT_COMPLEMENTS` |

---

## Portfolios API (portfolios.py)

```
GET  /portfolios                      → HTML страница
POST /portfolios/update               → обновляет одну запись локально в BigQuery
POST /portfolios/bulk-update          → обновляет массив {changes: [...]} локально в BigQuery
GET  /portfolios/list                 → все портфолио из portfolio_labels
GET  /portfolios/profiles             → список профилей из amazon_secrets.json (для dropdown)
POST /portfolios/amazon-sync-names    → загружает названия из Amazon API для всех профилей, MERGE в portfolio_labels
POST /portfolios/amazon-create        → создаёт портфолио в Amazon API + добавляет в portfolio_labels
POST /portfolios/amazon-update        → переименовывает портфолио в Amazon API + обновляет portfolio_labels
```

### Удалённые endpoints (июнь 2026)
- `POST /portfolios/sync` — сканирование campaigns_* таблиц не нужно, т.к. `amazon-sync-names` сам создаёт новые записи
- `POST /portfolios/import-csv` — заменён на `amazon-sync-names`

### amazon-sync-names
Для каждого профиля вызывает `POST /portfolios/list` (Amazon API v3, `application/vnd.spPortfolio.v3+json`) с пагинацией через `nextToken`. Собирает все строки в памяти, затем:
1. `DROP TABLE IF EXISTS portfolio_sync_tmp`
2. `CREATE TABLE portfolio_sync_tmp`
3. `LOAD` все строки одним batch job
4. `MERGE portfolio_labels` — UPDATE если portfolio_id существует, INSERT если нет

### amazon-create / amazon-update
- Content-Type: `application/vnd.spPortfolio.v3+json`
- `POST /portfolios` для создания, `PUT /portfolios` для обновления
- `state` поддерживает только `ENABLED`
- После успешного ответа Amazon — синхронизирует `portfolio_labels` в BigQuery

### portfolios.html (июнь 2026)
Кнопки на странице:
- **Загрузить названия из Amazon** — вызывает `amazon-sync-names`, обновляет таблицу
- **Создать портфолио** — модал с полями Название / Аккаунт / Маркетплейс (маркетплейсы из `/portfolios/profiles`)
- **Сохранить в Amazon** (янтарная) — отправляет изменения названий через `amazon-update`
- **Сохранить локально** (зелёная) — только BigQuery через `bulk-update`

---

## Логика импорта каталога

CSV — экспорт из расширения Productor для Chrome.

### Порядок колонок в актуальном CSV (Productor, май 2026)
```
col[0]  asin
col[1]  brandName
col[2]  createdDate        (Unix timestamp)
col[3]  currencyCode
col[4]  deleteReasonType
col[5]  designId
col[6]  estimatedExpirationDate
col[7]  listPrice
col[8]  listingId
col[9]  lockReasonType
col[10] marketplace
col[11] productImageUrn
col[12] productTitle
col[13] productType
col[14] searchableOnRetail
col[15] status
col[16] updatedDate
col[17] pm_data            (JSON: буллиты, картинки, продажи, BSR...)
```

Парсер читает колонки по именам из заголовка — изменение порядка не сломает импорт.

### Скрипт выгрузки из Productor (IndexedDB → CSV)
Запускается в консоли браузера на странице Merch by Amazon при активном Productor:
```javascript
const dbName = "prettymerch_tmp";
const storeName = "products";
const fromDate = new Date("2026-05-10").getTime() / 1000;
const req = indexedDB.open(dbName);
req.onsuccess = function(e) {
  const db = e.target.result;
  db.transaction(storeName, "readonly").objectStore(storeName).getAll().onsuccess = function(e) {
    const data = e.target.result;
    const filtered = data.filter(row => row.createdDate >= fromDate);
    if (!filtered.length) { console.log("Нет товаров после указанной даты"); return; }
    const keys = [
      "asin", "brandName", "createdDate", "currencyCode", "deleteReasonType",
      "designId", "estimatedExpirationDate", "listPrice", "listingId",
      "lockReasonType", "marketplace", "productImageUrn", "productTitle",
      "productType", "searchableOnRetail", "status", "updatedDate", "pm_data"
    ];
    const csv = [
      keys.join(","),
      ...filtered.map(row => keys.map(k => JSON.stringify(row[k] ?? "")).join(","))
    ].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], {type: "text/csv"}));
    a.download = "prettymerch_products.csv";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    console.log(`Выгружено: ${filtered.length} из ${data.length}`);
  };
};
```
**Важно:** строки с пустым `asin` отбрасываются при импорте.

### MERGE процесс
1. DROP + CREATE catalog_staging
2. INSERT данные в staging чанками по 1000 строк
3. MERGE staging → catalog (по `listing_id`, поле `tags` не перезаписывается)
4. DROP catalog_staging

---

## Логика сбора рекламной статистики

### Через веб-интерфейс (ads.html)
1. `POST /ads/create_report` → создаёт отчёт в Amazon, пишет в reports_log.json
2. `POST /ads/refresh_statuses` → проверяет статусы PENDING отчётов
3. `POST /ads/download_report` → скачивает gzip с S3
4. `POST /ads/upload_to_bq` → DELETE старых данных + INSERT новых

### Через CLI (collect.py)
```bash
python3 collect.py 2026-05-31                         # Merch US за день
python3 collect.py 2026-05-01 2026-05-31 MERCH US     # период
python3 collect.py 2026-05-31 2026-05-31 KDP UK       # KDP UK
python3 collect.py 2026-05-31 all                     # все профили
```

### Ограничения API
- Один отчёт — максимум 31 день
- Amazon хранит данные 95 дней
- Attribution restatement: данные пересчитываются до 14 дней назад

### Загрузка данных в BigQuery (ads_routes.py, campaigns_routes.py)

Оба файла используют одинаковую схему загрузки чанками с параллельным батчингом:

```python
CHUNK      = 50_000      # строк в одном job
BATCH_SIZE = 5           # jobs параллельно, потом пауза
```

**Алгоритм:**
1. Данные режутся на чанки по 50k строк
2. Запускаются 5 jobs параллельно (без `job.result()`)
3. Потом ждём все 5 (`job.result()` в цикле)
4. Пауза 2 сек между батчами
5. Следующие 5 jobs

**Почему так:**
- Один большой job (867k строк) → OOM на PythonAnywhere (3 ГБ лимит)
- Полностью параллельный запуск всех jobs → `429 rateLimitExceeded` от BigQuery (`table.write` лимит)
- Батчи по 5 + пауза 2 сек — баланс между скоростью и rate limit

**Перед загрузкой всегда DELETE:**
- `ads_routes.py`: `DELETE WHERE date BETWEEN ... AND ... AND profile_id = '...'`
- `campaigns_routes.py`: `DELETE WHERE marketplace = '...'`

Дублей не возникает — чистим диапазон перед вставкой.

---

## Правила изменения ставок (планируется, analyze.py)

- Минимум 10 кликов за 14 дней для принятия решения
- ACOS > 40% и CVR < 1% → снизить ставку на 20%
- ACOS < 15% и CVR > 3% → повысить ставку на 15%
- Все изменения → `pending_changes` → одобрение → `send.py` → `change_log`

---

## Авторизация (app.py)

HTTP Basic Auth через `@app.before_request`. Логин/пароль задаются в `app.py`.

```python
# ── Auth ──────────────────────────────────────────────────
import base64
from flask import Response, request  # request обязателен!

AUTH_USERNAME = "Artem"
AUTH_PASSWORD = "..."

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
```

**Важно:** `request` должен быть импортирован явно. Без него Flask упадёт с Internal Server Error.

---

## Файлы которые есть в репо (не удалять)

| Файл | Описание |
|---|---|
| `collect.py` | CLI сбор статистики — используется регулярно |
| `fix_uk_fr.py` | Исправление профилей UK/FR |
| `get_merch_eu_profiles.py` | Получение EU профилей |
| `reports_log.json` | Лог отчётов — активный файл |
| `.gitignore` | Настройки git |

---

## Как обновить на GitHub

```bash
cd ~/amazon-ads

# Посмотреть что изменилось
git status

# Добавить все изменённые файлы
git add -A

# Или конкретные файлы
git add earnings_kdp.html kdp_earnings_routes.py app.py index.html project_context.md

# Коммит
git commit -m "Add KDP earnings import"

# Сохранение после сессии июнь 2026 (search terms checkboxes + batch add + context_name)
# git add products_analytics.html campaigns_analytics.html control_routes.py control.html project_context.md
# git commit -m "Search terms checkboxes batch neg, /control/add_batch, context_name column"
# git push origin master

# Пуш в master
git push origin master
```

После изменения Python файлов — перезагрузить на PythonAnywhere: **Web tab → Reload**.

### .gitignore (никогда не пушить)
```
config/
uploads/
*.pyc
__pycache__/
```

---

## Частые проблемы и решения

### JS: template literal с одинарными кавычками
Симптом: `Unexpected token ')` в строке с `font-family:'DM Mono'` или `.replace(/'/g,...)`
Решение: использовать `&quot;` внутри HTML атрибутов, `\x27` для кавычки в строке

### JS: `_jeS` для безопасного вставления строк в template literals
```js
const _jeS = (s) => String(s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;');
// Или использовать &quot; в onkeydown/onclick атрибутах HTML
```

### BigQuery: Aggregations of aggregations
Причина: `SUM()`, `ROUND(SUM())` поверх CTE с GROUP BY
Решение: убрать ROUND/COALESCE из агрегатов, считать CTR/ACOS в Python

### Amazon API: DUPLICATE_RESOURCE_ID_FOUND
Причина: несколько изменений одной кампании в одном батче
Решение: `send_update_campaigns` мёрджит все изменения кампании в один payload

### Amazon API: matchType для негативных ключей
Симптом: `NEGATIVE_PHRASE not found in enum`
Решение: `raw_mt.replace("NEGATIVE_", "")` + `"negative": True`

### Amazon API: AdGroup does not belong to Campaign
Причина: keyword_add получил adGroupId от группы из другой кампании при совпадении имён
Решение: составной ключ `(ag_name, camp_id)` + определение по `index` из API ответа

### Amazon API: FIELD_VALUE_NOT_UNIQUE при создании keywords
Причина: keyword с таким текстом + match_type уже существует в группе
Это нормально — дубли в Amazon не создаются

### Дата окончания на 1 день больше чем в консоли Amazon
Причина: отправка `T23:59:59Z` (UTC) для US → Amazon показывает следующий день
Решение: `T23:59:59-05:00` для US (с timezone offset)

### Scroll прыгает при раскрытии групп
Решение: `html { overflow-anchor: none }` + двойной `requestAnimationFrame`

### Портфолио dropdown — клик не работает
Причина: стрелка `.pda` вне `.pdt` перекрывает кнопку и не вызывает `onclick`
Решение: стрелка должна быть **внутри** `.pdt`

### targeting_type не определяется для + Группа в AUTO кампании
Причина: `/analytics/campaigns/structure` не возвращает `targeting_type` на уровне кампании
Решение: брать из строки таблицы и передавать через `state._expandedTgt` или аргумент `tgtTypeFallback`

### Страница импорта зависает на 0%
Причина: использование `EventSource` вместо polling через `setInterval`.
Решение: endpoint `/BLUEPRINT/progress/<job_id>` должен возвращать JSON-массив и очищать очередь. JS — `setInterval(fetch(...), 1500)`.

### JS ошибка "h is not defined" в buildStruct
Симптом: структура кампании не открывается, "Ошибка: h is not defined"
Причина: код `h +=` используется до объявления `let h = ''` в функции `buildStruct`
Решение: добавить `let h = '';` перед первым использованием `h +=`

### Amazon SP API v1 — ACTION_NOT_SUPPORTED: Ended campaign cannot be updated without endDate extension
Причина: нельзя менять state/budget завершённой кампании без одновременного продления даты
Решение: мёрдж state/budget + end_date в один payload решает проблему

### Amazon SP API v1 — FIELD_VALUE_IS_NULL: adProduct is missing
Причина: поле `adProduct` обязательно для всех create операций (targets, adGroups, ads)
Решение: добавить `"adProduct": "SPONSORED_PRODUCTS"` во все payload

### Amazon SP API v1 — BAD_REQUEST: missing required properties [adType, ...]
Симптом: при создании объявления (create/ads)
Причина: API требует `adType` и `creative.productCreative.productCreativeSettings.advertisedProduct`
Решение: использовать правильный формат с `adType: "PRODUCT_AD"` и вложенным `creative`

### Amazon SP API v1 — негативный product targeting (ASIN) — missing productIdType
Причина: `productIdType` нужен на уровне `productTarget`, а `productId` — внутри `product`
Решение: правильная структура — `productTarget.productIdType = "ASIN"` и `productTarget.product.productId = asin`

### Amazon SP API v1 — SUCCESS но изменение не применилось
Причина: старая версия `parse_multi_response` смотрела в `data.get("targets")` которого нет в SP API v1
SP API v1 возвращает `{"success": [...], "error": [...], "partialSuccess": [...]}` — не `{"targets": [...]}`
Решение: исправлен `parse_multi_response` — читает `success[]`, `error[]`, `partialSuccess[]`

### NameError: name 'c' is not defined в send.py
Причина: в `send_update_campaigns` используется `c.get("marketplace")` но цикл называет переменную `change`
Решение: везде использовать `change.get(...)` — переменная `mkt_code` уже определена из `change.get("marketplace")`

### Негативные ASIN таргеты показывают PRODUCT_EXACT вместо ASIN
Причина: ASIN хранится в `targetDetails.productTarget.product.productId`, не в `productTarget.productId`
Решение: исправлено в `campaigns_routes.py`, нужна повторная синхронизация кампаний

### SQL алиас конфликт в products_routes.py
Причина: алиас `c` для `campaigns` конфликтовал с `c` для `catalog` в одном запросе
Решение: CTE использует алиас `camp` — `FROM campaigns camp WHERE camp.entity_type = 'campaign'`

### Поисковые запросы пустые в мануальных кампаниях на Products странице
Причина: `search_terms` для мануальных кампаний хранятся в `keyword['search_terms']`, не в `group['search_terms']`
Решение: в JS собирать из `g.search_terms + g.keywords[].search_terms + g.targets[].search_terms`

### context_name пустой для авто-таргетов и ключей на control.html
Причина: `ad_group_name` = NULL на строках `product_targeting`/`keyword` в campaigns таблице
Решение: JOIN с entity_type='ad_group' через `ad_group_id`:
```sql
SELECT DISTINCT t.target_id AS eid, ag.ad_group_name AS name
FROM campaigns_merch t
JOIN campaigns_merch ag ON ag.ad_group_id = t.ad_group_id
  AND ag.entity_type = 'ad_group' AND ag.marketplace = t.marketplace
WHERE t.target_id IN (...) AND t.entity_type='product_targeting'
```

---

## На горизонте

- **analyze.py** — автоматический bid optimization loop
- **Search Term Harvesting** — таблица `keyword_queue`, автоматическое добавление ключей
- **Looker Studio** — дашборды
- **BigQuery Client singleton** (`bq_client.py`) — `bigquery.Client()` создаётся один раз при старте, все route файлы используют `get_client()`. Ускоряет каждый запрос на ~200-500ms (нет повторной инициализации credentials). Реализация:
```python
# bq_client.py
from google.cloud import bigquery
_client = None
def get_client():
    global _client
    if _client is None:
        _client = bigquery.Client(project='amazon-ads-api-494412')
    return _client
```
Затем: `sed -i 's/bigquery\.Client(project=PROJECT_ID)/get_client()/g' ~/amazon-ads/*_routes.py`