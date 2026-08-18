# -*- coding: utf-8 -*-
"""Страница «Остановка ASIN без продаж» и пакетная постановка групп в очередь.

Проверяется то, что раньше делалось руками: выбрать ASIN без заказов и
остановить все их группы одним действием.
"""
import base64, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/dev/null"

import bq_client


class FakeJob:
    errors = None
    def __init__(self, rows=None): self._rows = rows or []
    def result(self): return self._rows


class FakeBQ:
    """Отдаёт заготовленные ответы и запоминает, что записывали."""
    def __init__(self):
        self.queries, self.loaded = [], []
        self.data_rows = []
        self.group_rows = []
        self.pending = []          # уже стоящие в очереди (entity_type, entity_id, field_name)
    def query(self, sql):
        self.queries.append(sql)
        low = sql.lower()
        if 'from stats s' in low or 'grp_cnt' in low and 'active_groups' in low and 'cat' in low:
            return FakeJob(self.data_rows)
        if 'grp_total' in low:
            return FakeJob(self.group_rows)
        if 'status = \'pending\'' in low:
            return FakeJob([dict(entity_type=t, entity_id=i, field_name=f)
                            for t, i, f in self.pending])
        return FakeJob([])
    def load_table_from_json(self, rows, table, job_config=None):
        self.loaded.append((table, list(rows))); return FakeJob()
    def load_table_from_file(self, fh, table, job_config=None):
        return FakeJob()


fake = FakeBQ()
bq_client._client = fake

import app as A
import management.control_routes as cr
cr.bigquery.Client = lambda project=None: fake

c   = A.app.test_client()
tok = base64.b64encode(f"{A.AUTH_USERNAME}:{A.AUTH_PASSWORD}".encode()).decode()
H   = {'Authorization': f'Basic {tok}'}


# ── 1. Страница отдаётся, с меню и оформлением ────────────
r = c.get('/automation/pause-asins', headers=H)
html = r.get_data(as_text=True)
assert r.status_code == 200
assert 'nav-drop-menu' in html and 'Общее оформление' in html
assert 'Остановка ASIN без продаж' in html
assert 'class="nav-link active">Остановка ASIN' in html.replace('\n', ' ') or 'active' in html
print("  ✓ страница открывается, шапка и стили подставлены")


# ── 2. Поиск ASIN: критерии уходят в запрос ───────────────
fake.data_rows = [
    {"asin": "B0TEST0001", "marketplace": "US", "impressions": 5000, "clicks": 42,
     "cost": 18.4, "sales_14d": 0.0, "purchases_14d": 0, "active_groups": 3,
     "auto_groups": 1, "manual_groups": 2,
     "title": "Cat shirt", "image_url": None, "acos": None},
    {"asin": "B0TEST0002", "marketplace": "US", "impressions": 900, "clicks": 15,
     "cost": 6.1, "sales_14d": 0.0, "purchases_14d": 0, "active_groups": 1,
     "auto_groups": 1, "manual_groups": 0,
     "title": "Dog shirt", "image_url": None, "acos": None},
]
r = c.get('/automation/pause-asins/data?account_type=MERCH&marketplace=US'
          '&date_from=2026-07-01&date_to=2026-08-16&min_clicks=10&min_cost=5&max_orders=0',
          headers=H)
d = r.get_json()
assert r.status_code == 200, d
assert d['total'] == 2
assert d['summary']['groups'] == 4 and d['summary']['asins'] == 2
sql = fake.queries[-1]
assert 's.clicks        >= 10.0' in sql and 's.purchases_14d <= 0.0' in sql
assert "ad_state = 'ENABLED'" in sql and "ad_group_state = 'ENABLED'" in sql
print(f"  ✓ найдено {d['total']} ASIN, {d['summary']['groups']} активных групп, "
      f"впустую ${d['summary']['cost']}")

# уже остановленные группы в выборку не идут
assert 'active_groups' in sql and 'IFNULL(gc.active_groups, 0) > 0' in sql
print("  ✓ ASIN без активных групп отфильтрованы на стороне SQL")


# ── 3. Предпросмотр групп + чужие ASIN в группе ───────────
fake.group_rows = [
    {"ad_group_id": "g1", "ad_group_name": "Grp 1", "campaign_id": "c1",
     "marketplace": "US", "profile_id": "111", "campaign_name": "Camp A",
     "asins_total": 1, "asins_selected": 1, "targeting_type": "AUTO"},
    {"ad_group_id": "g2", "ad_group_name": "Grp 2", "campaign_id": "c1",
     "marketplace": "US", "profile_id": "111", "campaign_name": "Camp A",
     "asins_total": 4, "asins_selected": 1, "targeting_type": "MANUAL"},
]
r = c.get if False else c.post('/automation/pause-asins/groups', headers=H, json={
    "account_type": "MERCH", "marketplace": "US",
    "asins": ["B0TEST0001", "B0TEST0002"]})
