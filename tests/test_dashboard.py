# -*- coding: utf-8 -*-
"""Сводка по портфолио на главной: /dashboard/portfolios."""
import base64, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/dev/null"

import bq_client


class FakeJob:
    errors = None
    def __init__(self, rows): self._rows = rows
    def result(self): return self._rows


class FakeBQ:
    def __init__(self): self.queries = []; self.rows = []
    def query(self, sql):
        self.queries.append(sql)
        return FakeJob(self.rows)


fake = FakeBQ()
bq_client._client = fake

import app as A

c   = A.app.test_client()
tok = base64.b64encode(f"{A.AUTH_USERNAME}:{A.AUTH_PASSWORD}".encode()).decode()
H   = {'Authorization': f'Basic {tok}'}


# ── 1. Главная отдаётся вместе с блоком сводки ────────────
r = c.get('/', headers=H)
html = r.get_data(as_text=True)
assert r.status_code == 200
assert 'Сводка по портфолио' in html and 'dashboard/portfolios' in html
print("  ✓ блок сводки есть на главной")


# ── 2. Расчёты: ACoS, прибыль, итоги ──────────────────────
fake.rows = [
    {"portfolio": "Vintage_Flag", "marketplace": "", "campaigns": 34,
     "impressions": 320000, "clicks": 2100, "cost": 845.20, "sales": 3120.50, "orders": 180,
     "prev_cost": 690.10, "prev_sales": 2500.0, "prev_orders": 150},
    {"portfolio": "Class_of_2039", "marketplace": "", "campaigns": 18,
     "impressions": 210000, "clicks": 1400, "cost": 512.40, "sales": 420.0, "orders": 22,
     "prev_cost": 380.0, "prev_sales": 600.0, "prev_orders": 31},
]
r = c.get('/dashboard/portfolios?account_type=MERCH&date_from=2026-08-01&date_to=2026-08-30',
          headers=H)
d = r.get_json()
assert r.status_code == 200, d
a, b = d['rows']
assert a['acos'] == round(845.20 / 3120.50 * 100, 1)
assert b['profit'] == round(420.0 - 512.40, 2) < 0     # убыточное портфолио видно сразу
t = d['total']
assert t['cost'] == 1357.6 and t['sales'] == 3540.5 and t['orders'] == 202
assert t['acos'] == round(1357.6 / 3540.5 * 100, 1)
print(f"  ✓ считается ACoS, прибыль и итоги: расход ${t['cost']}, продажи ${t['sales']}, "
      f"ACoS {t['acos']}%")


# ── 3. Период и сравнение с предыдущим ────────────────────
p = d['period']
assert p['days'] == 30 and p['from'] == '2026-08-01' and p['to'] == '2026-08-30'
assert p['prev_from'] == '2026-07-02' and p['prev_to'] == '2026-07-31', p
sql = fake.queries[-1]
assert "s.date BETWEEN '2026-07-02' AND '2026-08-30'" in sql, "предыдущий период не запрашивается"
assert "IF(s.date >= '2026-08-01'" in sql and "IF(s.date <  '2026-08-01'" in sql
print(f"  ✓ период {p['from']}—{p['to']} сравнивается с {p['prev_from']}—{p['prev_to']} "
      f"одним запросом")


# ── 4. Разбивка по странам и фильтр активных ──────────────
c.get('/dashboard/portfolios?account_type=MERCH&by_country=1', headers=H)
sql = fake.queries[-1]
assert 'c.marketplace AS marketplace' in sql and 'GROUP BY c.portfolio, marketplace' in sql
c.get('/dashboard/portfolios?account_type=MERCH', headers=H)
assert "'' AS marketplace" in fake.queries[-1], "без разбивки страны суммируются в одну строку"
assert "campaign_state = 'ENABLED'" in fake.queries[-1]
c.get('/dashboard/portfolios?account_type=MERCH&active_only=0', headers=H)
assert "campaign_state = 'ENABLED'" not in fake.queries[-1]
print("  ✓ «все страны» / «по странам» и фильтр активных кампаний уходят в SQL")


# ── 5. KDP и защита от мусора в параметрах ────────────────
c.get('/dashboard/portfolios?account_type=KDP', headers=H)
assert 'campaigns_kdp' in fake.queries[-1] and "account_type = 'KDP'" in fake.queries[-1]
assert c.get('/dashboard/portfolios?account_type=XXX', headers=H).status_code == 400
c.get('/dashboard/portfolios?account_type=MERCH&date_from=не-дата', headers=H)
assert 'BETWEEN' in fake.queries[-1], "кривая дата не должна ронять запрос"
print("  ✓ KDP берёт свои таблицы, мусор в параметрах не ломает запрос")

print("\n=== ВСЕ ПРОВЕРКИ ПРОШЛИ ===")
