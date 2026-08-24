import json
import os
import tempfile
import time

from google.cloud import bigquery

_client = None

def get_client():
    global _client
    if _client is None:
        _client = bigquery.Client(project='amazon-ads-api-494412')
    return _client


# ── Загрузка данных ───────────────────────────────────────
# BigQuery ограничивает частоту операций над одной таблицей (примерно 5 за
# 10 секунд, location: table.write). Загрузка чанками по 50k пачками по 5
# упиралась в этот лимит на больших аккаунтах: синхронизация 532k строк
# падала с 429 rateLimitExceeded посреди записи. Поэтому данные пишутся в
# NDJSON-файл и загружаются ОДНИМ job — одна операция вместо десятка,
# а память не удваивается копией JSON в RAM.

RETRY_PAUSES = (10, 30, 60, 120)   # паузы между попытками


def _is_rate_limit(err):
    text = str(err).lower()
    return '429' in text or 'ratelimitexceeded' in text or 'rate limits' in text


def _is_conflict(err):
    """Параллельная запись в ту же таблицу.

    BigQuery выполняет UPDATE/DELETE по одной таблице последовательно и, если
    другое задание успело изменить её, отвечает «Could not serialize access ...
    due to concurrent update». Это не ошибка данных — операцию нужно повторить.
    """
    text = str(err).lower()
    return 'concurrent update' in text or 'could not serialize' in text


def with_retry(fn, on_retry=None):
    """Выполнить операцию BigQuery, переживая лимит частоты и конфликт записи."""
    last = None
    for attempt, pause in enumerate((0,) + RETRY_PAUSES):
        if pause:
            if on_retry:
                on_retry(f"BigQuery занят, пауза {pause}с и повтор...")
            time.sleep(pause)
        try:
            return fn()
        except Exception as e:
            last = e
            if not (_is_rate_limit(e) or _is_conflict(e)) or attempt == len(RETRY_PAUSES):
                raise
    raise last


def load_rows(rows, table, progress=None, write_disposition="WRITE_APPEND"):
    """Загрузить строки в таблицу одним заданием BigQuery.

    rows      — список словарей
    table     — полное имя таблицы
    progress  — callable(done, total, msg) для отображения хода
    Возвращает число загруженных строк.
    """
    if not rows:
        return 0

    client = get_client()
    total  = len(rows)
    tmp    = tempfile.NamedTemporaryFile('w', suffix='.ndjson', delete=False,
                                         encoding='utf-8')
    try:
        # пишем построчно: файл не держим в памяти целиком
        for i, row in enumerate(rows, 1):
            tmp.write(json.dumps(row, ensure_ascii=False, default=str))
            tmp.write('\n')
            if progress and (i % 50_000 == 0 or i == total):
                progress(i, total, f"Подготовлено {i:,}/{total:,} строк".replace(',', ' '))
        tmp.close()

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=write_disposition,
        )
        if progress:
            progress(total, total, f"Загружаем {total:,} строк в BigQuery...".replace(',', ' '))

        def _run():
            with open(tmp.name, 'rb') as fh:
                job = client.load_table_from_file(fh, table, job_config=job_config)
            job.result()
            if job.errors:
                raise RuntimeError(f"BQ ошибки: {job.errors}")
            return job

        with_retry(_run, on_retry=(lambda m: progress(total, total, m)) if progress else None)
        return total
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


def run_query(sql, progress=None):
    """Выполнить запрос (DELETE и т.п.), переживая лимит частоты операций."""
    client = get_client()
    return with_retry(lambda: client.query(sql).result(),
                      on_retry=(lambda m: progress(0, 0, m)) if progress else None)