d = r.get_json()
assert r.status_code == 200, d
assert d['total'] == 2 and d['with_other'] == 1
assert d['groups'][0]['has_other_asins'] is False
assert d['groups'][1]['has_other_asins'] is True
print("  ✓ предпросмотр: 2 группы, из них 1 с чужими ASIN — помечена предупреждением")


# ── 3b. Фильтр по типу кампаний (авто / ручные) ───────────
r = c.get('/automation/pause-asins/data?account_type=MERCH&marketplace=US&ttype=AUTO', headers=H)
assert r.status_code == 200, r.get_json()
sql = fake.queries[-1]
assert "WHERE TRUE AND ct.targeting_type = 'AUTO'" in sql, "фильтр авто-кампаний не попал в запрос"
assert 'grps AS' in sql and 'groups AS' not in sql, "GROUPS — зарезервированное слово BigQuery"
assert 'auto_groups' in sql and 'manual_groups' in sql
print("  ✓ фильтр «только авто» уходит в SQL, разбивка авто/ручные считается")

r = c.get('/automation/pause-asins/data?account_type=MERCH&ttype=MANUAL', headers=H)
assert "WHERE TRUE AND ct.targeting_type = 'MANUAL'" in fake.queries[-1]
r = c.get('/automation/pause-asins/data?account_type=MERCH', headers=H)
# в запросе всегда есть подсчёт разбивки IF(ct.targeting_type='AUTO'...),
# поэтому проверяем именно условие фильтрации в WHERE
assert "WHERE TRUE AND ct.targeting_type" not in fake.queries[-1], "без фильтра тип не ограничивается"
print("  ✓ «только ручные» и «все» работают так же")

# фильтр применяется и при выборе групп на остановку
r = c.post('/automation/pause-asins/groups', headers=H, json={
    "account_type": "MERCH", "marketplace": "US", "ttype": "AUTO",
    "asins": ["B0TEST0001"]})
d2 = r.get_json()
assert r.status_code == 200, d2
assert "c.targeting_type = 'AUTO'" in fake.queries[-1]
assert d2['auto'] == 1 and d2['manual'] == 1   # фейк отдаёт обе, счётчики считаются
print("  ✓ при остановке фильтр типа тоже учитывается, в ответе разбивка")


# ── 4. Пакетная постановка пауз в очередь ─────────────────
items = [{"account_type": "MERCH", "marketplace": "US", "profile_id": "111",
          "entity_type": "ad_group", "entity_id": g["ad_group_id"],
          "field_name": "state", "old_value": "ENABLED", "new_value": "PAUSED"}
         for g in d['groups']]
fake.loaded.clear()
r = c.post('/control/add_batch', headers=H, json={"items": items})
res = r.get_json()
assert r.status_code == 200, res
assert res['inserted'] == 2 and res.get('skipped', 0) == 0
table, rows = fake.loaded[-1]
assert all(x['entity_type'] == 'ad_group' and x['new_value'] == 'PAUSED'
           and x['status'] == 'PENDING' for x in rows)
print(f"  ✓ {res['inserted']} пауз поставлено в очередь одним запросом "
      f"(раньше ad_group в batch не принимался вовсе)")


# ── 5. Повтор не создаёт дублей ───────────────────────────
fake.pending = [("ad_group", "g1", "state"), ("ad_group", "g2", "state")]
fake.loaded.clear()
r = c.post('/control/add_batch', headers=H, json={"items": items})
res = r.get_json()
assert res['inserted'] == 0 and res['skipped'] == 2, res
assert not fake.loaded, "ничего не должно записываться"
print("  ✓ повторная постановка тех же групп пропущена (skipped=2), дублей нет")

# частичный дубль: одна уже в очереди, вторая новая
fake.pending = [("ad_group", "g1", "state")]
fake.loaded.clear()
res = c.post('/control/add_batch', headers=H, json={"items": items}).get_json()
assert res['inserted'] == 1 and res['skipped'] == 1, res
assert fake.loaded[-1][1][0]['entity_id'] == 'g2'
print("  ✓ частичный повтор: новая группа добавлена, дубль пропущен")

print("\n=== ВСЕ ПРОВЕРКИ ПРОШЛИ ===")
