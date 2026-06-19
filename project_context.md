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
| `targets_routes.py` | `targets_bp` | `/targets` — анализ таргетов (ключевые слова, авто/мануал) |
| `control_routes.py` | `control_bp` | `/control` — управление рекламой через pending_changes |
| `sales_comparison_routes.py` | `sales_comparison_bp` | `/sales-comparison` — сравнение продаж MBA/KDP с рекламой |
| `asin_merge_routes.py` | `asin_merge_bp` | `/asin-merge` — слияние ASIN дубликатов в каталоге |

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
| `earnings_kdp.html` | `/earnings-kdp` | Импорт продаж KDP (Excel, вкладки Paperback/Hardcover/eBook Royalty) |
| `sales_comparison.html` | `/sales-comparison` | Сравнение продаж MBA/KDP с рекламой по дизайнам |
| `asin_merge.html` | `/asin-merge` | Слияние ASIN-дубликатов в каталоге по design_id |
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
├── catalog_routes.py          → catalog_bp
├── earnings_routes.py         → earnings_bp
├── kdp_earnings_routes.py     → kdp_earnings_bp
├── ads_routes.py              → ads_bp
├── campaigns_routes.py        → campaigns_bp
├── portfolios.py              → portfolios_bp
├── analytics_routes.py        → analytics_bp
├── products_routes.py         → products_bp
├── targets_routes.py          → targets_bp
├── search_terms_routes.py     → search_terms_bp
├── sales_comparison_routes.py → sales_comparison_bp
├── asin_merge_routes.py       → asin_merge_bp
└── control_routes.py          → control_bp
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
Читаются три отдельные вкладки: **Paperback Royalty**, **Hardcover Royalty**, **eBook Royalty**.
⚠️ Вкладка **Combined Sales** НЕ используется — там нет колонки ASIN для paperback/hardcover (только ISBN-13).

### Структура вкладок
```python
SHEETS = [
    {"name": "Paperback Royalty",  "has_isbn": True,  "has_order_date": True},
    {"name": "Hardcover Royalty",  "has_isbn": True,  "has_order_date": True},
    {"name": "eBook Royalty",      "has_isbn": False, "has_order_date": False},
]
```
- Все три вкладки имеют колонку **ASIN**
- Paperback/Hardcover также имеют **ISBN** (ISBN-13) и **Order Date**
- eBook имеет только **Royalty Date**

### Endpoints

| Метод | URL | Описание |
|---|---|---|
| `POST` | `/kdp-earnings/upload` | Принимает `.xlsx`, запускает импорт в фоне, возвращает `{job_id}` |
| `GET` | `/kdp-earnings/progress/<job_id>` | Polling: возвращает JSON-массив событий и очищает очередь |
| `GET` | `/kdp-earnings/count` | Количество строк в таблице `earnings_kdp` |

### Шаги импорта
1. Читаем три вкладки Excel (`pandas`, `dtype=str`)
2. `parse_row(row, sheet_meta)` — извлекает ASIN из колонки `ASIN`, ISBN из `ISBN` (только pb/hc)
3. Дедупликация внутри файла по MD5-хэшу: `(royalty_date, asin, isbn, marketplace, transaction_type, units_sold, units_refunded, royalty, currency)`
4. `ensure_table_schema()` — добавляет новые колонки если таблица уже существует
5. Проверяем существующие хэши в BigQuery (батчи по 10 000)
6. Загружаем только новые строки (`WRITE_APPEND`, `ALLOW_FIELD_ADDITION`, чанки по 1000)

**Важно:** `schema=BQ_SCHEMA` НЕ передаётся в `LoadJobConfig` — иначе BigQuery конфликтует с REQUIRED/NULLABLE для уже существующих колонок. Используется только `schema_update_options=[ALLOW_FIELD_ADDITION]`.

### Дата в базе
Записывается `royalty_date` — дата начисления роялти. `order_date` (когда был сделан заказ) тоже хранится для pb/hc.

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

## Targets Page (targets_routes.py + targets.html)

### Назначение
Страница `/targets` — анализ и управление таргетами (ключевые слова, авто/мануал) на уровне групп объявлений. Два режима: **Группы** (агрегированная статистика по группам) и **Таргеты** (плоский список всех таргетов).

### Blueprint
```python
targets_bp = Blueprint('targets', __name__)
# Зарегистрирован в app.py: app.register_blueprint(targets_bp)
# HTML: GET /targets → targets.html
```

### GET /targets/data
Основной endpoint таблицы. Параметр `mode` переключает между режимами.

**Общие параметры:** `account_type` (MERCH/KDP), `mode` (groups/targets), `date_from`, `date_to`, `marketplace`, `portfolio_ids` (через запятую), `name`, `state` (ad_group_state), `camp_state` (campaign_state), `sort_by`, `sort_dir`, `page`, `per_page`

**Числовые фильтры:** `impressions_op/val/min/max`, `clicks_*`, `cost_*`, `ctr_*`, `sales_14d_*`, `purchases_14d_*`, `acos_*`

**Режим `mode=groups`:**
- Дополнительные параметры: `ttype` (targeting_type: keyword/auto/product), `group_state` (ALL/ACTIVE/PAUSED)
- SQL: агрегирует `targets_stats_{suffix}` с JOIN `campaigns_{suffix}` по ad_group_id, фильтр по targeting_type группы
- Возвращает поля: `ad_group_id`, `ad_group_name`, `campaign_name`, `portfolio_name`, `marketplace`, `ad_group_state`, `campaign_state`, `ad_group_default_bid`, `targeting_type`, `impressions`, `clicks`, `cost`, `sales_14d`, `purchases_14d`, `ctr`, `acos`

**Режим `mode=targets`:**
- Дополнительные параметры: `ttype` (тип таргета), `group_state` (статус группы для фильтрации)
- SQL: `targets_stats_{suffix}` LEFT JOIN `campaigns_{suffix}` (для ad_group_state)
- Возвращает поля: `keyword_id`, `kw_text`, `keyword_type`, `match_type`, `bid`, `target_state`, `ad_group_name`, `campaign_name`, `ad_group_state`, `ad_group_default_bid`, `impressions`, `clicks`, `cost`, `sales_14d`, `purchases_14d`, `ctr`, `acos`

**Важно:** В режиме таргетов `ad_group_default_bid` берётся из поля `g.ad_group_default_bid` в CTE `g` (через ROW_NUMBER OVER PARTITION BY ad_group_id из campaigns), объединённого с stats LEFT JOIN. Это позволяет показывать ставку группы в качестве fallback когда ставка таргета не задана.

