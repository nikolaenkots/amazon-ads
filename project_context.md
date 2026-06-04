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
| `products_routes.py` | `products_bp` | `/analytics/products` — аналитика по рекламируемым ASIN |
| `control_routes.py` | `control_bp` | `/control` — управление рекламой через pending_changes |

### HTML страницы

| Файл | URL | Описание |
|---|---|---|
| `index.html` | `/` | Главная — навигация по всем разделам |
| `campaigns_analytics.html` | `/analytics/campaigns` | Аналитика кампаний с фильтрами, структурой, управлением |
| `products_analytics.html` | `/analytics/products` | Аналитика по рекламируемым ASIN + полное управление кампаниями |
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
├── products_routes.py  → products_bp
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

## Products Analytics HTML (products_analytics.html)

Светлая тема (`--bg: #f4f4f6`). Аналог Amazon Ads Console → Products.

### Функциональность
- Фильтры: Аккаунт (MERCH/KDP), дата от/до, маркетплейс, мультивыбор портфолио, поиск по ASIN
- Числовые фильтры в заголовках колонок (попап `.npop` с операторами `fpToggle/fpApply/fpClear`)
- Сводная статистика: ASIN, Показы, Клики, CTR, Расходы, Продажи 14d, Заказы 14d, ACOS
- Таблица с фото из каталога, названием, статусом, типом, ценой; сортировка, пагинация 50/страница
- Клик по строке → inline-панель кампаний (без перенаправления)
- Клик по кампании → структура групп (Таргеты / Поисковые запросы / Минус слова)

### Хедер кампании (строка кампании)
Прямо в строке кампании встроены:
- **Toggle** state (ENABLED/PAUSED)
- **Название кампании** + карандашик для переименования (появляется при hover над строкой)
- **Бюджет** — inline-редактирование как ставка: кликаешь на значение → появляется поле ввода + ✓/✕, Enter сохраняет
- **Дата окончания** — inline-редактирование: кликаешь → date input + ✓/✕, показывает `∞` если бессрочно
- Бейджи MANUAL/AUTO, ENABLED/PAUSED
- Статистика: Показы · Клики · Расходы · Продажи · Заказы · ACOS · Портфолио
- Стрелка раскрытия структуры

### Структура кампании (после раскрытия)
- **Кнопка + Группа** над списком групп (всегда видна, не в отдельной полосе)
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
grid-template-columns: 1fr 150px 80px 70px 65px 88px 85px 72px
Запрос · Таргет/тип · Показы · Клики · Заказы · Расходы · Продажи · ACOS
```

CSS классы `.ih` / `.ii` и `.ih.st` / `.ii.st` задают сетку только через CSS — без inline `style=` переопределений в шаблоне.

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

### Модал + Группа
Открывается с параметром `targeting_type` кампании (`openCreateGrp(campId, mkt, targetingType)`).
- **AUTO кампания**: Название + Ставка группы + ASIN объявлений
- **MANUAL кампания**: Название + Ставка группы + ASIN объявлений + Ключевые слова (текст + match type + ставка KW)

`submitCreateGrp()` добавляет в очередь одним пакетом:
1. `ad_group_add` — создание группы
2. `product_ad_add` × N — по одному на каждый ASIN объявления
3. `keyword_add` × N — по одному на каждое ключевое слово (только MANUAL)

### Портфолио dropdown
Пробует `/analytics/campaigns/portfolios`, fallback на `/portfolios/list`.

### Фильтрация групп по ASIN
```js
const anyHasAsin = groups.some(g => g.ads.some(a => a.asin === filterAsin));
// MANUAL: показываем только группы с совпадающим ASIN в ads
// AUTO: нет ASIN в ads → показываем группы с clicks > 0
// Если ads есть но asin null → показываем с clicks > 0
```

### Scroll без прыжков
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
409 если уже есть PENDING для этого объекта (кроме типов из NO_DUP_CHECK)

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
| `campaign` | `name` | Переименовать кампанию |
| `campaign` | `daily_budget` | Дневной бюджет |
| `campaign` | `portfolio_id` | Перенести в портфолио |
| `campaign` | `end_date` | Дата окончания (YYYY-MM-DD или пусто) |
| `ad_group` | `state` | ENABLED / PAUSED |
| `ad_group` | `name` | Переименовать группу |
| `ad_group` | `default_bid` | Ставка группы |
| `keyword` | `state` | ENABLED / PAUSED |
| `keyword` | `bid` | Ставка ключевого слова |
| `target` | `state` | ENABLED / PAUSED (авто-таргеты) |
| `target` | `bid` | Ставка авто-таргета |
| `product_ad` | `state` | ENABLED / PAUSED |
| `keyword_add` | `—` | new_value = JSON `{text, match_type, bid, ad_group_id?, ad_group_name?, campaign_id}` |
| `negative_add` | `—` | new_value = JSON `{text, match_type, ad_group_id, campaign_id}` |
| `negative_product_add` | `—` | new_value = JSON `{asin, ad_group_id, campaign_id}` |
| `negative_delete` | `—` | entity_id = keyword_id минус слова |
| `ad_group_add` | `—` | new_value = JSON `{name, default_bid, campaign_id}` |
| `product_ad_add` | `—` | new_value = JSON `{asin, campaign_id, ad_group_id?, ad_group_name?}` |

### NO_DUP_CHECK
Для этих типов проверка дублей по entity_id пропускается (разрешено добавлять несколько в одну группу):
```python
NO_DUP_CHECK = {'keyword_add', 'negative_add', 'negative_product_add', 'ad_group_add', 'product_ad_add'}
```

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

### Форматы SP API v1 (выверены по официальной документации)

**Бюджет кампании:**
```python
{"budgetType": "MONETARY", "recurrenceTimePeriod": "DAILY",
 "budgetValue": {"monetaryBudgetValue": {
   "monetaryBudget": {"value": float(val)},
   "marketplaceSettings": [{"marketplace": mkt_code, "monetaryBudget": {"value": float(val)}}]
 }}}
