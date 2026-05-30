# Amazon Ads Automation — Контекст проекта

## Цель системы
Автоматизация сбора рекламной статистики и управления ставками для Merch by Amazon и KDP рекламы.
Анализ кликов по ключевым словам, управление ставками через pending_changes,
сравнение рекламных расходов с органическими продажами MBA.

---

## Стек

| Сервис | Роль | URL / Доступ |
|---|---|---|
| **BigQuery** | Хранилище — каталог, реклама, продажи | Project: `amazon-ads-api-494412`, Dataset: `amazon_ads` |
| **PythonAnywhere** | Скрипты, веб-интерфейс | `nikolaenkots.pythonanywhere.com` · папка `~/amazon-ads/` |
| **Retool** | Частично используется | — |
| **Looker Studio** | Дашборды — реклама vs продажи, ACOS | — |
| **Amazon Ads API** | Reporting v3, SP API v1 | OAuth2, secrets в `~/amazon-ads/config/` |

---

## Структура файлов на сервере (~/amazon-ads/)

### Flask приложение (разбито на Blueprint модули)

| Файл | Статус | Описание |
|---|---|---|
| `app.py` | ✅ Готов | Flask init + регистрация blueprints + главная страница `/` |
| `catalog_routes.py` | ✅ Готов | Blueprint каталога — `/catalog`, `/upload`, `/progress/<id>` |
| `earnings_routes.py` | ✅ Готов | Blueprint продаж — `/earnings`, `/upload_earnings`, `/earnings_progress/<id>` |
| `ads_routes.py` | ✅ Готов | Blueprint рекламы — `/ads`, `/ads/create_report`, `/ads/refresh_statuses` и др. |
| `campaigns_routes.py` | ✅ Готов | Blueprint кампаний — `/campaigns`, `/campaigns/sync`, `/campaigns/preview` |
| `portfolios.py` | ✅ Готов | Blueprint портфолио — `/portfolios/*` endpoints |
| `analytics_routes.py` | ✅ Готов | Blueprint аналитики — `/analytics/campaigns`, `/analytics/campaigns/data`, `/analytics/campaigns/portfolios`, `/analytics/campaigns/structure`, `/analytics/debug/targeting` |
| `collect.py` | ✅ Готов | Сбор статистики из Amazon Ads API через CLI |

### HTML страницы

| Файл | URL | Описание |
|---|---|---|
| `index.html` | `/` | Главная страница — навигация |
| `catalog.html` | `/catalog` | Импорт каталога из Productor CSV |
| `earnings.html` | `/earnings` | Импорт отчёта продаж MBA |
| `ads.html` | `/ads` | Сбор рекламной статистики |
| `campaigns.html` | `/campaigns` | Синхронизация кампаний из SP API |
| `portfolios.html` | `/portfolios` | Управление именами портфолио |
| `campaigns_analytics.html` | `/analytics/campaigns` | Аналитика кампаний с фильтрами, пагинацией и раскрытием структуры |

### Конфиги и данные

| Файл | Описание |
|---|---|
| `config/amazon_secrets.json` | Amazon Ads API ключи и профили |
| `config/bigquery_key.json` | Ключ сервисного аккаунта Google Cloud |
| `reports_log.json` | Лог очереди отчётов Amazon Ads |

---

## Архитектура Flask (Blueprint модули)

```
app.py
├── catalog_routes.py   → catalog_bp
├── earnings_routes.py  → earnings_bp
├── ads_routes.py       → ads_bp
├── campaigns_routes.py → campaigns_bp
├── portfolios.py       → portfolios_bp
└── analytics_routes.py → analytics_bp
```

`progress_store = {}` — shared dict в `app.py`, импортируется всеми blueprints через `import app`.

Каждый blueprint получает его через:
```python
def _get_progress_store():
    import app
    return app.progress_store
```

---

## Analytics API (analytics_routes.py)

### Страница аналитики кампаний
```
GET /analytics/campaigns → campaigns_analytics.html
```

### Данные кампаний
```
GET /analytics/campaigns/data
```
Параметры:
- `account_type` — MERCH | KDP
- `date_from`, `date_to` — YYYY-MM-DD
- `marketplace` — US | UK | DE | FR | IT | ES | CA | AU
- `portfolio_id` — один portfolio_id
- `portfolio_ids` — несколько через запятую (мультивыбор)
- `targeting_type` — AUTO | MANUAL
- `campaign_state` — ENABLED | PAUSED
- `activity` — has_clicks | has_impressions | no_clicks | no_impressions
- `name` — поиск по campaign_name
- `sort_by`, `sort_dir` — сортировка
- `page`, `per_page` — пагинация (max 100)
- Числовые фильтры: `clicks_op/val/min/max`, `acos_op/val/min/max`, `cost_op/val/min/max`, `impressions_*`, `sales_14d_*`, `purchases_14d_*`, `ctr_*`

