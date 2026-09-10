# -*- coding: utf-8 -*-
"""Ставка группы объявлений: поле default_bid, а не bid.

Раньше страницы слали для группы field_name='bid', очередь такие записи молча
принимала, а send.py их не понимал — в логе шло «Неизвестный тип: ad_group/bid,
пропускаем», и ставка группы до Amazon не доходила.
"""
import base64, importlib.util, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/dev/null"

import bq_client


class FakeJob:
    errors = None
    def __init__(self, rows=None): self._rows = rows or []
    def result(self): return self._rows


class Cnt:
    cnt = 0


class FakeBQ:
    def __init__(self): self.loaded = []
    def query(self, sql):
        # дубликатов нет: запрос проверки возвращает одну строку с нулём
        return FakeJob([Cnt()] if 'cnt' in sql.lower() or 'count(' in sql.lower() else [])
    def load_table_from_json(self, rows, table, job_config=None):
        self.loaded.append(list(rows)); return FakeJob()


fake = FakeBQ()
bq_client._client = fake

import app as A
import management.control_routes as cr
cr.bigquery.Client = lambda project=None: fake

c   = A.app.test_client()
tok = base64.b64encode(f"{A.AUTH_USERNAME}:{A.AUTH_PASSWORD}".encode()).decode()
H   = {'Authorization': f'Basic {tok}'}

ITEM = {"account_type": "MERCH", "marketplace": "US", "profile_id": "111",
        "entity_type": "ad_group", "entity_id": "g1",
        "old_value": "0.50", "new_value": "0.75"}


# ── 1. Одиночное добавление: bid → default_bid ────────────
fake.loaded.clear()
r = c.post('/control/add', headers=H, json={**ITEM, "field_name": "bid"})
d = r.get_json()
assert r.status_code == 200, d
assert fake.loaded[-1][0]['field_name'] == 'default_bid', fake.loaded[-1][0]
assert 'Ставка группы' in d.get('label', ''), d
print("  ✓ ставка группы попадает в очередь как default_bid, с понятной подписью")


# ── 2. Batch-обновление — так же ──────────────────────────
fake.loaded.clear()
r = c.post('/control/add_batch_update', headers=H,
           json={"items": [{**ITEM, "field_name": "bid"}]})
d = r.get_json()
assert r.status_code == 200 and d['inserted'] == 1, d
assert fake.loaded[-1][0]['field_name'] == 'default_bid'
print("  ✓ массовое изменение ставок групп — тоже default_bid")


# ── 3. Неизвестное поле теперь отвергается сразу ──────────
r = c.post('/control/add', headers=H,
           json={**ITEM, "field_name": "portfolio_id"})
assert r.status_code == 400, r.get_json()
assert 'нельзя менять' in r.get_json()['error']
r = c.post('/control/add_batch_update', headers=H,
           json={"items": [{**ITEM, "field_name": "portfolio_id"}]})
assert (r.get_json().get('errors') or [{}])[0].get('error', '').startswith('Для ad_group'), r.get_json()
print("  ✓ чужое поле не оседает в очереди мёртвым грузом, а отклоняется с текстом")


# ── 4. send.py разбирает уже накопленные записи ───────────
spec = importlib.util.spec_from_file_location("send_mod", os.path.join(BASE, "scripts", "send.py"))
send = importlib.util.module_from_spec(spec)
spec.loader.exec_module(send)

old_rec = {"entity_type": "ad_group", "field_name": "bid", "entity_id": "g1",
           "new_value": "0.75", "old_value": "0.50"}
groups = send.group_changes([old_rec])
assert groups["update_ad_groups"] == [old_rec], groups
assert old_rec["field_name"] == "default_bid", "имя поля должно нормализоваться"
print("  ✓ старые записи из очереди уходят в Amazon, а не пропускаются с ошибкой")

# и попадают в нужную колонку BigQuery
assert send.BQ_FIELD_MAP[("ad_group", "default_bid")][0] == "ad_group_default_bid"
print("  ✓ результат пишется в ad_group_default_bid")

print("\n=== ВСЕ ПРОВЕРКИ ПРОШЛИ ===")
