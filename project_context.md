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
| **Retool** | Интерфейс управления ставками | — |
| **Looker Studio** | Дашборды — реклама vs продажи, ACOS | — |
| **Amazon Ads API** | Reporting v3, SP API v1 | OAuth2, secrets в `~/amazon-ads/config/` |

---

## Файлы на сервере (~/amazon-ads/)

| Файл | Статус | Описание |
|---|---|---|
| `app.py` | ✅ Готов | Flask сервер — веб-интерфейс каталога, продаж, рекламы |
| `collect.py` | ✅ Готов | Сбор статистики из Amazon Ads API через CLI |
| `ads.html` | ✅ Готов | Страница сбора рекламной статистики — очередь отчётов |
| `catalog.html` | ✅ Готов | Страница каталога |
| `earnings.html` | ✅ Готов | Страница продаж |
| `index.html` | ✅ Готов | Главная страница |
| `reports_log.json` | ✅ Активный | Лог очереди отчётов Amazon Ads |
| `config/amazon_secrets.json` | ✅ Есть | Amazon Ads API ключи и профили |
| `config/bigquery_key.json` | ✅ Есть | Ключ сервисного аккаунта Google Cloud |
| `analyze.py` | 🔲 Не создан | Анализ ставок, запись в pending_changes |
| `send.py` | 🔲 Не создан | Отправка одобренных ставок в Amazon |

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

### SP API (управление ставками)
```
POST https://{endpoint}/adsApi/v1/query/campaigns   → справочник кампаний
POST https://{endpoint}/adsApi/v1/query/adGroups    → справочник групп
POST https://{endpoint}/adsApi/v1/query/targets     → справочник таргетов
POST https://{endpoint}/adsApi/v1/update/targets    → обновление ставок
```

---

## Структура БД BigQuery (dataset: amazon_ads)

### catalog ✅ ГОТОВА
```sql
listing_id        STRING NOT NULL  -- уникальный ключ (design_id_PRODUCTTYPE_MARKETPLACE)
asin              STRING NOT NULL
marketplace       STRING NOT NULL  -- US, DE, UK, FR...
design_id         STRING
brand             STRING
title             STRING
product_type      STRING           -- STANDARD_T_SHIRT, ZIP_HOODIE...
price             FLOAT64
status            STRING           -- PUBLISHED, DRAFT, REMOVED
bullet_point_1    STRING
bullet_point_2    STRING
ad_asin           STRING           -- ASIN для рекламы (только для STANDARD_T_SHIRT)
tags              STRING           -- теги через запятую: "cats, vintage, funny"
image_url         STRING
live_url          STRING
edit_url          STRING
created_at_amazon TIMESTAMP
imported_at       TIMESTAMP
```
CLUSTER BY: marketplace, product_type, status

### catalog_staging ✅ ГОТОВА
Та же структура что catalog, без поля tags.
Используется при импорте CSV: DROP → CREATE → INSERT → MERGE → DROP

### earning ✅ ГОТОВА
```sql
marketplace       STRING
asin              STRING
title             STRING
category_1        STRING
category_2        STRING
category_3        STRING
product_type      STRING
brand_name        STRING
transaction_type  STRING
sale_price        FLOAT64
earnings          FLOAT64
currency          STRING
quantity          INT64
earning_date      STRING
```

### targets_stats_merch ✅ ГОТОВА — 1.38M строк, 305 MB
```sql
date                           DATE    NOT NULL
profile_id                     STRING  NOT NULL
marketplace                    STRING  NOT NULL
campaign_id                    STRING  NOT NULL
ad_group_id                    STRING  NOT NULL
keyword_id                     STRING
keyword                        STRING           -- текст для BROAD/PHRASE/EXACT
keyword_type                   STRING           -- BROAD/PHRASE/EXACT/TARGETING_EXPRESSION_PREDEFINED
targeting                      STRING           -- close-match/substitutes/... для авто
ad_keyword_status              STRING           -- ENABLED/PAUSED/ARCHIVED
impressions                    INT64
clicks                         INT64
cost                           FLOAT64
top_of_search_impression_share FLOAT64
purchases_1d                   INT64
purchases_7d                   INT64
purchases_14d                  INT64
sales_1d                       FLOAT64
sales_7d                       FLOAT64
sales_14d                      FLOAT64
units_1d                       INT64
units_7d                       INT64
units_14d                      INT64
loaded_at                      TIMESTAMP
```
PARTITION BY date, CLUSTER BY marketplace, campaign_id, keyword_type