### GET /targets/group
Детальная информация о группе: структура + статистика. Реализован по **паттерну products**: два отдельных BigQuery запроса (struct + stats), join в Python.

**Параметры:** `group_id`, `campaign_id`, `marketplace`, `account_type`, `date_from`, `date_to`

**4 параллельных запроса:**
1. `sql_group_info` — дефолтная ставка и campaign_id группы из campaigns_{suffix}
2. `sql_struct` — ВСЕ сущности группы (keyword, product_targeting, negative_keyword, negative_product_targeting) из campaigns_{suffix}, дедупликация через ROW_NUMBER OVER PARTITION BY entity_id ORDER BY synced_at DESC
3. `sql_stats` — агрегированная статистика по keyword_id из targets_stats_{suffix} с `ANY_VALUE(keyword_type)`
4. `sql_search_terms` — поисковые запросы из search_terms_{suffix}

**SQL struct (ключевой паттерн):**
```sql
SELECT entity_type, keyword_id, keyword_text, match_type, keyword_bid, keyword_state,
       target_id, targeting_expression, target_bid, target_state
FROM (
    SELECT ...,
           ROW_NUMBER() OVER (
               PARTITION BY CASE WHEN entity_type IN ('keyword','negative_keyword')
                            THEN keyword_id ELSE target_id END
               ORDER BY synced_at DESC
           ) rn
    FROM `{camp_table}`
    WHERE entity_type IN ('keyword','product_targeting','negative_keyword','negative_product_targeting')
      AND ad_group_id = '{safe_gid}' {mkt_cond}
) WHERE rn = 1
```

**Python join:**
```python
stats_by_id = {r['keyword_id']: r for r in stats_rows}
for row in struct_rows:
    eid = row.get('keyword_id') or row.get('target_id')
    st = stats_by_id.get(eid, {})
    # keyword_type: из stats или fallback
    ktype = st.get('keyword_type') or (row['match_type'].upper() if row['match_type'] else 'TARGETING_EXPRESSION')
    # ... сборка targets[] и negatives[]
```

**Возвращает:**
```json
{
  "group_bid": 0.5,
  "campaign_id": "...",
  "targets": [{"id":"...","text":"...","type":"BROAD","bid":null,"state":"ENABLED","stats":{...}}],
  "negatives": [{"id":"...","text":"...","type":"EXACT","neg_type":"keyword|product"}],
  "search_terms": [{"search_term":"...","keyword_id":"...","keyword":"...","impressions":...}]
}
```

**Почему struct из campaigns, а не из stats:** паузированные таргеты не имеют статистики → если начинать с stats, они не появятся. Паттерн "struct → LEFT JOIN stats" гарантирует отображение всех таргетов независимо от состояния.

**keyword_type из campaigns:** поле `keyword_type` существует в `targets_stats_{suffix}`, но НЕ в `campaigns_{suffix}`. Для получения используется `ANY_VALUE(keyword_type)` в stats-запросе, для новых таргетов — fallback `UPPER(match_type)` или `'TARGETING_EXPRESSION'`.

### targets.html — Состояние (S)
```js
S = {
  acct, mode, ttype, groupTgtType, groupState, tgtGroupState,
  df, dt, mkt, portfolios, pfs, name, state, campState,
  sort, dir, page, perPage, total, numFilters,
  openGroupId, openGroupMkt
}
```

### targets.html — Режимы и фильтры
- **Режим Группы**: фильтры тип AUTO/MANUAL + статус ALL/ACTIVE/PAUSED
- **Режим Таргеты**: фильтры тип таргета + статус группы
- Портфолио dropdown (как в products): фильтрует по account_type + geo

### targets.html — renderGroups()
Таблица групп. Колонки: Группа / Кампания / Маркетплейс / Ставка / Показы / Клики / Расходы / Продажи / Заказы / ACOS.
- Inline редактирование ставки группы (`openBidEdit` / `saveBid`)
- Разворачивание группы по клику на шевроне → `loadGroupDetail(groupId, mkt)`

### targets.html — renderTargets()
Таблица таргетов с колонкой toggle слева.
- Toggle `.stog` для включения/паузы каждого таргета
- Fallback bid: если `target.bid` null → показывается `ad_group_default_bid` серым курсивом с `(г)`
- Бейдж статуса группы под именем группы (`.bp` amber для PAUSED)
- Inline редактирование ставки

### targets.html — renderGroupDetail()
Products-style layout с вкладками `.tabs`/`.tab`/`.tp`:
- Вкладка **Таргеты** — `renderGroupTargets()`
- Вкладка **Поисковые запросы** — `renderGroupSearchTerms()`
- Вкладка **Минус слова** — `renderGroupNegatives()`

### targets.html — renderGroupTargets()
Grid `.ih`/`.ii` (как в products):
```
24px 1fr 60px 80px 80px 70px 65px 88px 85px 72px
Toggle · Текст · Тип · Ставка · Показы · Клики · Заказы · Расходы · Продажи · ACOS
```
- `.stog` toggle (`.en`/`.pa`) с `toggleState()` → `.pend` amber после успешного запроса
- Ставка с fallback на ставку группы (серый курсив + `(г)`)
- Inline редактирование ставки → `ctrlAdd` с entity_type `keyword` или `target`

### targets.html — renderGroupSearchTerms()
Grid `.ih.st`/`.ii.st` с чекбоксами.
- Кнопка **«→ Минус (N)»** при выборе строк
- `openNegFromSt(groupId, campId, mkt)` — разделяет ASINы и слова, открывает modalNeg
- `isAsin(str)` — `/^[Bb][0-9A-Za-z]{9}$/`

### targets.html — renderGroupNegatives()
Grid `.in2` с бейджами типа KW/PRODUCT:
- Негативные ключи (negative_keyword) → тип "KW" + match type
- Негативные продукты (negative_product_targeting) → тип "PRODUCT" + ASIN из targeting_expression

### targets.html — modalNeg
Радиокнопки Слово/Продукт ASIN. ID полей: `mnegGroupId`, `mnegCampId`, `mnegMkt`.
- `onNegTypeChange(radio)` — скрывает/показывает строку Match Type
- `submitAddNeg()`:
  - Слово → `entity_type: 'negative_add'`
  - ASIN → `entity_type: 'negative_product_add'` (каждый ASIN отдельной записью)
  - Batch отправка через `ctrlAddBatch(payloads)`

### targets.html — toggleState()
```js
async function toggleState(e, entityType, entityId, currentState, mkt) {
  // ставит .pend (amber) сразу на кнопку
  // отправляет ctrlAdd с новым state (ENABLED↔PAUSED)
  // при успехе: .pend остаётся до следующей загрузки данных
}
```