Возвращает: `rows`, `total`, `page`, `per_page`, `summary` (агрегаты по всей выборке).

### Портфолио для фильтра
```
GET /analytics/campaigns/portfolios?account_type=MERCH&marketplace=US
```
Возвращает уникальные портфолио из `campaigns_merch` с JOIN на `portfolio_labels`.

### Структура кампании
```
GET /analytics/campaigns/structure?campaign_id=...&account_type=MERCH&date_from=...&date_to=...
```
Возвращает:
- `campaign_name` — полное название кампании
- `adjustments` — плейсменты (TOP_OF_SEARCH, PRODUCT_PAGE, REST_OF_SEARCH) с процентами
- `groups` — группы объявлений, каждая содержит:
  - `stats` — суммарная статистика группы за период
  - `keywords` — ключевые слова с `stats` и `search_terms`
  - `targets` — product targeting с `stats`
  - `negatives` — минус слова
  - `search_terms` — поисковые запросы группы (для AUTO)

Статистика для auto-таргетов: маппинг `targets_stats.targeting` → `campaigns_merch.targeting_expression`:
- `close-match` → `KEYWORDS_CLOSE_MATCH`
- `loose-match` → `KEYWORDS_LOOSE_MATCH`
- `substitutes` → `PRODUCT_SUBSTITUTES`
- `complements` → `PRODUCT_COMPLEMENTS`

### Debug endpoint
```
GET /analytics/debug/targeting?campaign_id=...&account_type=MERCH&date_from=...&date_to=...
```
Показывает raw данные из `targets_stats` и `campaigns_merch` для отладки маппинга.

---

## Amazon Ads API

### Авторизация
```
Endpoint auth:   https://api.amazon.com/auth/o2/token
Grant type:      refresh_token
Client ID:       в config/amazon_secrets.json
Refresh token:   в config/amazon_secrets.json
```

### Профили (profile_id)
```
Merch US:  2418854071638725  → advertising-api.amazon.com
Merch IT:  1643110315908506  → advertising-api-eu.amazon.com
Merch ES:  3571496662552642  → advertising-api-eu.amazon.com
Merch UK:  180261448232436   → advertising-api-eu.amazon.com
Merch DE:  2023177291219092  → advertising-api-eu.amazon.com
Merch FR:  613747068444603   → advertising-api-eu.amazon.com
KDP US:    2138688425253475  → advertising-api.amazon.com
KDP CA:    216157406396956   → advertising-api.amazon.com
KDP UK:    3828973734410759  → advertising-api-eu.amazon.com
KDP DE:    1209740463543490  → advertising-api-eu.amazon.com
KDP FR:    2062477294536113  → advertising-api-eu.amazon.com
KDP IT:    2012455889033628  → advertising-api-eu.amazon.com
KDP ES:    1530105280135495  → advertising-api-eu.amazon.com
KDP AU:    2089815793960864  → advertising-api-fe.amazon.com
```
Merch EU профили получены через `/managerAccounts` EU endpoint как VENDOR type.
Все профили работают — статус 200 при создании отчётов подтверждён.

### Типы отчётов (Reporting API v3)
```
POST https://{endpoint}/reporting/reports
Content-Type: application/vnd.createasyncreportrequest.v3+json
```

| reportTypeId | groupBy | Таблица BQ |
|---|---|---|
| spTargeting | targeting | targets_stats_merch / targets_stats_kdp |
| spAdvertisedProduct | advertiser | asin_stats_merch / asin_stats_kdp |
| spSearchTerm | searchTerm | search_terms_merch / search_terms_kdp |

### SP API (управление)
```
POST https://{endpoint}/adsApi/v1/query/campaigns   → справочник кампаний
POST https://{endpoint}/adsApi/v1/query/adGroups    → справочник групп
POST https://{endpoint}/adsApi/v1/query/targets     → справочник таргетов
POST https://{endpoint}/adsApi/v1/query/ads         → product ads
POST https://{endpoint}/adsApi/v1/update/targets    → обновление ставок
```

Portfolios API (`/adsApi/v1/query/portfolios`) — возвращает 401/404, недоступен.
Имена портфолио хранятся в таблице `portfolio_labels` и управляются вручную.

---

## Структура БД BigQuery (dataset: amazon_ads)

