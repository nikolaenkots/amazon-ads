# Вторая установка на Google Cloud VM

Инструкция для копии системы на своём проекте Google и своём аккаунте Amazon Ads
(например, VM `margoads` в зоне `us-central1-a`). Исходная установка на
PythonAnywhere при этом продолжает работать: код у них общий, различия — только
в `config/`.

Что должно получиться: та же панель на своём домене или IP, своя BigQuery, свои
ключи Amazon, свои задачи по расписанию.

---

## 1. Проект Google и BigQuery

```bash
# в Cloud Shell или локально с gcloud
gcloud config set project <НОВЫЙ_ПРОЕКТ>
gcloud services enable bigquery.googleapis.com
```

Сервис-аккаунт для VM (или воспользуйтесь тем, что уже привязан к машине):

```bash
gcloud iam service-accounts create amazon-ads --display-name "Amazon Ads app"
gcloud projects add-iam-policy-binding <НОВЫЙ_ПРОЕКТ> \
  --member "serviceAccount:amazon-ads@<НОВЫЙ_ПРОЕКТ>.iam.gserviceaccount.com" \
  --role roles/bigquery.dataEditor
gcloud projects add-iam-policy-binding <НОВЫЙ_ПРОЕКТ> \
  --member "serviceAccount:amazon-ads@<НОВЫЙ_ПРОЕКТ>.iam.gserviceaccount.com" \
  --role roles/bigquery.jobUser
```

На Google Cloud VM файл ключа не нужен: приложение возьмёт сервис-аккаунт самой
машины. Привяжите его при создании VM или командой
`gcloud compute instances set-service-account margoads --zone us-central1-a
--service-account amazon-ads@<НОВЫЙ_ПРОЕКТ>.iam.gserviceaccount.com
--scopes cloud-platform`.

---

## 2. Код на машине

```bash
gcloud compute ssh margoads --zone us-central1-a

sudo apt update && sudo apt install -y python3-venv python3-pip nginx git
sudo useradd -m -s /bin/bash app || true
sudo mkdir -p /opt/amazon-ads && sudo chown app:app /opt/amazon-ads

sudo -u app -H bash -lc '
  git clone <URL_РЕПОЗИТОРИЯ> /opt/amazon-ads
  cd /opt/amazon-ads
  python3 -m venv venv
  venv/bin/pip install -U pip
  venv/bin/pip install -r requirements.txt gunicorn
  mkdir -p logs uploads config
'
```

---

## 3. Настройки установки

Весь «характер» установки — в `config/`, этой папки нет в git:

```bash
sudo -u app tee /opt/amazon-ads/config/settings.json > /dev/null <<'JSON'
{
  "project_id": "<НОВЫЙ_ПРОЕКТ>",
  "dataset":    "amazon_ads",
  "site_name":  "Margo Ads",
  "auth": {"username": "<логин>", "password": "<пароль>"}
}
JSON
```

Туда же — `config/amazon_secrets.json` с ключами своего аккаунта Amazon Ads
(`client_id`, `client_secret`, `refresh_token` и список `profiles` с их
`id`, `type`, `marketplace`; для европейских профилей — `api_endpoint`
`https://advertising-api-eu.amazon.com`). Формат тот же, что на первой
установке.

Любую настройку можно задать и переменной окружения — они имеют приоритет:
`AMZADS_PROJECT_ID`, `AMZADS_DATASET`, `AMZADS_USER`, `AMZADS_PASSWORD`,
`AMZADS_KEY_FILE`, `AMZADS_SECRETS_FILE`, `AMZADS_SITE_NAME`.

---

## 4. Таблицы в новой BigQuery

Схемы копируются из рабочего проекта, данные не переносятся:

```bash
cd /opt/amazon-ads
sudo -u app venv/bin/python scripts/init_bigquery.py --from amazon-ads-api-494412 --dry-run
sudo -u app venv/bin/python scripts/init_bigquery.py --from amazon-ads-api-494412
```

Если справочники хочется взять готовыми (каталог товаров, имена портфолио):

```bash
sudo -u app venv/bin/python scripts/init_bigquery.py \
  --from amazon-ads-api-494412 --copy catalog,portfolio_labels
```

Для чтения исходного проекта аккаунту нужны права `bigquery.dataViewer` на нём.
Если доступа нет — создайте таблицы в старом проекте вручную или запустите
скрипт из-под аккаунта, у которого есть оба доступа.

---

## 5. Запуск как сервиса

```bash
sudo cp /opt/amazon-ads/deploy/amazon-ads.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now amazon-ads
sudo systemctl status amazon-ads --no-pager

sudo cp /opt/amazon-ads/deploy/nginx.conf /etc/nginx/sites-available/amazon-ads
sudo ln -sf /etc/nginx/sites-available/amazon-ads /etc/nginx/sites-enabled/amazon-ads
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Открыть 80-й порт в фаерволе (один раз на проект):

```bash
gcloud compute firewall-rules create allow-http --allow tcp:80 --target-tags http-server
gcloud compute instances add-tags margoads --zone us-central1-a --tags http-server
```

После этого панель доступна по внешнему IP машины. Интерфейс закрыт Basic-авторизацией
из `settings.json`, но по HTTP пароль идёт в открытом виде — как только появится
домен, включите HTTPS:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d ads.example.com
```

---

## 6. Задачи по расписанию

```bash
sudo -u app crontab /opt/amazon-ads/deploy/crontab.txt
sudo -u app crontab -l
```

Время в cron — UTC. Проверить, что задачи действительно отработали, можно на
самой панели: «Импорт рекламы» и «Кампании SP API» показывают историю запусков,
а на главной под сводкой видно время последней загрузки.

---

## 7. Обновление кода

```bash
sudo -u app -H bash -lc 'cd /opt/amazon-ads && git pull'
sudo systemctl restart amazon-ads
```

`config/` не перезаписывается — настройки установки остаются на месте.

---

## Проверка после установки

1. `curl -u <логин>:<пароль> http://<IP>/assets-check` — приложение видит файлы оформления.
2. Открыть главную: сводка по портфолио отдаёт пустую таблицу, а не ошибку
   (данных ещё нет, но таблицы есть).
3. «Кампании SP API» → синхронизация одного гео: проверяет ключи Amazon и запись в BigQuery.
4. «Импорт рекламы» → отчёт за 3 дня: проверяет загрузку статистики.
5. Только потом включать cron на все гео.