```

**Дата окончания** — с timezone offset по маркетплейсу чтобы совпадало с консолью Amazon:
```python
MKT_OFFSET = {
    "US": -5, "CA": -5, "MX": -6,
    "UK": 0,  "GB": 0,
    "DE": 1,  "FR": 1, "IT": 1, "ES": 1, "NL": 1, "BE": 1, "PL": 1, "SE": 1,
    "TR": 3,  "AU": 10, "JP": 9, "IN": 5, "SG": 8, "AE": 4, "SA": 3, "BR": -3,
}
offset = MKT_OFFSET.get(mkt_code, 0)
sign = "+" if offset >= 0 else "-"
item["endDateTime"] = f"{val}T23:59:59{sign}{abs(offset):02d}:00"
# Пример для US: "2026-06-30T23:59:59-05:00"
# Пример для DE: "2026-06-30T23:59:59+01:00"
```

**Ставка ключевого слова/таргета (update/targets):**
```python
MKT_CURRENCY = {
    "US":"USD","CA":"CAD","UK":"GBP","GB":"GBP",
    "DE":"EUR","FR":"EUR","IT":"EUR","ES":"EUR","NL":"EUR",
    "AU":"AUD","JP":"JPY","IN":"INR","MX":"MXN","BR":"BRL",
}
item["bid"] = {"bid": float(val), "currencyCode": currency}
```

**Создание ключевого слова (keyword_add):**
```python
{
    "adGroupId": ag_id, "campaignId": camp_id,
    "adProduct": "SPONSORED_PRODUCTS",
    "negative": False, "state": "ENABLED", "targetType": "KEYWORD",
    "targetDetails": {"keywordTarget": {"matchType": "BROAD", "keyword": "pirate shirt"}},
    "bid": {"bid": 0.5, "currencyCode": "USD"}  # опционально
}
```

**Создание минус-слова (negative_add):**
```python
# matchType БЕЗ префикса NEGATIVE_: EXACT/PHRASE/BROAD (не NEGATIVE_EXACT/NEGATIVE_PHRASE)
# флаг негативности передаётся через "negative": True, не через matchType
raw_mt = val.get("match_type", "NEGATIVE_EXACT")
mt = raw_mt.replace("NEGATIVE_", "")  # "NEGATIVE_EXACT" → "EXACT"
{
    "adGroupId": ag_id, "campaignId": camp_id,
    "adProduct": "SPONSORED_PRODUCTS",
    "negative": True, "state": "ENABLED", "targetType": "KEYWORD",
    "targetDetails": {"keywordTarget": {"matchType": mt, "keyword": val["text"]}}
}
```

**Создание минус-ASIN (negative_product_add):**
```python
{
    "adGroupId": ag_id, "campaignId": camp_id,
    "adProduct": "SPONSORED_PRODUCTS",
    "negative": True, "state": "ENABLED", "targetType": "PRODUCT",
    "targetDetails": {"productTarget": {
        "matchType": "PRODUCT_EXACT",  # enum: PRODUCT_EXACT, PRODUCT_SIMILAR
        "productIdType": "ASIN",       # обязательно на уровне productTarget
        "product": {
            "productId": val["asin"],
            "productIdType": "ASIN"    # и внутри product тоже
        }
    }}
}
```

**Создание группы объявлений (ad_group_add):**
```python
{
    "campaignId": camp_id, "adProduct": "SPONSORED_PRODUCTS",
    "name": val["name"], "state": "ENABLED",
    "bid": {"defaultBid": float(val.get("default_bid", 0.5))}
}
```

**Создание объявления (product_ad_add):**
```python
{
    "adGroupId": ag_id, "adProduct": "SPONSORED_PRODUCTS",
    "adType": "PRODUCT_AD", "state": "ENABLED",
    "creative": {"productCreative": {"productCreativeSettings": {
        "advertisedProduct": {"productId": val["asin"], "productIdType": "ASIN"}
    }}}
}
```

### Мёрдж изменений одной кампании в один payload
`send_update_campaigns` группирует несколько записей pending_changes для одной кампании
(state + budget + end_date) в единый payload — иначе Amazon возвращает `DUPLICATE_RESOURCE_ID_FOUND`.
Использует `idx_map` для маппинга результатов обратно на оригинальные индексы.
```python
merged = {}  # campaign_id → {item: {campaignId:...}, indices: [...], mkt: "US"}
# После отправки:
for batch_idx, orig_indices in idx_map.items():
    for orig_i in orig_indices:
        results[orig_i] = merged_results.get(batch_idx, "SUCCESS")
