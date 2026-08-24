# -*- coding: utf-8 -*-
"""Запись применённых изменений в campaigns_* одним запросом на колонку.

Раньше на каждое изменение шёл свой UPDATE, и массовая пауза упиралась в
«Could not serialize access ... due to concurrent update».
"""
import os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'scripts'))
os.chdir(BASE)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/dev/null"

import send


class FakeJob:
    def result(self): return []


class FakeBQ:
    """Считает запросы и умеет разок упасть с конфликтом записи."""
    def __init__(self, fail_times=0):
        self.queries, self.fail_times = [], fail_times
    def query(self, sql):
        self.queries.append(sql)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise Exception("400 Could not serialize access to table "
                            "amazon-ads-api-494412:amazon_ads.campaigns_merch "
                            "due to concurrent update")
        return FakeJob()


# ── 1. Массовая пауза групп — один запрос вместо сотни ────
bq = FakeBQ()
groups = [{"entity_type": "ad_group", "entity_id": f"g{i}", "field_name": "state",
           "new_value": "PAUSED", "campaign_id": "c1"} for i in range(100)]
send.update_campaigns_bq(bq, "MERCH", "US", groups)
assert len(bq.queries) == 1, f"запросов: {len(bq.queries)} — должен быть один"
sql = bq.queries[0]
assert sql.startswith("UPDATE") and "SET ad_group_state = CASE ad_group_id" in sql
assert sql.count("WHEN 'g") == 100 and "ELSE ad_group_state END" in sql
assert "marketplace='US'" in sql
print(f"  ✓ 100 пауз групп — 1 запрос вместо 100 (раньше здесь и ловился конфликт)")


# ── 2. Разные поля — по запросу на колонку, значения не путаются ──
bq = FakeBQ()
send.update_campaigns_bq(bq, "MERCH", "US", [
    {"entity_type": "ad_group", "entity_id": "g1", "field_name": "state",
     "new_value": "PAUSED", "campaign_id": "c1"},
    {"entity_type": "keyword", "entity_id": "k1", "field_name": "bid",
     "new_value": "0.35", "campaign_id": "c1"},
    {"entity_type": "keyword", "entity_id": "k2", "field_name": "bid",
     "new_value": "0.40", "campaign_id": "c1"},
    {"entity_type": "campaign", "entity_id": "c1", "field_name": "name",
     "new_value": "Ivan's camp", "campaign_id": "c1"},
])
assert len(bq.queries) == 3, bq.queries
kw = [q for q in bq.queries if "keyword_bid" in q][0]
assert "WHEN 'k1' THEN 0.35" in kw and "WHEN 'k2' THEN 0.4" in kw
nm = [q for q in bq.queries if "campaign_name" in q][0]
assert "'Ivan''s camp'" in nm, "апостроф в названии не экранирован"
print("  ✓ каждая колонка — свой запрос, числа без кавычек, апостроф экранирован")


# ── 3. Удаления тоже пачкой ───────────────────────────────
bq = FakeBQ()
send.update_campaigns_bq(bq, "MERCH", "US", [
    {"entity_type": "negative_delete", "entity_id": "n1", "field_name": "", "new_value": ""},
    {"entity_type": "negative_delete", "entity_id": "n2", "field_name": "", "new_value": ""},
    {"entity_type": "campaign_delete", "entity_id": "c9", "field_name": "", "new_value": ""},
])
assert len(bq.queries) == 2, bq.queries
neg = [q for q in bq.queries if "negative_keyword" in q][0]
assert "keyword_id IN ('n1','n2')" in neg
print("  ✓ удаления минус-слов и кампаний — по одному запросу на тип")


# ── 4. Конфликт параллельной записи переживается повтором ──
send.with_retry.__globals__['RETRY_PAUSES'] = (0, 0)     # без ожидания в тесте
bq = FakeBQ(fail_times=1)
send.update_campaigns_bq(bq, "MERCH", "US", [
    {"entity_type": "ad_group", "entity_id": "g1", "field_name": "state",
     "new_value": "PAUSED", "campaign_id": "c1"}])
assert len(bq.queries) == 2, "после конфликта запрос должен повториться"
print("  ✓ «concurrent update» не теряет изменение — запрос повторяется")


# ── 5. Неизвестные типы игнорируются, а не ломают запись ──
bq = FakeBQ()
send.update_campaigns_bq(bq, "MERCH", "US", [
    {"entity_type": "keyword_add", "entity_id": "x", "field_name": "text", "new_value": "y"}])
assert bq.queries == [], "вставки не должны превращаться в UPDATE"
print("  ✓ keyword_add / negative_add в UPDATE не попадают")

print("\n=== ВСЕ ПРОВЕРКИ ПРОШЛИ ===")