### Особенности паттерна targets vs products
| Аспект | products | targets |
|---|---|---|
| Основная таблица stats | `asin_stats_{suffix}` | `targets_stats_{suffix}` |
| Структура | `campaigns_{suffix}` | `campaigns_{suffix}` |
| keyword_type | есть в stats | `ANY_VALUE(keyword_type)` из stats |
| Негативные продукты | `negative_product_targeting` | `negative_product_targeting` |
| Toggle entity_type | `keyword` или `target` | `keyword` или `target` |

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
row_hash            -- MD5 ключ дедупликации
royalty_date        -- DATE, дата начисления роялти
order_date          -- DATE, дата заказа (только pb/hc, NULL для eBook)
asin                -- STRING, реальный ASIN (из вкладок pb/hc/eBook)
asin_isbn           -- STRING, ISBN-13 (только pb/hc, NULL для eBook)
title               -- название книги
author              -- имя автора
marketplace         -- Amazon.com / Amazon.co.uk / etc.
royalty_type        -- 60% / 50%
transaction_type    -- Standard - Paperback / Hardcover / eBook
units_sold          -- INT64
units_refunded      -- INT64
net_units_sold      -- INT64
list_price          -- средняя цена листинга без налогов
offer_price         -- средняя цена предложения без налогов
manufacturing_cost  -- средняя стоимость производства/доставки
royalty             -- роялти в валюте
currency            -- USD / GBP / EUR / AUD / CAD / JPY / ...
imported_at         -- TIMESTAMP

-- Ключевые вычисления в SQL:
-- total_revenue = SUM(offer_price * net_units_sold)   -- gross revenue
-- royalties     = SUM(royalty)                         -- роялти после вычета доли Amazon

-- Маркетплейс хранится как Amazon.com / Amazon.co.uk / Amazon.de (полный домен)
-- KDP_DOMAIN_MAP в sales_comparison_routes.py: 'US' → 'Amazon.com', 'UK' → 'Amazon.co.uk' ...
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

## Sales Comparison (sales_comparison_routes.py + sales_comparison.html)

### Назначение
Сравнение органических продаж (earnings MBA / earnings_kdp KDP) с рекламными данными (asin_stats).
Группировка по **design_id + product_type + marketplace** — объединяет один дизайн под разными ASIN.

### Маршруты
| Метод | URL | Описание |
|---|---|---|
| `GET` | `/sales-comparison` | HTML страница |
| `GET` | `/sales-comparison/data` | Основная таблица с пагинацией |
| `GET` | `/sales-comparison/weekly` | График тренда (неделя или месяц) |
| `GET` | `/sales-comparison/portfolios` | Список портфолио |
| `GET` | `/sales-comparison/product-types` | Уникальные типы товаров |

### account_type
- `MERCH` — таблица `earnings`, маркетплейс `.com` / `.co.uk` / `.de` ...
- `KDP` — таблица `earnings_kdp`, маркетплейс `Amazon.com` / `Amazon.co.uk` ...

Маппинг marketplace (`sales_comparison_routes.py`):
```python
MKT_DOMAIN_MAP = {'US': '.com', 'DE': '.de', 'UK': '.co.uk', ...}     # для MERCH
KDP_DOMAIN_MAP = {'US': 'Amazon.com', 'UK': 'Amazon.co.uk', ...}       # для KDP
```

### Группировка MERCH по design_id
```sql
earn_keyed AS (
  SELECT COALESCE(c.design_id, e.asin) AS grp_key,   -- design_id или сам ASIN если не в каталоге
         COALESCE(c.product_type_norm, e.earn_pt) AS pt_key,
         e.asin AS earn_asin   -- реальный ASIN для primary_asin fallback
  FROM earn_raw e LEFT JOIN cat1 c ON c.asin = e.asin ...
),
organic AS (
  SELECT grp_key, pt_key, ..., MIN(earn_asin) AS primary_asin
  FROM earn_keyed GROUP BY grp_key, pt_key, marketplace
),
ads AS (
  SELECT grp_key, ..., MIN(advertised_asin) AS primary_asin
  FROM ads_keyed GROUP BY grp_key, pt_key, marketplace
),
base AS (
  COALESCE(a.primary_asin, o.primary_asin, o.grp_key) AS primary_asin
  -- primary_asin — реальный ASIN для отображения в таблице
  -- grp_key используется только как fallback если нет ни ads ни earnings
)
```

### Таблица продаж (колонки)
`asin` (grp_key) | `title` | `product_type` | `royalties` | `total_revenue` | `ad_sales` | `ad_spend` | `tacos` | `acos` | `ad_share_pct`

**TACoS** = `ad_spend / total_revenue` (не `ad_spend / royalties`)

**primary_asin** — реальный ASIN для отображения в колонке ASIN и для detail-запросов.
Если у товара нет рекламы и нет earnings → в колонке будет design_id (UUID).

### График тренда (weekly endpoint)
Параметр `period`:
- `week` (по умолчанию) → `DATE_TRUNC(date, WEEK(MONDAY))`
- `month` → `DATE_TRUNC(date, MONTH)`

### product_type фильтр
Multi-select dropdown. Передаётся как `product_types=TYPE1,TYPE2,...`.
SQL: `UPPER(COALESCE(product_type,'')) LIKE UPPER('%TYPE%')` в `filtered` CTE.

### Поиск (name фильтр)
```sql
AND (LOWER(COALESCE(title, '')) LIKE LOWER('%term%')
  OR LOWER(COALESCE(primary_asin, asin, '')) LIKE LOWER('%term%'))
```
Применяется в `filtered` CTE где колонки однозначны (не в `base`).

---

## ASIN Merge (asin_merge_routes.py + asin_merge.html)

### Назначение
Страница `/asin-merge` для ручного добавления ASIN-дубликатов в каталог.
Используется когда один дизайн продаётся под разными ASIN (переиздание, разные SKU), но только один
из них есть в каталоге. Добавление нового ASIN с тем же `design_id` позволяет группировать продажи.

### Endpoints
| Метод | URL | Описание |
|---|---|---|
| `GET` | `/asin-merge` | HTML страница |
| `GET` | `/asin-merge/lookup?asin=X` | Найти ASIN в каталоге |
| `POST` | `/asin-merge/add` | Скопировать строку каталога с новым ASIN |
| `GET` | `/asin-merge/list` | Все группы design_id с несколькими ASIN |

### Логика добавления
1. Lookup source ASIN → получить всю строку из `catalog`
2. Проверить что new ASIN ещё не в каталоге
3. Скопировать строку с `asin = new_asin` (все остальные поля одинаковые: design_id, title, image_url и т.д.)
4. INSERT через `bq_literal()` — экранирование через `\'` (не `''`), datetime через `TIMESTAMP 'value'`