### targets_stats_kdp ✅ ГОТОВА
Идентичная структура с targets_stats_merch.

### asin_stats_merch ✅ ГОТОВА
```sql
date                DATE    NOT NULL
profile_id          STRING  NOT NULL
marketplace         STRING  NOT NULL
campaign_id         STRING  NOT NULL
ad_group_id         STRING  NOT NULL
advertised_asin     STRING  NOT NULL
advertised_sku      STRING
impressions         INT64
clicks              INT64
cost                FLOAT64
purchases_1d        INT64
purchases_7d        INT64
purchases_14d       INT64
sales_1d            FLOAT64
sales_7d            FLOAT64
sales_14d           FLOAT64
units_1d            INT64
units_7d            INT64
units_14d           INT64
loaded_at           TIMESTAMP
```
PARTITION BY date, CLUSTER BY marketplace, advertised_asin, campaign_id

### asin_stats_kdp ✅ ГОТОВА
Идентичная структура с asin_stats_merch.

### search_terms_merch ✅ ГОТОВА
```sql
date                DATE    NOT NULL
profile_id          STRING  NOT NULL
marketplace         STRING  NOT NULL
campaign_id         STRING  NOT NULL
ad_group_id         STRING  NOT NULL
keyword_id          STRING
keyword             STRING
keyword_type        STRING
targeting           STRING
match_type          STRING
search_term         STRING  NOT NULL  -- реальный запрос покупателя
impressions         INT64
clicks              INT64
cost                FLOAT64
purchases_1d        INT64
purchases_7d        INT64
purchases_14d       INT64
sales_1d            FLOAT64
sales_7d            FLOAT64
sales_14d           FLOAT64
units_1d            INT64
units_7d            INT64
units_14d           INT64
loaded_at           TIMESTAMP
```
PARTITION BY date, CLUSTER BY marketplace, search_term, campaign_id

### search_terms_kdp ✅ ГОТОВА
Идентичная структура с search_terms_merch.

### pending_changes 🔲 НЕ СОЗДАНА
```sql
id              STRING  NOT NULL
profile_id      STRING
marketplace     STRING
account_type    STRING           -- MERCH / KDP
campaign_id     STRING
ad_group_id     STRING           -- нужен для API запроса
keyword_id      STRING           -- для keyword таргетов
target_id       STRING           -- для авто таргетов
keyword         STRING
keyword_type    STRING
targeting       STRING
old_bid         FLOAT64
new_bid         FLOAT64
change_pct      FLOAT64
reason          STRING           -- high_acos / low_acos_high_cvr / no_sales
window_days     INT64            -- за сколько дней считалось
window_clicks   INT64
window_acos     FLOAT64
window_cvr      FLOAT64
source          STRING           -- auto / manual
status          STRING           -- pending / approved / rejected
created_at      TIMESTAMP
reviewed_at     TIMESTAMP
reviewed_by     STRING
```

### bid_changes_log 🔲 НЕ СОЗДАНА
```sql
id              STRING  NOT NULL
profile_id      STRING
marketplace     STRING
account_type    STRING
campaign_id     STRING
ad_group_id     STRING
keyword_id      STRING
target_id       STRING
keyword         STRING
keyword_type    STRING
targeting       STRING
old_bid         FLOAT64
new_bid         FLOAT64
change_pct      FLOAT64
reason          STRING
source          STRING
status          STRING           -- sent / failed
error_message   STRING
api_response    STRING           -- сырой JSON от Amazon
created_at      TIMESTAMP
sent_at         TIMESTAMP
```
PARTITION BY DATE(created_at)

---

## Логика импорта каталога

CSV формат — экспорт из расширения Productor для Chrome через IndexedDB скрипт (см. ниже).