### catalog ✅ ГОТОВА
```sql
listing_id        STRING NOT NULL  -- уникальный ключ (design_id_PRODUCTTYPE_MARKETPLACE)
asin              STRING NOT NULL
marketplace       STRING NOT NULL
design_id         STRING
brand             STRING
title             STRING
product_type      STRING
price             FLOAT64
status            STRING
bullet_point_1    STRING
bullet_point_2    STRING
ad_asin           STRING
tags              STRING
image_url         STRING
live_url          STRING
edit_url          STRING
created_at_amazon TIMESTAMP
imported_at       TIMESTAMP
```

### earnings ✅ ГОТОВА
```sql
row_hash          STRING          -- MD5 для дедупликации
marketplace       STRING
sale_date         DATE
asin              STRING
title             STRING
category_1/2/3    STRING
product_type      STRING
purchased         INT64
cancelled         INT64
returned          INT64
revenue           FLOAT64
royalties         FLOAT64
currency          STRING
imported_at       TIMESTAMP
```

### campaigns_merch / campaigns_kdp ✅ ГОТОВЫ
```sql
entity_type           STRING  -- campaign/ad_group/keyword/negative_keyword/product_targeting/product_ad/bidding_adjustment
profile_id            STRING
marketplace           STRING
campaign_id           STRING
campaign_name         STRING
targeting_type        STRING  -- AUTO/MANUAL
bidding_strategy      STRING
daily_budget          FLOAT64
start_date            DATE
end_date              DATE
campaign_state        STRING
portfolio_id          STRING
portfolio_name        STRING  -- берётся из portfolio_labels при синхронизации
placement             STRING
placement_percentage  FLOAT64
ad_group_id           STRING
ad_group_name         STRING
ad_group_default_bid  FLOAT64
ad_group_state        STRING
keyword_id            STRING
keyword_text          STRING
match_type            STRING
keyword_bid           FLOAT64
keyword_state         STRING
target_id             STRING
targeting_expression  STRING
target_bid            FLOAT64
target_state          STRING
ad_id                 STRING
sku                   STRING
asin                  STRING
ad_state              STRING
synced_at             TIMESTAMP
```

### portfolio_labels ✅ ГОТОВА
```sql
portfolio_id    STRING NOT NULL
portfolio_name  STRING NOT NULL
account_type    STRING NOT NULL  -- MERCH / KDP
marketplace     STRING NOT NULL
notes           STRING
```
Управляется через `/portfolios` страницу.
`portfolio_id` уникален — один id не повторяется в разных маркетплейсах.

### targets_stats_merch / targets_stats_kdp ✅ ГОТОВЫ
```sql
date, profile_id, marketplace, campaign_id, ad_group_id
keyword_id, keyword, keyword_type, targeting, ad_keyword_status
impressions, clicks, cost, top_of_search_impression_share
purchases_1d/7d/14d, sales_1d/7d/14d, units_1d/7d/14d
loaded_at
```
PARTITION BY date, CLUSTER BY marketplace, campaign_id, keyword_type

### asin_stats_merch / asin_stats_kdp ✅ ГОТОВЫ
```sql
date, profile_id, marketplace, campaign_id, ad_group_id
advertised_asin, advertised_sku
impressions, clicks, cost
purchases_1d/7d/14d, sales_1d/7d/14d, units_1d/7d/14d
loaded_at
```

### search_terms_merch / search_terms_kdp ✅ ГОТОВЫ
```sql
date, profile_id, marketplace, campaign_id, ad_group_id
keyword_id, keyword, keyword_type, targeting, match_type, search_term
impressions, clicks, cost
purchases_1d/7d/14d, sales_1d/7d/14d, units_1d/7d/14d
loaded_at
```

### pending_changes_merch / pending_changes_kdp ✅ СОЗДАНЫ
```sql
id              STRING NOT NULL   -- uuid
created_at      TIMESTAMP NOT NULL
entity_type     STRING NOT NULL   -- campaign / keyword / ad
entity_id       STRING NOT NULL
profile_id      STRING NOT NULL
marketplace     STRING NOT NULL
field_name      STRING NOT NULL   -- name / bid / state
old_value       STRING
new_value       STRING NOT NULL
status          STRING NOT NULL   -- PENDING / SENDING / FAILED
error_msg       STRING
retry_count     INT64
```
PARTITION BY DATE(created_at), CLUSTER BY status, entity_type

### change_log_merch / change_log_kdp ✅ СОЗДАНЫ
```sql
id              STRING NOT NULL
pending_id      STRING            -- ссылка на pending_changes.id
sent_at         TIMESTAMP NOT NULL
entity_type     STRING NOT NULL
entity_id       STRING NOT NULL
profile_id      STRING NOT NULL
marketplace     STRING NOT NULL
field_name      STRING NOT NULL
old_value       STRING
new_value       STRING NOT NULL
result          STRING NOT NULL   -- SUCCESS / FAILED
error_msg       STRING
```
PARTITION BY DATE(sent_at), CLUSTER BY result, entity_type