### Зачем нужна страница
BigQuery не поддерживает ON CONFLICT, поэтому не получится автоматически слить ASINы.
Страница позволяет вручную добавить «зеркальный» ASIN, после чего sales_comparison
объединит их по design_id при следующей загрузке.

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

### KDP earnings: $0 роялти в sales-comparison
Причина: `earnings_kdp.marketplace = 'Amazon.com'` (полный домен), а код использовал `.com` (суффикс)
Решение: `KDP_DOMAIN_MAP` в `sales_comparison_routes.py` — отдельный маппинг для KDP

### KDP earnings: ASIN не определялся (asin_isbn содержит ISBN-13, не ASIN)
Причина: вкладка `Combined Sales` хранит ISBN-13 в поле asin_isbn для pb/hc
Решение: читать из отдельных вкладок `Paperback Royalty`, `Hardcover Royalty`, `eBook Royalty` — там есть колонка ASIN

### KDP earnings: дубли после переимпорта
Причина: старый хэш использовал `asin_isbn`, новый — `asin`. Разные хэши → 311 «новых» строк при повторном импорте
Решение: удалить старые данные через `DELETE WHERE asin IS NULL` перед переимпортом

### KDP total_revenue = royalties (неверный расчёт)
Причина: SQL использовал `SUM(e.royalty)` как total_revenue
Решение: `total_revenue = SUM(e.offer_price * e.net_units_sold)` — gross revenue = цена × кол-во

### sales-comparison: ASIN колонка показывает design_id (UUID)
Причина: когда у товара нет рекламных данных, `primary_asin = COALESCE(a.primary_asin, o.grp_key)` подставляет grp_key (design_id)
Решение: передавать `earn_asin` через organic CTE: `MIN(earn_asin) AS primary_asin`, затем `COALESCE(a.primary_asin, o.primary_asin, o.grp_key)`

### BigQuery INSERT: SyntaxError "concatenated string literals"
Причина: BigQuery не поддерживает `''` для экранирования апострофа в строках
Решение: использовать `\'` в `bq_literal()` — `s.replace("'", "\\'")`

### BigQuery schema conflict "Field has changed mode from REQUIRED to NULLABLE"
Причина: `schema=BQ_SCHEMA` в `LoadJobConfig` конфликтует с уже существующей схемой таблицы
Решение: убрать `schema=BQ_SCHEMA` из LoadJobConfig, оставить только `ALLOW_FIELD_ADDITION`

### BigQuery: "Name asin not found inside o" / "Column name title is ambiguous"
Причина: `name_cond` и `pt_cond` применялись в `base` CTE, где колонки из разных JOIN имеют одинаковые имена
Решение: перенести `name_cond` и `pt_cond` в `filtered` CTE (после base), где только unambiguous колонки

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

---

## Campaign Builder (campaign_builder.html + campaign_builder_routes.py) — июнь 2026

### Назначение
Google-Sheets-подобный интерфейс для массового создания AUTO/MANUAL Sponsored Products кампаний
через тот же pending_changes → /control → send.py воркфлоу. Заменяет старый Google Apps Script
bulk-генератор.

### Модель данных (1 строка = 1 группа)
Таблица — плоский список строк, каждая строка = группа объявлений (ad group).
Первая строка кампании несёт ОБА набора полей: campaign-level (Campaign Name, Type, Bid Strategy,
Budget, Top%, Portfolio, Start/End, Campaign Negative) И group-level (ASIN, Group Name/theme,
Match Type, Keywords, Bid, Group Negative). Последующие строки группы той же кампании несут
только group-level поля, campaign-level поля визуально скрыты (класс `cell-dim`,
показываются при фокусе на случай редактирования).

`isCampaign(row)` определяется просто: `!!(row.campName||'').trim()`.

### Авто-вычисляемые имена
- **Campaign Name** = `BASENAME_TYPE` (например `CLASSIC_AWESOME_LIKE_DAUGHTER_TEXT_MANUAL`),
  верхний регистр, пробелы → `_`. Пользователь вводит только базовое имя в "Campaign Name (base)".
- **Group Name**:
  - MANUAL: `ASIN_THEME_MATCHTYPE` (например `B0H2B7N82S_BONUS_DAD_BROAD`)
  - AUTO: `ASIN_THEME_AUTO` (например `B0H2B7N82S_BONUS_DAD_AUTO`), Match Type не используется
- Для AUTO кампаний Match Type и Keywords визуально скрыты/неактивны и не валидируются,
  `buildTree()` принудительно обнуляет `keywords: []` для `type==='auto'`.

### UI: 15 колонок
Campaign Name (base) | Type | Bid Strategy | Match Type | ASIN | Group Name (theme) | Keywords |
Budget $ | Bid $ | Top % | Portfolio | Start Date | End Date | Group Negative | Campaign Negative

Bid Strategy — select с тремя опциями: "Dynamic bids - down only" / "Dynamic bids - up and down" /
"Fixed bid" — независимая ось от Type (auto/manual targeting).

### Excel/Sheets-подобное поведение
- **Колонки**: `<colgroup>` + `table-layout:fixed`, drag-resize через `.col-resizer` на правом крае `<th>`
- **Range-selection**: mousedown+mouseenter по `td` (без preventDefault — не блокирует нативный
  фокус инпута). При реальном drag (range > 1 cell) активный input блюрится, чтобы Ctrl+C/Delete
  работали по диапазону, а не по тексту в инпуте. Одиночная ячейка — нативное поведение.
- **Ctrl+C** на диапазоне → TSV в буфер (multiline ячейки оборачиваются в `"..."` с `""`-escaping)
- **Delete/Backspace** на диапазоне → очищает все ячейки (selects → дефолты: mt→broad,
  type→Manual, bidStrategy→Dynamic bids - down only)
- **Paste**: если в буфере нет `\t` → весь текст идёт в одну ячейку (включая многострочные
  Keywords/Negative), с снятием обрамляющих кавычек `"..."` → `...` и `""`→`"`. Если есть `\t` →
  TSV распределяется по ячейкам/строкам, новые строки добавляются автоматически. Paste в `<select>`
  (Portfolio/Type/etc.) теперь поддерживается — ID/значение подставляется и option выбирается.
- **Удаление кампании**: клик по `#` на первой строке кампании удаляет её и все её группы (с
  confirm если групп >1). Клик на group-only строке удаляет только её.