```

### Bulk Sheet логика для создания группы (send_create_ad_groups)
Все `ad_group_add`, `keyword_add` (с `ad_group_name`), `product_ad_add` роутятся в одну очередь `create_ad_groups`.
Функция выполняет 3 шага:

**Шаг 1:** создаёт группы (`ad_group_add`) → берёт `adGroupId` из `success[].adGroup.adGroupId` по имени группы:
```python
for item in rj.get("success", []):
    ag = item.get("adGroup", {})
    ag_name_to_id[ag.get("name")] = ag.get("adGroupId")
```

**Шаг 2:** создаёт ключевые слова (`keyword_add`) — подставляет `adGroupId` по `ad_group_name`:
```python
ag_id = ag_name_to_id.get(val.get("ad_group_name")) or val.get("ad_group_id", "")
```

**Шаг 3:** создаёт объявления (`product_ad_add`) — аналогично подставляет `adGroupId`.

`keyword_add` с `ad_group_name` (без `ad_group_id`) → роутится в `create_ad_groups`.
`keyword_add` с `ad_group_id` (стандартное добавление KW) → роутится в `create_targets`.

### parse_multi_response
SP API v1 возвращает структуру `{"success": [...], "error": [...], "partialSuccess": [...]}`.
Старый код смотрел в `data.get(key)` = `data.get("targets")` которого нет → все SUCCESS по умолчанию.
Исправлено: читаем все три секции:
```python
for item in data.get("success", []):
    results[item.get("index", 0)] = "SUCCESS"
for item in data.get("error", []):
    idx = item.get("index", 0)
    errs = item.get("errors", [{}])
    msg = "; ".join(f"{e.get('code','')}: {e.get('message','')}" for e in errs)
    results[idx] = msg or "UNKNOWN_ERROR"
```

---

## campaigns_routes.py

### _dt_to_date(dt_str, marketplace)
Конвертирует ISO datetime → дату в локальном времени маркетплейса.
Amazon Console показывает даты в local time, API хранит в UTC.

```python
MKT_OFFSET = {"US":-5,"CA":-5,"MX":-6,"UK":0,"GB":0,
              "DE":1,"FR":1,"IT":1,"ES":1,"NL":1,"BE":1,"PL":1,"SE":1,
              "TR":3,"AU":10,"JP":9,"IN":5,"SG":8,"AE":4,"SA":3,"BR":-3}
