# -*- coding: utf-8 -*-
"""Что происходит с гео, где нет рекламы / нет доступа.

Профили теста:
  Merch US — обычный отчёт с данными
  KDP UK   — отчёт COMPLETED, но пустой ([]) — гео без рекламы
Плюс отдельная проверка: 400 от Amazon при создании отчёта,
и сбой при скачивании уже готового отчёта.
"""
import gzip, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/dev/null"

import scripts.auto_collect as auto_collect
import data_import.ads_routes as ads_routes
import bq_client


class FakeResp:
    def __init__(self, payload, status=200, raw=None):
        self._payload, self.status_code = payload, status
        self.content = raw if raw is not None else json.dumps(payload).encode()
    def json(self): return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}: {self._payload}")


ROWS_US = [{"date": "2026-08-15", "campaignId": 111, "adGroupId": 222, "keywordId": 333,
            "keyword": "cat shirt", "keywordType": "BROAD",
            "impressions": 10, "clicks": 1, "cost": 0.5}]

scenario = {"create_fails": False, "download_fails": False}
state = {"checks": {}, "rid2prof": {}}


def fake_post(url, **kw):
    if "auth/o2/token" in url:
        return FakeResp({"access_token": "fake"})
    if url.endswith("/reporting/reports"):
        name = (kw.get("json") or {}).get("name", "")
        if scenario["create_fails"] and "KDP" in name:
            r = FakeResp({"code": "400", "details": "Profile has no Sponsored Products"}, status=400)
            r.text = json.dumps({"code": "400", "details": "Profile has no Sponsored Products"})
            return r
        rid = f"r{len(state['checks'])+1}"
        state["checks"][rid] = 0
        state["rid2prof"][rid] = "KDP" if "KDP" in name else "MERCH"
        return FakeResp({"reportId": rid})
    raise AssertionError(url)


def fake_get(url, **kw):
    if "/reporting/reports/" in url:
        rid = url.rsplit("/", 1)[1]
        state["checks"][rid] += 1
        if state["checks"][rid] < 2:
            return FakeResp({"status": "PENDING"})
        return FakeResp({"status": "COMPLETED", "url": f"https://s3.fake/{rid}.gz"})
    if "s3.fake" in url:
        if scenario["download_fails"]:
            raise Exception("Connection reset by peer")
        rid = url.split("/")[-1].replace(".gz", "")
        rows = [] if state["rid2prof"][rid] == "KDP" else ROWS_US   # KDP UK — гео без рекламы
        return FakeResp(None, raw=gzip.compress(json.dumps(rows).encode()))
    raise AssertionError(url)


class FakeJob:
    def result(self): return None

class FakeCount:
    def __init__(self, c): self.c = c
    def result(self): return [{"c": self.c}]

class FakeBQ:
    existing_rows = 0          # сколько строк "уже есть" в базе за период
    def __init__(self): self.deletes, self.loaded, self.counts = [], [], []
    def query(self, sql):
        if sql.strip().upper().startswith("SELECT COUNT"):
            self.counts.append(sql); return FakeCount(FakeBQ.existing_rows)
        self.deletes.append(sql); return FakeJob()
    def load_table_from_json(self, rows, table, job_config=None):
        self.loaded.append((table, len(rows))); return FakeJob()


def run(label, **flags):
    scenario.update({"create_fails": False, "download_fails": False})
    scenario.update(flags)
    state["checks"].clear(); state["rid2prof"].clear()
    bq_client._client = FakeBQ()
    if os.path.exists(auto_collect.AUTO_LOG):
        os.remove(auto_collect.AUTO_LOG)
    print(f"\n{'='*60}\n  {label}\n{'='*60}")
    auto_collect.main(days=14, only_types=["spTargeting"])
    return auto_collect._read_log(), bq_client._client


auto_collect.requests.post = fake_post
auto_collect.requests.get = fake_get
ads_routes.req_lib.post = fake_post
auto_collect.POLL_EVERY = 1
auto_collect.MAX_WAIT = 10
time.sleep = lambda s: None

# ── 1. Гео без рекламы: отчёт готов, но пустой ────────────
entries, bq = run("СЦЕНАРИЙ 1: KDP UK — нет рекламы (пустой отчёт)")
kdp = next(e for e in entries if e["account_type"] == "KDP")
mer = next(e for e in entries if e["account_type"] == "MERCH")
print(f"  KDP UK   → status={kdp['status']} rows={kdp['rows']} inserted={kdp['inserted']} error={kdp['error']}")
print(f"  Merch US → status={mer['status']} rows={mer['rows']} inserted={mer['inserted']}")
assert kdp["status"] == "EMPTY" and kdp["rows"] == 0 and kdp["inserted"] == 0
assert kdp["note"] == "нет рекламы за период", kdp["note"]
assert mer["status"] == "LOADED" and mer["inserted"] == 1
assert len(bq.deletes) == 1, "DELETE только для гео с данными"
assert len(bq.loaded) == 1
print("  ✓ пустое гео: EMPTY, 0 строк, DELETE не выполнялся, остальные гео не задеты")

# ── 1b. Пустой отчёт, НО в базе уже есть данные ───────────
FakeBQ.existing_rows = 12345
entries, bq = run("СЦЕНАРИЙ 1b: пустой отчёт при непустой базе — данные должны уцелеть")
kdp = next(e for e in entries if e["account_type"] == "KDP")
print(f"  KDP UK   → status={kdp['status']} inserted={kdp['inserted']} note={kdp['note']}")
assert kdp["status"] == "EMPTY" and kdp["inserted"] == 0
assert "не тронуты" in kdp["note"], kdp["note"]
assert len(bq.deletes) == 1, f"DELETE должен быть только для Merch US, а было {len(bq.deletes)}"
assert all("targets_stats_kdp" not in q for q in bq.deletes), "данные KDP UK НЕ должны удаляться!"
print("  ✓ данные в базе сохранены, DELETE по пустому гео не выполнен")
FakeBQ.existing_rows = 0

# ── 2. Профиль без Sponsored Products: 400 при создании ───
entries, bq = run("СЦЕНАРИЙ 2: KDP UK — 400 при создании отчёта", create_fails=True)
kdp = next(e for e in entries if e["account_type"] == "KDP")
mer = next(e for e in entries if e["account_type"] == "MERCH")
print(f"  KDP UK   → status={kdp['status']} error={str(kdp['error'])[:70]}")
print(f"  Merch US → status={mer['status']} inserted={mer['inserted']}")
assert kdp["status"] == "FAILED" and kdp["error"]
assert mer["status"] == "LOADED", "сбой одного гео не должен ломать остальные"
print("  ✓ FAILED с текстом ошибки, остальные гео обработаны")

# ── 3. Сбой скачивания уже готового отчёта ────────────────
entries, bq = run("СЦЕНАРИЙ 3: обрыв связи при скачивании готового отчёта", download_fails=True)
for e in entries:
    print(f"  {e['profile_name']} → status={e['status']} error={str(e['error'])[:50]} finished={e['finished_at']}")
stuck = [e for e in entries if e["status"] == "PENDING"]
print(f"  → зависших в PENDING: {len(stuck)}")
