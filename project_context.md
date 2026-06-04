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

## Файловая структура (~/amazon-ads/)

### Flask приложение

| Файл | Blueprint | Описание |
|---|---|---|
| `app.py` | — | Flask init, регистрация blueprints, `progress_store = {}` |
| `catalog_routes.py` | `catalog_bp` | `/catalog` — импорт каталога из Productor CSV |
| `earnings_routes.py` | `earnings_bp` | `/earnings` — импорт отчётов продаж MBA |
| `ads_routes.py` | `ads_bp` | `/ads` — сбор рекламной статистики |
| `campaigns_routes.py` | `campaigns_bp` | `/campaigns` — синхронизация структуры кампаний из SP API |
| `portfolios.py` | `portfolios_bp` | `/portfolios` — управление именами портфолио |
| `analytics_routes.py` | `analytics_bp` | `/analytics/campaigns` — аналитика кампаний |
| `products_routes.py` | `products_bp` | `/analytics/products` — аналитика по рекламируемым ASIN ← НОВЫЙ |
| `control_routes.py` | `control_bp` | `/control` — управление рекламой через pending_changes |

### HTML страницы

| Файл | URL | Описание |
|---|---|---|
| `index.html` | `/` | Главная — навигация по всем разделам |
| `campaigns_analytics.html` | `/analytics/campaigns` | Аналитика кампаний с фильтрами, структурой, управлением |
| `products_analytics.html` | `/analytics/products` | Аналитика по рекламируемым ASIN ← НОВЫЙ |
| `control.html` | `/control` | Очередь изменений: Ожидают / Одобрено / История |
| `catalog.html` | `/catalog` | Импорт каталога |
| `earnings.html` | `/earnings` | Импорт продаж |
| `ads.html` | `/ads` | Сбор статистики |
| `campaigns.html` | `/campaigns` | Синхронизация кампаний |
| `portfolios.html` | `/portfolios` | Управление портфолио |

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
├── catalog_routes.py   → catalog_bp
├── earnings_routes.py  → earnings_bp
├── ads_routes.py       → ads_bp
├── campaigns_routes.py → campaigns_bp
├── portfolios.py       → portfolios_bp
├── analytics_routes.py → analytics_bp
├── products_routes.py  → products_bp      ← НОВЫЙ
└── control_routes.py   → control_bp
```

`progress_store = {}` — shared dict в `app.py`, используется всеми blueprints:
```python
def _get_progress_store():
    import app
    return app.progress_store
```

Регистрация `products_bp` в `app.py`:
```python
from products_routes import products_bp
app.register_blueprint(products_bp)
```

---

## Analytics API (analytics_routes.py)

### GET /analytics/campaigns
Возвращает `campaigns_analytics.html`

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

Возвращает:
```json
{
  "campaign_name": "...",
  "campaign_end_date": "2026-06-30",
  "groups": [{
    "id": "...", "name": "...", "bid": 0.5, "state": "ENABLED",
    "stats": {"impressions": 1000, "clicks": 10, "cost": 5.0, "sales_14d": 20.0, "purchases_14d": 2, "acos": 25.0},
    "keywords": [{
      "id": "...", "text": "...", "match_type": "BROAD", "bid": 0.5, "state": "ENABLED",
      "stats": {...},
      "search_terms": [{"term": "...", "keyword_type": "...", "impressions": ..., "clicks": ..., "purchases_14d": ...}]
    }],
    "targets": [{...}],
    "negatives": [{"text": "...", "match_type": "EXACT", "type": "keyword"}],
    "search_terms": [...],
    "ads": [{"ad_id": "...", "asin": "...", "title": "...", "image_url": "...", "stats": {...}}]
  }],
  "adjustments": [{"placement": "TOP_OF_SEARCH", "percentage": 30}],
  "campaign_negatives": [{"text": "...", "type": "keyword"}]
}
```

**Важно про search_terms:**
- Для **авто-кампаний**: `search_terms` на уровне группы (`st_by_ag[(ag_id)]` → `group['search_terms']`)
- Для **мануальных кампаний**: `search_terms` на уровне ключевого слова (`st_by_kw[(ag_id, keyword_id)]` → `keyword['search_terms']`)
- В JS нужно собирать из обоих источников:
  ```js
  const allSt = [
    ...(g.search_terms || []),
    ...(g.keywords || []).flatMap(kw => kw.search_terms || []),
    ...(g.targets || []).flatMap(t => t.search_terms || []),
  ];
  ```

### GET /analytics/debug/targeting
Debug: структура кампании в BigQuery. Параметры: `campaign_id`, `account_type`, `date_from`, `date_to`

---

## Products API (products_routes.py) ← НОВЫЙ

### GET /analytics/products
Возвращает `products_analytics.html`

### GET /analytics/products/data
Список рекламируемых ASIN с агрегированной статистикой.

Параметры: `account_type`, `date_from`, `date_to`, `marketplace`, `portfolio_ids`, `asin`,
`sort_by`, `sort_dir`, `page`, `per_page`

SQL: JOIN `asin_stats_{suffix}` с `campaigns_{suffix}` (фильтр по портфолио/маркетплейсу),
LEFT JOIN `catalog` для названия, изображения, статуса, цены.

**Алиасы в SQL:** CTE использует алиас `camp` (не `c`) чтобы не конфликтовать с `cat` (catalog).

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

Возвращает список кампаний с `impressions`, `clicks`, `cost`, `sales_14d`, `purchases_14d`, `ctr`, `acos`, `portfolio_name`.

---

## Products Analytics HTML (products_analytics.html) ← НОВЫЙ

Светлая тема (`--bg: #f4f4f6`). Аналог Amazon Ads Console → Products.