offset_h = MKT_OFFSET.get((marketplace or "US").upper(), 0)
s = dt_str.replace("Z", "+00:00")
dt = datetime.fromisoformat(s)
local_dt = dt + timedelta(hours=offset_h)
return local_dt.strftime("%Y-%m-%d")
# Пример: "2026-07-01T04:59:59Z" + marketplace="US" → "2026-06-30"
```

Вызовы: `_dt_to_date(c.get("startDateTime"), marketplace)` — передаём marketplace.

### Синхронизация кампаний
- `DELETE FROM campaigns_merch WHERE marketplace = 'US'` — перед вставкой (только по маркетплейсу)
- Данные статистики (`targets_stats`, `asin_stats`, `search_terms`) не затрагиваются
- Исторические данные статистики хранятся в BigQuery навсегда (Amazon хранит 95 дней, мы — бессрочно)

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

### JS ошибка "h is not defined" в buildStruct
Симптом: структура кампании не открывается, "Ошибка: h is not defined"
Причина: код `h +=` используется до объявления `let h = ''` в функции `buildStruct`
Решение: добавить `let h = '';` перед первым использованием `h +=`

### JS ошибка на странице аналитики
Симптом: кнопка "Применить" не работает, в DevTools `applyFilters is not defined`
Причина: синтаксическая ошибка в JS (незакрытые template literals, кавычки внутри строк)
Решение: проверить через `node -e "try{new Function(js)}catch(e){console.log(e.message)}"` после извлечения JS из HTML

### BigQuery "Aggregations of aggregations are not allowed"
Причина: `SUM()`, `ROUND(SUM())`, `COALESCE(SUM())` или оконные функции поверх CTE с GROUP BY
Решение: убрать ROUND/COALESCE из агрегатов в SQL, вынести HAVING в WHERE внешнего запроса,
считать CTR/ACOS в Python после получения данных

### Amazon SP API v1 — DUPLICATE_RESOURCE_ID_FOUND
Симптом: при отправке нескольких изменений одной кампании (state + budget + end_date)
Причина: несколько объектов `{"campaignId": "X", ...}` с одинаковым campaignId в одном батче
Решение: `send_update_campaigns` мёрджит все изменения одной кампании в один payload

### Amazon SP API v1 — ACTION_NOT_SUPPORTED: Ended campaign cannot be updated without endDate extension
Причина: нельзя менять state/budget завершённой кампании без одновременного продления даты
Решение: мёрдж state/budget + end_date в один payload решает проблему

### Amazon SP API v1 — matchType для негативных ключевых слов
Симптом: ошибка "instance value (NEGATIVE_PHRASE) not found in enum (possible values: [EXACT, PHRASE, BROAD])"
Причина: API не принимает matchType с префиксом NEGATIVE_
Решение: `raw_mt.replace("NEGATIVE_", "")` перед отправкой, флаг через `"negative": True`

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

### Дата окончания на 1 день больше чем в консоли Amazon
Причина: при отправке `T23:59:59Z` (UTC) для US профиля → Amazon хранит как `2026-07-01T04:59:59Z`
→ при чтении `[:10]` даёт `2026-07-01` вместо `2026-06-30`
Решение:
1. Отправка с timezone offset: `T23:59:59-05:00` для US (не UTC)
2. Чтение через `_dt_to_date(dt_str, marketplace)` с конвертацией UTC → local time

### NameError: name 'c' is not defined в send.py
Причина: в `send_update_campaigns` используется `c.get("marketplace")` но цикл называет переменную `change`
Решение: везде использовать `change.get(...)` — переменная `mkt_code` уже определена из `change.get("marketplace")`

### Негативные ASIN таргеты показывают PRODUCT_EXACT вместо ASIN
Причина: ASIN хранится в `targetDetails.productTarget.product.productId`, не в `productTarget.productId`
Решение: исправлено в `campaigns_routes.py`, нужна повторная синхронизация кампаний

### Статистика авто-таргетов не показывается
Причина: в `targets_stats` поле `targeting` = "close-match"/"substitutes", а в `campaigns_merch` = "KEYWORDS_CLOSE_MATCH"/"PRODUCT_SUBSTITUTES"
Решение: маппинг в `analytics_routes.py` в функции индексации `tgt_stats`

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

- **analyze.py** — автоматический bid optimization loop (минимум 10 кликов за 14 дней, ACOS пороги)
- **Search Term Harvesting** — таблица `keyword_queue`, автоматическое добавление новых ключей из search terms
- **Looker Studio** — дашборды для аналитики
- **Retool** — управление через готовый UI