- **+ Кампания (+группа)** — добавляет 1 строку с дефолтами (budget=30, top=30, start=сегодня)
- **+ Группа** — добавляет пустую group-only строку после выделенной/сфокусированной строки

### Импорт черновика из Google Sheets
Блок "Черновик из Google Sheets" (toggle "Показать"):
- **Вариант 1**: вставка ссылки на Sheets (`/export?format=csv&gid=...`), требует доступ
  "Любой пользователь по ссылке — Просмотр". CORS может блокировать — fallback на вариант 2.
- **Вариант 2**: textarea, вставка TSV-диапазона (Ctrl+V из Sheets/Excel)
- **Маппинг колонок по заголовкам** (`HEADER_ALIASES` dict) — порядок колонок в исходной
  таблице не важен, если есть строка заголовков (чекбокс "первая строка — заголовки").
  Поддерживает варианты названий: "Type of Campaign"/"Campaign Type"→type, "Bid for Group"→bid,
  "Groupe Minus"/"Group Minus"→grpNeg, "Placement Top"→top, и т.д.
- После загрузки сразу запускается `validate()`, проблемные ячейки подсвечиваются красным
  (`cellErrors` Set с ключами `'ri:colKey'`), статус показывает количество ошибок.
- Нормализация при импорте: mt→lowercase (невалидное→broad), type→Auto если `auto`
  (любой регистр) иначе Manual, bidStrategy→дефолт если не входит в список 3 валидных значений
  (КРИТИЧНО: нельзя делать `v = v || default`, т.к. непустая невалидная строка типа `"auto"`
  тогда "проходит" — нужно безусловное `v = default` если не в списке).
- Даты: `-` удаляется (`YYYY-MM-DD` → `YYYYMMDD`)

### Backend: campaign_builder_routes.py
- `GET /campaign-builder` → отдаёт HTML
- `POST /campaign-builder/queue` → валидирует, нормализует (`_norm_date`,
  `clean_groups` с проверкой matchType), вставляет 1 строку на кампанию в
  `pending_changes_merch/kdp` с `entity_type='campaign_create'`, `new_value` = JSON:
```json
{
  "type": "auto|manual",
  "name": "FULL_CAMPAIGN_NAME",
  "bidStrategy": "Dynamic bids - down only",
  "budget": 30.0, "bidadj": 30,
  "portfolio": "39709167542056",
  "start": "2026-06-11", "end": "2026-06-20",
  "compneg": ["free"],
  "groups": [{
    "name": "ASIN_THEME_BROAD", "theme": "Bonus Dad", "asin": "B0H2B7N82S",
    "bid": 0.6, "matchType": "broad",
    "keywords": ["best dad ever shirt", "..."],
    "negatives": ["custom"]
  }]
}
```

---

## send.py: send_create_campaigns() — ВЫВЕРЕННЫЕ форматы (июнь 2026, протестировано live)

Полный пайплайн: campaigns → adGroups → ads → targets (keywords), всё через
`/adsApi/v1/create/*`, обрабатывает `campaign_create` записи из pending_changes.

### 1. POST /adsApi/v1/create/campaigns
```python
strategy_map = {
    "Dynamic bids - down only":   "SALES_DOWN_ONLY",
    "Dynamic bids - up and down": "SALES_UP_AND_DOWN",
    "Fixed bid":                  "MANUAL",
}
payload = {
    "adProduct": "SPONSORED_PRODUCTS",
    "name": c["name"],
    "state": "ENABLED",
    "marketplaceScope": "SINGLE_MARKETPLACE",   # строка, НЕ объект!
    "marketplaces": [mkt],                      # отдельное поле, массив
    "optimizations": {"bidSettings": {"bidStrategy": strategy}},
    "budgets": [{
        "budgetType": "MONETARY",
        "recurrenceTimePeriod": "DAILY",
        "budgetValue": {"monetaryBudgetValue": {
            "monetaryBudget": {"value": budget},
            "marketplaceSettings": [{"marketplace": mkt, "monetaryBudget": {"value": budget}}]
        }}
    }],
    "autoCreationSettings": {"autoCreateTargets": (c["type"] == "auto")},  # ВСЕГДА присутствует,
                                                                            # даже для MANUAL (false)
}
if start: payload["startDateTime"] = f"{start}T00:00:00Z"
if end:   payload["endDateTime"]   = f"{end}T23:59:59{sign}{offset:02d}:00"
if c.get("portfolio"): payload["portfolioId"] = c["portfolio"]

# placementBidAdjustments — ВСТРОЕН в campaign payload, отдельного endpoint НЕ существует
# (POST /create/campaigns/bidAdjustments возвращает 403)
if bidadj > 0:
    payload["optimizations"]["bidSettings"]["bidAdjustments"] = {
        "placementBidAdjustments": [{"placement": "TOP_OF_SEARCH", "percentage": bidadj}]
    }
```

**Парсинг ответа**: `campaignId` вложен в `item["campaign"]["campaignId"]`, НЕ на верхнем
уровне `item["campaignId"]`. Если `index` отсутствует (`-1`) и в батче только 1 кампания —
fallback на `index=0` (Amazon иногда не возвращает index для одиночных батчей).
```python
cid = item.get("campaignId") or (item.get("campaign") or {}).get("campaignId")
```

### 2. POST /adsApi/v1/create/adGroups
```python
{
    "adProduct": "SPONSORED_PRODUCTS",
    "campaignId": cid,
    "name": g["name"],
    "state": "ENABLED",
    "bid": {"defaultBid": float(g["bid"])},   # ПЛОСКОЕ число, БЕЗ currencyCode,
                                               # БЕЗ вложенности {"bid":..,"currencyCode":..}
}
```
`adGroupId` в ответе: `item["adGroup"]["adGroupId"]` (с тем же fallback на `campaignId`-стиль
вложенности что и у campaigns).

### 3. POST /adsApi/v1/create/ads
```python
{
    "adProduct": "SPONSORED_PRODUCTS",
    "adType": "PRODUCT_AD",
    "adGroupId": ag_id,        # campaignId здесь НЕ допускается схемой — убрать!
    "state": "ENABLED",
    "creative": {"productCreative": {"productCreativeSettings": {
        "advertisedProduct": {
            "productId": g["asin"],      # НЕ "asin" — обязательно "productId"
            "productIdType": "ASIN",     # обязательное поле
        }
    }}}
}
```

