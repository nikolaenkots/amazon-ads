# -*- coding: utf-8 -*-
"""Мок-тест автосинхронизации кампаний: Amazon API и BigQuery подменены фейками.

Сценарии:
  1. обычная синхронизация двух профилей → OK, DELETE + загрузка
  2. API вернул 0 объектов, а в базе есть данные → EMPTY, DELETE НЕ выполняется
  3. ошибка API у одного профиля → ERROR, остальные профили обрабатываются
Плюс проверка endpoint GET /campaigns/history.
"""
import json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/dev/null"

import data_import.campaigns_routes as cr
import scripts.auto_sync_campaigns as auto_sync_campaigns


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.text = json.dumps(payload)
    def json(self): return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}: {self.text}")


CAMPAIGN = {"campaignId": "111", "name": "Test Camp", "state": "ENABLED",
            "budgets": [{"budgetValue": {"monetaryBudgetValue": {"monetaryBudget": {"value": 5.0}}}}],
            "optimizations": {"bidSettings": {"bidStrategy": "LEGACY_FOR_SALES"}},
            "autoCreationSettings": {"autoCreateTargets": True},
            "startDateTime": "2026-01-01T00:00:00Z"}
AD_GROUP = {"adGroupId": "222", "campaignId": "111", "name": "Grp", "state": "ENABLED",
            "bid": {"defaultBid": 0.5}}
TARGET   = {"targetId": "333", "campaignId": "111", "adGroupId": "222", "targetType": "KEYWORD",
            "state": "ENABLED", "bid": {"bid": 0.4},
            "targetDetails": {"keywordTarget": {"keyword": "cat shirt", "matchType": "BROAD"}}}
AD       = {"adId": "444", "campaignId": "111", "adGroupId": "222", "state": "ENABLED",
            "advertisedProducts": [{"resolvedProductId": "B0TEST12345"}]}

scenario = {"empty": set(), "fail": set()}


def fake_post(url, **kw):
    if "auth/o2/token" in url:
        return FakeResp({"access_token": "fake"})
    scope = (kw.get("headers") or {}).get("Amazon-Advertising-API-Scope", "")
    if scope in scenario["fail"]:
        return FakeResp({"code": "401", "details": "Unauthorized for profile"}, status=401)
    empty = scope in scenario["empty"]
    if url.endswith("/query/campaigns"):
        return FakeResp({"campaigns": [] if empty else [CAMPAIGN]})
    if url.endswith("/query/adGroups"):
        return FakeResp({"adGroups": [] if empty else [AD_GROUP]})
    if url.endswith("/query/targets"):
        return FakeResp({"targets": [] if empty else [TARGET]})
    if url.endswith("/query/ads"):
        return FakeResp({"ads": [] if empty else [AD]})
    if url.endswith("/query/portfolios"):
        return FakeResp({"portfolios": []})
    raise AssertionError(f"unexpected POST {url}")


class FakeJob:
    errors = None
    def result(self): return None

class FakeCount:
    def __init__(self, c): self.c = c
    def result(self): return [{"c": self.c}]

class FakeBQ:
    existing_rows = 0
    def __init__(self): self.deletes, self.loaded = [], []
    def query(self, sql):
        if sql.strip().upper().startswith("SELECT COUNT"):
            return FakeCount(FakeBQ.existing_rows)
        self.deletes.append(sql); return FakeJob()
    def load_table_from_json(self, rows, table, job_config=None):
        self.loaded.append((table, len(rows))); return FakeJob()


fake_bq = FakeBQ()
cr.req_lib.post = fake_post
cr.bigquery.Client = lambda project=None: fake_bq
time.sleep = lambda s: None

PROFILES = [
    {"id": "1001", "type": "MERCH", "marketplace": "US", "name": "Merch US"},
    {"id": "2002", "type": "KDP", "marketplace": "UK", "name": "KDP UK",
     "api_endpoint": "https://advertising-api-eu.amazon.com"},
]
cr._AMZ["profiles"] = PROFILES
auto_sync_campaigns._AMZ = cr._AMZ