**Функциональность:**
- Фильтры: Аккаунт (MERCH/KDP), дата от/до, маркетплейс, мультивыбор портфолио, поиск по ASIN
- Сводная статистика: ASIN, Показы, Клики, CTR, Расходы, Продажи 14d, Заказы 14d, ACOS
- Таблица с фото из каталога, названием, статусом, типом, ценой; сортировка, пагинация 50/страница
- Клик по строке → inline-панель кампаний (без перенаправления)
- Клик по кампании → структура групп (Таргеты / Поисковые запросы / Минус слова)
- Колонки ключевых слов: Тип · Ставка (оранжевая) · Показы · Клики · Заказы · Расходы · Продажи · ACOS
- Колонки хедера кампании: Показы · Клики · Расходы · Продажи · Заказы · ACOS · Портфолио
- Колонки хедера группы: Показы · Клики · Расходы · Продажи · Заказы · ACOS

**Портфолио dropdown:** пробует `/analytics/campaigns/portfolios`, fallback на `/portfolios/list`.

**Фильтрация групп по ASIN:**
```js
const anyHasAsin = groups.some(g => g.ads.some(a => a.asin === filterAsin));
// MANUAL: показываем только группы с совпадающим ASIN в ads
// AUTO: нет ASIN в ads → показываем группы с clicks > 0
// Если ads есть но asin null → показываем с clicks > 0
```

**Scroll без прыжков:**
- `html { overflow-anchor: none }` — отключает браузерный scroll anchoring
- `rowClick` — вставляет expand-строку через `tr.after()`, не перерисовывает таблицу
- `grpClick(this)` — передаёт header-элемент, навигация через `closest('.gg')` + `querySelector('.ggb')`, двойной `requestAnimationFrame` для восстановления `scrollY`
- Вкладки через `tabClick(event, idx)` без ID групп — `closest('.ggb')` для точного контейнера

---

## Control API (control_routes.py)

### GET /control → control.html
### GET /control/profiles → маппинг acct_marketplace → profile_id

### POST /control/add
Добавить изменение в очередь.
```json
{
  "account_type": "MERCH",
  "marketplace": "US",
  "profile_id": "2418854071638725",
  "entity_type": "campaign",
  "entity_id": "313276520414059",
  "field_name": "state",
  "old_value": "ENABLED",
  "new_value": "PAUSED"
}
```
Возвращает: `{"success": true, "id": "uuid", "label": "⏸ Пауза"}`
409 если уже есть PENDING для этого объекта

### POST /control/approve — `{account_type, ids: [...]}`
### POST /control/reject — `{account_type, ids: [...]}`
### POST /control/send — `{account_type, marketplace?}` → запускает send.py в фоне, возвращает `job_id`
### GET /control/send/status/<job_id>
### GET /control/pending — `?account_type=MERCH&status=PENDING&marketplace=US&limit=200`
### GET /control/log — `?account_type=MERCH&marketplace=US&limit=100&result=SUCCESS`