### 4. POST /adsApi/v1/create/targets (keywords, только MANUAL)
Frontend теперь шлёт `keywords` как **массив строк** `["text1","text2"]`, не массив объектов.
Match type и bid берутся с уровня группы (`g["matchType"]`, `g["bid"]`):
```python
for kw in g.get("keywords", []):
    kw_text = str(kw).strip()
    if not kw_text: continue
    payload = {
        "adGroupId": ag_id,             # campaignId НЕ нужен
        "adProduct": "SPONSORED_PRODUCTS", "negative": False, "state": "ENABLED",
        "targetType": "KEYWORD",
        "targetDetails": {"keywordTarget": {
            "matchType": g["matchType"].upper(), "keyword": kw_text
        }},
        "bid": {"bid": float(g["bid"]), "currencyCode": currency},
    }
```

### Общий паттерн ошибок "Start of structure or map found where not expected"
Эта ошибка Amazon = JSON-структура корня/поля имеет неправильный ТИП (объект вместо строки,
или наоборот), не связана с отсутствующими полями. Встречалась трижды:
1. `marketplaceScope` как объект `{...}` вместо строки `"SINGLE_MARKETPLACE"`
2. `bidStrategy` enum значения: правильные — `SALES_DOWN_ONLY`/`SALES_UP_AND_DOWN`/`MANUAL`
   (НЕ `LEGACY_FOR_SALES`/`AUTO_FOR_SALES` — это были придуманные значения)
3. adGroup `bid` как `{"defaultBid": {...}}` (двойная вложенность) вместо `{"defaultBid": <float>}`

### Live-проверенный результат (11.06.2026)
4 кампании (2 AUTO + 2 MANUAL) → 5 ad groups → 5 product ads → 14 keywords,
все шаги `✓ Готово: 4 успешно, 0 с ошибками`, включая placementBidAdjustments inline.

---

## Страница "Удаление кампаний" (/campaigns-deleting) — июнь 2026

### Назначение
Массовый просмотр, архивация и удаление кампаний из Amazon Ads. Создана для очистки
большого числа тестовых кампаний (созданных через Campaign Builder).

### Фронтенд: campaigns_deleting.html
- Та же модель фильтров/статистики, что в campaigns_analytics.html (без drill-down):
  аккаунт MERCH/KDP, даты, маркетплейс, портфолио, таргетинг, статус (включая ARCHIVED),
  активность, поиск по названию.
- Таблица кампаний с чекбоксами слева, sortable-колонки.
- При выборе строк появляется панель действий:
  - **📦 Архивировать выбранные** — campaign.state → ARCHIVED через update/campaigns
  - **🗑️ Удалить выбранные** — полное удаление через delete/campaigns
- Confirm-модалка адаптируется под выбранное действие, показывает количество и предупреждение
  о необратимости.
- Уже-`ARCHIVED` кампании пропускаются при архивации (Amazon не позволяет повторный переход).
- Маршрут зарегистрирован в `analytics_routes.py`: `GET /campaigns-deleting` →
  `send_from_directory(BASE_DIR, 'campaigns_deleting.html')`.
- Карточка добавлена на главную `/` (раздел "Управление").

### Backend: send.py — send_delete_campaigns()
```python
def send_delete_campaigns(endpoint, headers, changes, dry_run=False):
    """Удалить кампании целиком (POST /adsApi/v1/delete/campaigns, до 1000 за раз)"""
    campaign_ids = [c["entity_id"] for c in changes]
    resp = amz_post(endpoint, "/adsApi/v1/delete/campaigns", headers, {"campaignIds": campaign_ids})
    return parse_multi_response(resp, "campaigns", len(changes))
```
- Новый `entity_type='campaign_delete'` в `group_changes()` → группа `delete_campaigns`,
  зарегистрирована в `send_funcs` dispatch (после `create_campaigns`).
- `update_campaigns_bq()`: при успехе `campaign_delete` → `DELETE FROM campaigns_table
  WHERE campaign_id=... AND marketplace=...` (полная очистка из BQ).

### Backend: control_routes.py
- `campaign_delete` добавлен в `ALLOWED_OPS` (`["—"]`) и в `LABELS`
  (`"🗑️ Удалить кампанию"`).
- `campaign_delete` добавлен в `NO_DUP_CHECK` (оба места — `/control/add` и
  `/control/add_batch`), иначе `/control/add_batch` возвращал
  `400 "не поддерживается в batch"`.
- `camp_ids` для подтягивания `campaign_name` в `/control/pending` теперь объединяет
  `by_type["campaign"]` и `by_type["campaign_delete"]`, чтобы названия кампаний
  отображались и для записей на удаление.

### Workflow удаления
1. Выбор кампаний на `/campaigns-deleting` → "Удалить" → confirm
2. Batch `entity_type='campaign_delete', field_name='—', new_value='DELETED'`
   → `POST /control/add_batch` → запись в `pending_changes_merch/kdp` (status=PENDING)
3. Одобрение на `/control` (label "🗑️ Удалить кампанию", имя кампании подтягивается)
4. `send.py` → `send_delete_campaigns` → `POST /adsApi/v1/delete/campaigns`
5. При успехе строка кампании удаляется из `campaigns_merch/kdp` в BigQuery

### Важный баг-фикс (та же сессия): _AMZ NameError в control_routes.py
В какой-то момент в `control_routes.py` пропал блок загрузки секретов:
```python
AMZ_SECRETS_PATH = os.path.join(BASE_DIR, 'config', 'amazon_secrets.json')
with open(AMZ_SECRETS_PATH) as _f:
    _AMZ = json.load(_f)
```
Без него `/control/profiles` падал с `NameError: name '_AMZ' is not defined` (500),
из-за чего фронтенд получал пустой `profile_id` и `/control/add_batch` возвращал
400 "Нет валидных элементов". Блок восстановлен сразу после `BASE_DIR/PROJECT_ID/DATASET`.

### Известный риск при ручном редактировании файлов через str_replace
При добавлении `send_delete_campaigns` в send.py случайно была удалена строка
`def send_create_campaigns(endpoint, headers, changes, dry_run=False):` — остался
docstring без `def`, что вызывало `NameError: name 'send_create_campaigns' is not defined`
при обращении к dispatch-таблице `send_funcs`. После каждой правки длинных файлов
через `str_replace` — обязательно `python3 -m py_compile` + `diff` с версией на GitHub

---

## Страница "Таргеты" (/targets) — массовые действия и пагинация (июнь 2026)

### Чекбоксы и массовые действия для таргетов (mode=targets)

В `renderTargets()` добавлена колонка с чекбоксами слева. Каждая строка содержит:
```html
<input type="checkbox" class="row-cb"
  data-id="..." data-type="keyword|target" data-mkt="US"
  data-state="ENABLED|PAUSED" data-bid="0.5">
```
Первая ячейка `<th>` — select-all чекбокс. При выборе хотя бы одной строки появляется
нижняя панель `.bulk-bar` с кнопками действий.

