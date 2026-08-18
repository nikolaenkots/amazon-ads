# -*- coding: utf-8 -*-
"""Загрузка в BigQuery: одно задание вместо пачки и переживание лимита 429.

Причина появления: синхронизация 532k строк падала на середине с
429 rateLimitExceeded (too many table update operations for this table),
потому что данные грузились 11 заданиями пачками по 5 — а BigQuery
ограничивает частоту операций над одной таблицей.
"""
import os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/dev/null"

import bq_client


class FakeJob:
    errors = None
    def result(self): return None


class FakeBQ:
    """Считает задания и умеет отвечать 429 заданное число раз."""
    def __init__(self, fail_times=0):
        self.loads = []
        self.queries = []
        self.fail_times = fail_times
    def load_table_from_file(self, fh, table, job_config=None):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise Exception("429 Exceeded rate limits: too many table update "
                            "operations for this table; reason: rateLimitExceeded")
        rows = sum(1 for line in fh if line.strip())
        self.loads.append((table, rows))
        return FakeJob()
    def query(self, sql):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise Exception("429 rateLimitExceeded")
        self.queries.append(sql)
        return FakeJob()


bq_client.time.sleep = lambda s: None      # не ждать паузы в тесте
TABLE = "proj.ds.table"
ROWS  = [{"id": i, "name": f"строка {i}", "value": i * 1.5} for i in range(120_000)]


# ── 1. Большая загрузка — ровно одно задание ──────────────
bq_client._client = fake = FakeBQ()
seen = []
n = bq_client.load_rows(ROWS, TABLE, progress=lambda d, t, m: seen.append(m))
print(f"строк загружено: {n}, заданий BigQuery: {len(fake.loads)}")
assert n == len(ROWS)
assert len(fake.loads) == 1, f"должно быть одно задание, а было {len(fake.loads)}"
assert fake.loads[0] == (TABLE, len(ROWS))
assert seen, "прогресс должен сообщаться"
print("  ✓ 120 000 строк ушли одним заданием (раньше было бы 3 задания)")

# ── 2. Лимит 429 — повтор, а не падение ───────────────────
bq_client._client = fake = FakeBQ(fail_times=2)
msgs = []
n = bq_client.load_rows(ROWS[:10], TABLE, progress=lambda d, t, m: msgs.append(m))
assert n == 10 and len(fake.loads) == 1
assert any("лимит операций" in m for m in msgs), msgs
print(f"  ✓ после двух отказов 429 загрузка прошла, повторов: "
      f"{sum(1 for m in msgs if 'повтор' in m)}")

# ── 3. DELETE тоже переживает 429 ─────────────────────────
bq_client._client = fake = FakeBQ(fail_times=1)
bq_client.run_query(f"DELETE FROM `{TABLE}` WHERE marketplace = 'US'")
assert len(fake.queries) == 1
print("  ✓ DELETE выполнен после повтора")

# ── 4. Не-429 ошибка пробрасывается сразу ─────────────────
class BadBQ(FakeBQ):
    def load_table_from_file(self, fh, table, job_config=None):
        raise Exception("400 Invalid schema: no such field")

bq_client._client = BadBQ()
try:
    bq_client.load_rows(ROWS[:5], TABLE)
    raise AssertionError("ошибка схемы не должна проглатываться")
except Exception as e:
    assert "Invalid schema" in str(e), e
print("  ✓ обычная ошибка не маскируется повторами")

# ── 5. Пустой список — без обращения к BigQuery ───────────
bq_client._client = fake = FakeBQ()
assert bq_client.load_rows([], TABLE) == 0
assert not fake.loads
print("  ✓ пустой список не создаёт задание")

# временные файлы не остаются
import glob, tempfile
leftovers = glob.glob(os.path.join(tempfile.gettempdir(), '*.ndjson'))
assert not leftovers, f"остались временные файлы: {leftovers}"
print("  ✓ временные файлы удалены")

print("\n=== ВСЕ ПРОВЕРКИ ПРОШЛИ ===")