### Допустимые операции (ALLOWED_OPS)

| entity_type | field_name | Описание |
|---|---|---|
| `campaign` | `state` | ENABLED / PAUSED |
| `campaign` | `name` | Переименовать |
| `campaign` | `daily_budget` | Дневной бюджет |
| `campaign` | `portfolio_id` | Перенести в портфолио |
| `campaign` | `end_date` | Дата окончания (YYYY-MM-DD или пусто) |
| `ad_group` | `state` | ENABLED / PAUSED |
| `ad_group` | `name` | Переименовать |
| `ad_group` | `default_bid` | Ставка группы |
| `keyword` | `state` | ENABLED / PAUSED |
| `keyword` | `bid` | Ставка |
| `target` | `state` | ENABLED / PAUSED (авто-таргеты) |
| `target` | `bid` | Ставка авто-таргета |
| `product_ad` | `state` | ENABLED / PAUSED |
| `keyword_add` | `—` | new_value = JSON `{text, match_type, bid, ad_group_id, campaign_id}` |
| `negative_add` | `—` | new_value = JSON `{text, match_type, ad_group_id, campaign_id}` |
| `negative_delete` | `—` | entity_id = keyword_id минус слова |

---

## send.py

Читает `APPROVED` из `pending_changes`, отправляет в Amazon API, пишет в `change_log`.

```bash
python3 send.py                          # все APPROVED
python3 send.py --account MERCH          # только Merch
python3 send.py --marketplace US         # только US
python3 send.py --all                    # MERCH + KDP
python3 send.py --dry-run                # показать без отправки
```

Amazon API endpoints:
- `POST /adsApi/v1/update/campaigns` — state, name, budgets, portfolioId, endDateTime
- `POST /adsApi/v1/update/adGroups` — state, name, bid.defaultBid
- `POST /adsApi/v1/update/targets` — bid, state (keyword + target + product_ad)
- `POST /adsApi/v1/create/targets` — keyword_add, negative_add
- `POST /adsApi/v1/delete/targets` — negative_delete
- `POST /adsApi/v1/update/ads` — product_ad state

---

## Amazon Ads API

### Авторизация
```
POST https://api.amazon.com/auth/o2/token
grant_type: refresh_token
client_id / client_secret / refresh_token — в config/amazon_secrets.json
```