**Кнопки bulk-bar:**
- ▶ Включить — `bulkSetState('ENABLED')`
- ⏸ Пауза — `bulkSetState('PAUSED')`
- ✕ Архивировать — `bulkSetState('ARCHIVED')`
- $ Изменить ставку — `openBulkBid()` → `modalBulkBid`
- Снять выбор — `bulkClear()`

`bulkSetState()` и `submitBulkBid()` используют `ctrlUpdateBatch()` →
`POST /control/add_batch_update` (НЕ `/control/add_batch`, который не поддерживает keyword/target).

### Чекбоксы и массовые действия для групп (mode=groups)

В `renderGroups()` аналогично добавлены чекбоксы с `data-type="ad_group"`.
Те же кнопки (без "Изменить ставку" — ставка группы редактируется inline).

### Modal modalBulkBid

Один input `id="bbidVal"`. Режим выбирается через radio:
- **Точное значение** — вводится число, отправляется как `field_name: 'bid'`, `new_value: число`
- **% повышение** — вводится процент, `new_value` = `Math.round(old_bid * (1 + pct/100) * 100)/100`
- **% понижение** — аналогично со знаком минус

`onBbidModeChange()` динамически меняет label, min и placeholder у поля ввода.

### /control/add_batch_update (новый endpoint)

`POST /control/add_batch_update` в `control_routes.py`:
- Принимает те же поля что и `/control/add_batch`
- Поддерживает `entity_type`: `keyword`, `target`, `ad_group`, `campaign`
- Дедупликация: одним SQL `SELECT entity_id, field_name FROM table WHERE entity_id IN (...) AND status IN ('PENDING','APPROVED')` — пропускает (не ошибка) дубликаты
- Возвращает `{"success": true, "inserted": N, "skipped": M, "errors": [...]}`

### Настраиваемая пагинация

Селект `<select id="perPageSel">` с вариантами 25 / 50 / 100 / 200 строк.
Хранится в `S.perPage`, передаётся в `/targets/data` как параметр `per_page`.
`renderPagination()` синхронизирует значение селекта с `S.perPage` при каждом рендере.
`onPerPageChange()` сбрасывает `S.page = 1` и вызывает `load()`.

CSS: `.per-page-sel` — inline-блок рядом с пагинацией. `.pg-right` — правый блок пагинации.
При активной bulk-bar: `body.bulk-active .toast-wrap { bottom: 70px }` — тосты поднимаются выше панели.

---

## Страница "Бюджет кампаний" (/budget-analysis) — июнь 2026

### Назначение
Анализ утилизации бюджетов кампаний: насколько фактический расход соответствует заданному бюджету.
Массовое изменение бюджетов, дат окончания, включение/пауза.

### Маршрут
`GET /budget-analysis` → `analytics_routes.py` → `send_from_directory(BASE_DIR, 'budget_analysis.html')`.
Карточка на главной `/` в разделе "Аналитика" (зелёная).

### Источник данных
Использует тот же endpoint что и `campaigns_analytics.html`:
`GET /analytics/campaigns/data` — возвращает `daily_budget`, `cost`, `campaign_state`, `end_date` и т.д.

### Утилизация бюджета
```js
const periodDays = Math.max(1, (new Date(S.dt) - new Date(S.df)) / 86400000 + 1);
const util = Math.min(200, cost / (daily_budget * periodDays) * 100);
```
Отображается как progress-bar:
- **≥ 80%** — зелёный (хорошо)
- **≥ 50%** — янтарный (умеренно)
- **< 50%** — красный (бюджет используется слабо)

### Статистика (шапка)
- Кампаний (count)
- Бюджет/день (сумма `daily_budget`)
- Расход (сумма `cost`)
- Утилизация (средняя %)
- Продажи, ACoS

### Таблица
Колонки: checkbox | toggle state | Название + бейджи | Маркетплейс | Бюджет (inline edit) |
Утилизация (bar + %) | Расход | Продажи | ACoS | Показы | Клики | Дата окончания (inline edit)

**Inline-редактирование бюджета:** клик на ячейку → input, Enter/blur → `ctrlAdd` с
`entity_type:'campaign'`, `field_name:'daily_budget'`.

**Inline-редактирование даты окончания:** клик → input type=date, Enter/blur → `ctrlAdd` с
`entity_type:'campaign'`, `field_name:'end_date'`.

### Массовые действия (bulk)
- **Включить / Пауза** — `bulkSetState()` → `ctrlUpdateBatch()` → `/control/add_batch_update`
  с `entity_type:'campaign'`, `field_name:'state'`
- **Изменить бюджет** (`openBulkBudget` → `modalBulkBudget`) — три режима:
  - Точное значение: `field_name:'daily_budget'`, `new_value: число`
  - % повышение / % понижение: вычисляется на фронте из текущего `daily_budget`
- **Изменить дату окончания** (`openBulkEndDate` → `modalBulkEndDate`) — одна дата для всех,
  `field_name:'end_date'`

### Фильтры
MERCH/KDP, диапазон дат, маркетплейс, портфолио, статус, поиск по названию.

**Портфолио:** загружается через `GET /portfolios/list` (тот же endpoint что в campaigns_analytics).
Фильтрация на фронте: `p.account_type === S.acct`. Поля: `p.portfolio_id`, `p.portfolio_name`.
Функция `filterPortfoliosByAcct()` вызывается при смене аккаунта MERCH/KDP.

**Профили:** `GET /control/profiles` → `getProfileId(mkt)` по ключу `S.acct + '_' + mkt`.

### Настраиваемая пагинация
Те же 25/50/100/200, синхронизируется с `S.perPage`.

---

## send.py — таймауты и повторные попытки (июнь 2026)

### Проблема
При отправке ~700 изменений (бюджеты + даты) `requests.post()` без таймаута зависал
на неопределённое время если Amazon не отвечал. Скрипт не падал — просто висел навсегда.

### Решение
```python
# Токен
resp = requests.post(..., timeout=30)

# amz_post — все запросы к Amazon API
def amz_post(endpoint, path, headers, body, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.post(f"{endpoint}{path}", headers=headers, json=body, timeout=60)
        except requests.Timeout:
            wait = 10 * (attempt + 1)
            print(f"  Timeout на {path}, ждём {wait}s...")
            time.sleep(wait)
            continue
        except requests.ConnectionError as e:
            wait = 10 * (attempt + 1)
            time.sleep(wait)
            continue
        if resp.status_code == 429:
            wait = 5 * (attempt + 1)
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            wait = 10 * (attempt + 1)
            time.sleep(wait)
            continue
        return resp
    raise RuntimeError(f"Не удалось выполнить запрос {path} после {retries} попыток")
```
Максимальное время на один батч в худшем случае: 60 сек × 3 попытки = 3 минуты.
Обычный ответ Amazon: 1–3 секунды.