def run(label, empty=(), fail=()):
    global fake_bq
    scenario["empty"] = set(empty); scenario["fail"] = set(fail)
    fake_bq = FakeBQ(); cr.bigquery.Client = lambda project=None: fake_bq
    if os.path.exists(cr.SYNC_LOG):
        os.remove(cr.SYNC_LOG)
    print(f"\n{'='*60}\n  {label}\n{'='*60}")
    auto_sync_campaigns.main()
    return cr._read_sync_log(), fake_bq


# ── 1. Обычная синхронизация ──────────────────────────────
entries, bq = run("СЦЕНАРИЙ 1: обе гео синхронизируются нормально")
assert len(entries) == 2, entries
assert all(e["status"] == "OK" for e in entries), [e["status"] for e in entries]
assert all(e["source"] == "auto" for e in entries)
assert all(e["total"] == 4 for e in entries), [e["total"] for e in entries]   # camp+grp+kw+ad
assert len(bq.deletes) == 2 and len(bq.loaded) == 2
assert all(e["counts"]["campaign"] == 1 for e in entries)
assert all(e["duration_sec"] is not None and e["finished_at"] for e in entries)
print("  ✓ OK, 4 строки на профиль, DELETE + загрузка выполнены")

# ── 2. Пустой ответ API при непустой базе ─────────────────
FakeBQ.existing_rows = 98765
entries, bq = run("СЦЕНАРИЙ 2: API вернул 0 объектов по KDP UK, в базе есть данные", empty={"2002"})
kdp = next(e for e in entries if e["account_type"] == "KDP")
mer = next(e for e in entries if e["account_type"] == "MERCH")
print(f"  KDP UK   → status={kdp['status']} note={kdp['note']}")
print(f"  Merch US → status={mer['status']} total={mer['total']}")
assert kdp["status"] == "EMPTY" and kdp["total"] == 0
assert "не тронуты" in kdp["note"], kdp["note"]
assert mer["status"] == "OK"
assert len(bq.deletes) == 1, f"DELETE только для Merch US, а было {len(bq.deletes)}"
assert all("campaigns_kdp" not in q for q in bq.deletes), "структура KDP НЕ должна удаляться!"
print("  ✓ структура в базе сохранена, DELETE по пустому профилю не выполнен")
FakeBQ.existing_rows = 0

# ── 3. Ошибка API у одного профиля ────────────────────────
entries, bq = run("СЦЕНАРИЙ 3: 401 по KDP UK", fail={"2002"})
kdp = next(e for e in entries if e["account_type"] == "KDP")
mer = next(e for e in entries if e["account_type"] == "MERCH")
print(f"  KDP UK   → status={kdp['status']} error={str(kdp['error'])[:60]}")
print(f"  Merch US → status={mer['status']} total={mer['total']}")
assert kdp["status"] == "ERROR" and kdp["error"]
assert mer["status"] == "OK", "сбой одного профиля не должен ломать остальные"
assert not any(e["status"] == "RUNNING" for e in entries), "не должно остаться зависших RUNNING"
print("  ✓ ERROR с текстом, остальные профили обработаны, зависших RUNNING нет")

# ── 4. Endpoint истории ───────────────────────────────────
from flask import Flask
app = Flask(__name__); app.register_blueprint(cr.campaigns_bp)
data = app.test_client().get("/campaigns/history?limit=100").get_json()
assert len(data) == 2 and data[0]["source"] == "auto"
ts = [(d["finished_at"] or d["created_at"]) for d in data]
assert ts == sorted(ts, reverse=True), "история должна быть отсортирована по времени"
print(f"\n/campaigns/history → {len(data)} записи, сортировка по времени OK")

print("\n=== ВСЕ ПРОВЕРКИ ПРОШЛИ ===")