---

## Portfolios API (endpoints)

```
GET  /portfolios             → HTML страница управления портфолио
POST /portfolios/sync        → сканирует campaigns_*, добавляет новые в portfolio_labels
POST /portfolios/update      → обновляет одну запись
POST /portfolios/bulk-update → обновляет массив изменений {changes: [...]}
GET  /portfolios/list        → возвращает все портфолио из portfolio_labels
POST /portfolios/import-csv  → импорт имён из CSV через MERGE {rows: [{portfolio_id, portfolio_name}]}
```

### Импорт CSV (portfolios.html → /portfolios/import-csv)
Поддерживает два формата:
- **Amazon Bulk CSV** (разделитель `;`) — колонки `Portfolio ID`, `Portfolio Name`, фильтрует строки где `Entity = Portfolio`
- **Простой CSV** (разделитель `,`) — колонки `portfolio_id`, `portfolio_name`

---

## Логика импорта каталога

CSV формат — экспорт из расширения Productor для Chrome.

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
    if (!filtered.length) {
      console.log("Нет товаров после указанной даты");
      return;
    }
    const keys = [
      "asin", "brandName", "createdDate", "currencyCode", "deleteReasonType",
      "designId", "estimatedExpirationDate", "listPrice", "listingId",
      "lockReasonType", "marketplace", "productImageUrn", "productTitle",
      "productType", "searchableOnRetail", "status", "updatedDate", "pm_data"
    ];
    const csv = [
      keys.join(","),
      ...filtered.map(row =>
        keys.map(k => JSON.stringify(row[k] ?? "")).join(",")
      )
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "prettymerch_products.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    console.log(`Всего в базе: ${data.length}`);
    console.log(`Выгружено после ${new Date(fromDate * 1000).toLocaleDateString()}: ${filtered.length}`);
  };
};
```

**Важно:** строки с пустым `asin` (новые товары без присвоенного Amazon ASIN) отбрасываются
при импорте. После того как Amazon присвоит ASIN, следующий импорт добавит их через MERGE.

### Процесс обновления (MERGE):
1. DROP + CREATE catalog_staging
2. INSERT данные в staging чанками по 1000 строк
3. MERGE staging → catalog (по `listing_id`, поле `tags` не перезаписывается)
4. DROP catalog_staging (очистка)

---

## Логика сбора рекламной статистики

### Через веб-интерфейс (ads.html)
1. POST /ads/create_report → создаёт отчёт в Amazon, пишет в reports_log.json
2. POST /ads/refresh_statuses → проверяет статусы, скачивает готовые, пишет в BigQuery

### Через CLI (collect.py)
```bash
python3 collect.py --date 2026-05-31 --account MERCH --marketplace US
python3 collect.py --date 2026-05-31 --all
```

Процесс: авторизация → создание отчёта → поллинг статуса → скачивание → DELETE старых данных за период → WRITE_APPEND в BigQuery.

Использует MERGE вместо цикла UPDATE чтобы избежать ошибки `concurrent update` в BigQuery.

---

## Как обновить на сервере

```bash
cd ~/amazon-ads
git add -A
git commit -m "описание изменений"
git push
```

### Что НЕ попадает в GitHub (.gitignore)
```
config/          # секреты Amazon API и BigQuery ключ — никогда не пушить
uploads/         # временные файлы загрузок
*.pyc
__pycache__/
streamlit_app.py
```

### Файлы которые есть в репо но НЕ нужно удалять из проекта Claude

| Файл | Зачем хранить |
|---|---|
| `collect.py` | CLI скрипт для сбора статистики — используется регулярно |
| `fix_uk_fr.py` | Скрипт исправления профилей UK/FR — может понадобиться |
| `get_merch_eu_profiles.py` | Получение EU профилей — справочный скрипт |
| `test_merch_eu_report.py` | Тест EU отчётов — справочный |
| `test_uk_fr.py` | Тест UK/FR профилей — справочный |
| `try_vendor_eu.py` | Тест vendor EU — справочный |
| `reports_log.json` | Лог отчётов — активный файл, обновляется при работе |
| `.gitignore` | Настройки git — не трогать |

### Подключение репо к Claude проекту
Project → Add content → Link GitHub repository → выбери `nikolaenkots/amazon-ads`

---

## Как использовать этот документ

Вставь этот текст в начало нового чата с Claude перед описанием задачи.
Например: "Вот контекст проекта: [этот документ]. Задача: создать analyze.py..."