### Почему FAILED при реально успешной операции
Сценарий "ложного FAILED":
1. Первый запуск отправил изменение → Amazon выполнил
2. Скрипт завис ожидая ответ (без таймаута) → статус остался `SENDING`
3. Следующий запуск: `reset_stale_sending()` → `SENDING → APPROVED` → повторная отправка
4. Amazon: "уже в этом состоянии" → ошибка → статус `FAILED`
5. Реально всё сработало с первого раза

После добавления таймаута такой сценарий невозможен.

### Диагностика зависших записей (BigQuery)
```sql
-- Проверить застрявшие SENDING
SELECT status, entity_type, COUNT(*) as cnt, MIN(created_at) as oldest
FROM `amazon-ads-api-494412.amazon_ads.pending_changes_merch`
WHERE status = 'SENDING'
GROUP BY status, entity_type;

-- Сбросить вручную
UPDATE `amazon-ads-api-494412.amazon_ads.pending_changes_merch`
SET status = 'APPROVED'
WHERE status = 'SENDING';

-- Посмотреть ошибки
SELECT entity_type, error_msg, COUNT(*) as cnt
FROM `amazon-ads-api-494412.amazon_ads.pending_changes_merch`
WHERE status = 'FAILED' AND DATE(created_at) >= '2026-06-12'
GROUP BY entity_type, error_msg
ORDER BY cnt DESC;
```
**Важно:** колонка называется `created_at` (не `updated_at`) и `error_msg` (не `error_message`).
перед коммитом, проверяя что не пропали соседние строки/определения функций.
---

## Страница поисковых запросов `/search-terms` (июнь 2026)

### Файлы
- `search_terms_routes.py` — Blueprint `search_terms_bp`
- `search_terms.html` — фронтенд страницы
- Зарегистрирован в `app.py`: `app.register_blueprint(search_terms_bp)`
- Карточка добавлена на `index.html` в секцию Analytics

### Таблицы BigQuery
- `search_terms_{merch|kdp}` — поля: `date, campaign_id, ad_group_id, keyword_id, keyword, keyword_type, targeting, match_type, search_term, impressions, clicks, cost, purchases_14d, sales_14d, marketplace`
- `asin_stats_{merch|kdp}` — поля: `ad_group_id, advertised_asin, marketplace, ...`
- `portfolio_labels` (без суффикса) — поля: `portfolio_id, portfolio_name, account_type, marketplace`
- `campaigns_{merch|kdp}` — `entity_type='campaign'` и `entity_type='ad_group'`

### Типы ключевых слов (keyword_type)
- `BROAD / PHRASE / EXACT` — ручные ключевые слова (initiator_type=keyword)
- `TARGETING_EXPRESSION_PREDEFINED` — авто кампания (initiator_type=auto)
- `TARGETING_EXPRESSION` — таргет по продукту (initiator_type=product)

### API endpoints

**`GET /search-terms/data`** — фильтры:
- `account_type` (MERCH/KDP), `date_from`, `date_to`, `marketplace`
- `portfolio_ids` — запятые-разделённые portfolio_id
- `name` — поиск по тексту search_term (LIKE)
- `initiator_type` — keyword / auto / product / ''
- `match_type_filter` — BROAD / PHRASE / EXACT / AUTO / ''
- `query_type` — text / product (ASIN по regex `^B[0-9A-Z]{9}$`) / ''
- `state_filter` — ad_group_state (ENABLED/PAUSED)
- `camp_state_filter` — campaign_state (ENABLED/PAUSED)
- Числовые: `{field}_op/_val/_min/_max` для impressions, clicks, cost, ctr, sales_14d, purchases_14d, acos
- Пагинация: `page`, `per_page`, `sort_by`, `sort_dir`

Возвращает: `{rows, total, page, per_page, summary: {total_count, sum_impressions, sum_clicks, sum_cost, sum_sales, sum_purchases}}`

**`GET /search-terms/groups-for-asin`** — принимает `ad_group_id`, ищет ASIN из `asin_stats_{suffix}`, возвращает все группы где рекламируется тот же ASIN:
- `{groups: [{ad_group_id, ad_group_name, ad_group_state, campaign_id, campaign_name, campaign_state, targeting_type, marketplace}], asin}`
- Сортировка: активные (ENABLED+ENABLED) первыми, затем по campaign_name / ad_group_name

### Ключевые функции фронтенда

**`renderRows(rows)`** — отрисовка таблицы:
- `editedTerms{}` — карта локально отредактированных текстов (для использования при добавлении в минус)
- Колонка "Инициатор": для auto → `—`, для product → текст targeting, для keyword → текст keyword
- Колонка "Тип": `kwTypeBadge(keyword_type)` — AUTO / PROD / BROAD / PHRASE / EXACT бейджи
- Колонка "Совп.": для auto → `—`, для остальных → `matchTypeBadge(match_type)`
- Кнопка "+Ключ" появляется при `tr:hover` (opacity:0 → opacity:1)

**`_negPairs` array** — `[{term, ad_group_id, campaign_id, marketplace, ad_group_name, campaign_name}]`:
- Хранит точные пары (запрос → группа) из выбранных строк
- Используется в `openBulkNeg()` и `submitNeg()` для правильного назначения (каждый минус → только в свою группу)

**`isAsin(t)`** — `/^[Bb][0-9A-Za-z]{9}$/.test(t||'')`

**`openBulkNeg()`**:
- Дедуплицирует пары по `${term}|${ad_group_id}`
- Если все ASINы → скрывает строку EXACT/PHRASE
- Показывает тип-подсказку (зелёный бейдж для ASIN, синий для текста)

**`submitNeg()`**:
- ASINы → `entity_type: 'negative_product_add'`, payload `{asin, ad_group_id, campaign_id}`
- Текст → `entity_type: 'negative_add'`, payload `{text, match_type, ad_group_id, campaign_id}`
- Все payloads включают `account_type: S.acct`

**`openRowKw(term, agId, campId, mkt)`** — модал добавления ключевого слова:
- Загружает группы через `/search-terms/groups-for-asin?ad_group_id=agId&...`
- Активные группы предчекнуты, источник помечен ★

**`submitAddKw()`**:
- `entity_type: 'keyword_add'`, payload `{keyword, match_type, bid, campaign_id, ad_group_id}`
- Включает `account_type: S.acct`