### Профили (profile_id)
```
MERCH_US:  2418854071638725  → advertising-api.amazon.com
MERCH_IT:  1643110315908506  → advertising-api-eu.amazon.com
MERCH_ES:  3571496662552642  → advertising-api-eu.amazon.com
MERCH_UK:  180261448232436   → advertising-api-eu.amazon.com
MERCH_DE:  2023177291219092  → advertising-api-eu.amazon.com
MERCH_FR:  613747068444603   → advertising-api-eu.amazon.com
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
```
POST https://{endpoint}/reporting/reports
Content-Type: application/vnd.createasyncreportrequest.v3+json
```
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

**Важно:** негативные product targeting (ASIN) хранятся как `entity_type = "negative_product_targeting"`,
`targeting_expression` = ASIN. ASIN из `targetDetails.productTarget.product.productId` в API ответе.

### targets_stats_merch / targets_stats_kdp
```sql
date, campaign_id, ad_group_id, keyword_id, keyword, keyword_type, targeting
impressions, clicks, cost, top_of_search_impression_share
purchases_1d/7d/14d, sales_1d/7d/14d
marketplace
```
PARTITION BY date, CLUSTER BY marketplace, campaign_id

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
status   -- PENDING → APPROVED → SENT / FAILED / REJECTED
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

### earnings
```sql
sale_date, asin, marketplace, product_type
purchased, royalties, revenue, currency
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
GET  /portfolios             → HTML страница
POST /portfolios/sync        → сканирует campaigns_*, добавляет новые в portfolio_labels
POST /portfolios/update      → обновляет одну запись
POST /portfolios/bulk-update → обновляет массив {changes: [...]}
GET  /portfolios/list        → все портфолио из portfolio_labels
POST /portfolios/import-csv  → импорт имён из CSV через MERGE
```

### Импорт CSV (два формата)
- **Amazon Bulk CSV** (разделитель `;`) — колонки `Portfolio ID`, `Portfolio Name`
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

### Процесс обновления (MERGE)
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

---

## Правила изменения ставок (бизнес-логика, планируется)

- Минимум 10 кликов за 14 дней для принятия решения
- ACOS > 40% и CVR < 1% → снизить ставку на 20%
- ACOS < 15% и CVR > 3% → повысить ставку на 15%
- Все изменения → `pending_changes` → одобрение → `send.py` → `change_log`

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

## Как обновить на сервере

```bash
cd ~/amazon-ads
git add -A
git commit -m "описание изменений"
git push
```

После изменения Python файлов — перезагрузить приложение на PythonAnywhere (Web tab → Reload).

### .gitignore (никогда не пушить)
```
config/          # API ключи и BigQuery credentials
uploads/
*.pyc
__pycache__/
```

---

## Частые проблемы и решения

### JS ошибка на странице аналитики
Симптом: кнопка "Применить" не работает, в DevTools `applyFilters is not defined`
Причина: синтаксическая ошибка в JS (незакрытые template literals, кавычки внутри строк)
Решение: проверить через `node --check /tmp/test.js` после извлечения JS из HTML

### BigQuery "Aggregations of aggregations are not allowed"
Причина: `SUM()`, `ROUND(SUM())`, `COALESCE(SUM())` или оконные функции поверх CTE с GROUP BY
Решение: убрать ROUND/COALESCE из агрегатов в SQL, вынести HAVING в WHERE внешнего запроса,
считать CTR/ACOS в Python после получения данных

### Негативные ASIN таргеты показывают PRODUCT_EXACT
Причина: ASIN хранится в `targetDetails.productTarget.product.productId`, не в `productTarget.productId`
Решение: исправлено в `campaigns_routes.py`, нужна повторная синхронизация кампаний

### Статистика авто-таргетов не показывается
Причина: в `targets_stats` поле `targeting` = "close-match"/"substitutes", а в `campaigns_merch` = "KEYWORDS_CLOSE_MATCH"/"PRODUCT_SUBSTITUTES"
Решение: маппинг в `analytics_routes.py` в функции индексации `tgt_stats`

### Дата окончания кампании не меняется
Причина: Amazon SP API v1 использует поле `endDateTime` в формате ISO 8601 (`2026-06-30T23:59:59Z`)
Решение: исправлено в `send.py` — конвертируем YYYY-MM-DD → ISO 8601

### Marketplace-scoped DELETE при синхронизации
Причина: `TRUNCATE TABLE` удаляет данные для всех маркетплейсов
Решение: `DELETE FROM table WHERE marketplace = 'US'` перед синхронизацией конкретного маркетплейса

### Портфолио dropdown пустой на Products странице
Причина: `/analytics/campaigns/portfolios` зарегистрирован дважды в `analytics_routes.py`
Решение: `products_analytics.html` пробует два endpoint и берёт первый с данными

### Scroll прыгает при раскрытии групп
Причина: изменение `display: none → block` меняет высоту страницы, браузер применяет scroll anchoring
Решение: `html { overflow-anchor: none }` + `grpClick(this)` через `closest()`/`querySelector()` + двойной `requestAnimationFrame`

### SQL алиас конфликт в products_routes.py
Причина: алиас `c` для `campaigns` конфликтовал с `c` для `catalog` в одном запросе
Решение: CTE использует алиас `camp` — `FROM campaigns camp WHERE camp.entity_type = 'campaign'`

### Поисковые запросы пустые в мануальных кампаниях на Products странице
Причина: `search_terms` для мануальных кампаний хранятся в `keyword['search_terms']`, не в `group['search_terms']`
Решение: в JS собирать из `g.search_terms + g.keywords[].search_terms + g.targets[].search_terms`

---

## На горизонте (следующие задачи)

- **Pending changes UI** — страница `/control` для просмотра и одобрения изменений из очереди
- **Search Term Harvesting** — таблица `keyword_queue`, автоматическое добавление новых ключей
- **analyze.py** — автоматический bid optimization loop (минимум 10 кликов за 14 дней, ACOS пороги)
- **Looker Studio** — дашборды для аналитики
- **Retool** — управление через готовый UI