### Порядок колонок в актуальном CSV (Productor, май 2026)
```
col[0]  asin
col[1]  brandName
col[2]  createdDate        (Unix timestamp)
col[3]  currencyCode
col[4]  deleteReasonType
col[5]  designId
col[6]  listPrice
col[7]  listingId
col[8]  lockReasonType
col[9]  marketplace
col[10] productImageUrn
col[11] productTitle
col[12] productType
col[13] searchableOnRetail
col[14] status
col[15] updatedDate
col[16] pm_data            (JSON: буллиты, картинки, продажи, BSR...)
col[17] estimatedExpirationDate
```

⚠️ Парсер (`process_catalog_row`) читает колонки **по именам из заголовка**, а не по индексам —
изменение порядка колонок в Productor не сломает импорт.

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
    // Порядок колонок соответствует актуальному формату (май 2026)
    const keys = [
      "asin", "brandName", "createdDate", "currencyCode", "deleteReasonType",
      "designId", "listPrice", "listingId", "lockReasonType", "marketplace",
      "productImageUrn", "productTitle", "productType", "searchableOnRetail",
      "status", "updatedDate", "pm_data", "estimatedExpirationDate"
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
при импорте — это ожидаемое поведение. После того как Amazon присвоит ASIN, следующий импорт
добавит их через MERGE.

### Процесс обновления (MERGE):
1. DROP + CREATE catalog_staging
2. Чтение CSV через `csv.reader(f, newline='')` — корректная обработка многострочных полей
3. `build_catalog_col_idx(header)` — маппинг по именам колонок из заголовка
4. INSERT данные в staging чанками по 1000 строк
5. MERGE staging → catalog (по `listing_id`, поле `tags` не перезаписывается)
6. DROP catalog_staging (очистка)

---

## Логика сбора рекламной статистики

### Через веб-интерфейс (ads.html)
1. Выбор аккаунта (MERCH/KDP) и маркетплейса
2. Выбор типа отчёта (spTargeting / spAdvertisedProduct / spSearchTerm)
3. Выбор периода (макс 31 день)
4. POST /ads/create_report → создаёт отчёт в Amazon, пишет в reports_log.json
5. POST /ads/refresh_statuses → проверяет статус всех PENDING отчётов
6. POST /ads/download_report → скачивает файл с S3 (~5 сек)
7. POST /ads/upload_to_bq → загружает в BQ в фоновом потоке с прогрессом

### Через CLI (collect.py)
```bash
python3 collect.py 2026-04-27                       # Merch US
python3 collect.py 2026-04-01 2026-04-27 MERCH US   # период
python3 collect.py 2026-04-27 2026-04-27 KDP UK     # KDP UK
python3 collect.py 2026-04-27 all                   # все профили
```

### Ограничения API
- Отчёт за один день: ~21k строк, ~600 KB
- Отчёт за 30 дней: ~630k строк, ~18 MB
- Amazon хранит данные 95 дней
- Attribution restatement: данные пересчитываются до 14 дней назад
- Один запрос к API — макс 31 день

---

## Правила изменения ставок (бизнес-логика, планируется)

- Минимум 10 кликов за 14 дней для принятия решения
- ACOS > 40% и CVR < 1% → снизить ставку на 20%
- ACOS < 15% и CVR > 3% → повысить ставку на 15%
- Иначе → не трогать
- Все изменения сначала в pending_changes, отправка только после одобрения

### Связь таблиц для анализа ставок
```
targets_stats (keyword_id) 
    → JOIN targets справочник (через SP API /query/targets)
    → получаем target_id для обновления ставки
    → POST /adsApi/v1/update/targets
```

При структуре 1 группа = 1 ASIN можно джойнить через ad_group_id:
```sql
SELECT t.keyword, a.advertised_asin, SUM(t.clicks), SUM(t.sales_14d)
FROM targets_stats_merch t
JOIN asin_stats_merch a ON t.ad_group_id = a.ad_group_id AND t.date = a.date
GROUP BY 1, 2
```

---

## GitHub репозиторий

Репо: `https://github.com/nikolaenkots/amazon-ads` (приватное)
Ветка: `master`

### Синхронизация изменений с сервера на GitHub
После любых правок на PythonAnywhere:
```bash
cd ~/amazon-ads
git add .
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
