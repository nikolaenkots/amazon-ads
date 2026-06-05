#!/usr/bin/env python3
"""
Запустить на сервере: python3 apply_patch.py
Патчит control_routes.py и send.py
"""
import os, sys

BASE = os.path.dirname(os.path.abspath(__file__))

# ── Patch control_routes.py ───────────────────────────────
cr_path = os.path.join(BASE, 'control_routes.py')
with open(cr_path) as f:
    c = f.read()

# 1. Add negative_product_add to ALLOWED_OPS
old_ops = '''    "negative_delete":["—"],   # entity_id = keyword_id минус слова
    "product_ad":     ["state"],  # включить/выключить объявление'''
new_ops = '''    "negative_delete":    ["—"],   # entity_id = keyword_id минус слова
    "negative_product_add":["—"], # new_value = JSON {asin, ad_group_id, campaign_id}
    "ad_group_add":       ["—"],  # new_value = JSON {name, default_bid, campaign_id}
    "product_ad":         ["state"],'''
if old_ops in c:
    c = c.replace(old_ops, new_ops)
    print("ALLOWED_OPS: OK")
else:
    print("ALLOWED_OPS: NOT FOUND — check manually")

# 2. Add labels
old_lbl = '''    ("negative_delete","—"):       lambda nv: '🗑️ Удалить минус слово','''
new_lbl = '''    ("negative_delete","—"):       lambda nv: '🗑️ Удалить минус слово',
    ("negative_product_add","—"):  lambda nv: f'🚫 Минус ASIN: {nv[:60]}',
    ("ad_group_add","—"):          lambda nv: f'➕ Новая группа: {nv[:60]}','''
if old_lbl in c:
    c = c.replace(old_lbl, new_lbl)
    print("LABELS: OK")
else:
    print("LABELS: NOT FOUND — check manually")

# 3. Fix duplicate check — skip for add operations
old_dup = '''    # Проверка дублей — не добавляем если уже есть PENDING для того же объекта+поля
    bq = bigquery.Client(project=PROJECT_ID)
    table = PENDING_TABLES[account_type]
    fn_clause = f"AND field_name = '{field_name}'" if field_name != '—' else ''
    dup_sql = f"""
    SELECT COUNT(*) as cnt FROM `{table}`
    WHERE entity_id = '{entity_id}'
      AND entity_type = '{entity_type}'
      {fn_clause}
      AND status IN ('PENDING', 'APPROVED')
    """
    dup_count = list(bq.query(dup_sql).result())[0].cnt
    if dup_count > 0:
        return jsonify({"error": "Уже есть ожидающее изменение для этого объекта"}), 409'''
new_dup = '''    bq = bigquery.Client(project=PROJECT_ID)
    table = PENDING_TABLES[account_type]

    # Для операций добавления разрешаем несколько записей (несколько минусов/ключей в одну группу)
    NO_DUP_CHECK = {'keyword_add', 'negative_add', 'negative_product_add', 'ad_group_add'}
    if entity_type not in NO_DUP_CHECK:
        fn_clause = f"AND field_name = '{field_name}'" if field_name != '—' else ''
        dup_sql = f"""
        SELECT COUNT(*) as cnt FROM `{table}`
        WHERE entity_id = '{entity_id}'
          AND entity_type = '{entity_type}'
          {fn_clause}
          AND status IN ('PENDING', 'APPROVED')
        """
        dup_count = list(bq.query(dup_sql).result())[0].cnt
        if dup_count > 0:
            return jsonify({"error": "Уже есть ожидающее изменение для этого объекта"}), 409'''
if old_dup in c:
    c = c.replace(old_dup, new_dup)
    print("DUP_CHECK: OK")
else:
    print("DUP_CHECK: NOT FOUND — check manually")

with open(cr_path, 'w') as f:
    f.write(c)
print(f"control_routes.py saved ({len(c)} chars)")


# ── Patch send.py ─────────────────────────────────────────
sp_path = os.path.join(BASE, 'send.py')
with open(sp_path) as f:
    s = f.read()

# 1. Add negative_product_add to group_changes
old_grp = '''        elif et in ("keyword_add", "negative_add"):
            groups["create_targets"].append(c)'''
new_grp = '''        elif et in ("keyword_add", "negative_add", "negative_product_add"):
            groups["create_targets"].append(c)
        elif et == "ad_group_add":
            groups["create_ad_groups"].append(c)'''
if old_grp in s:
    s = s.replace(old_grp, new_grp)
    print("send.py group_changes: OK")
else:
    print("send.py group_changes: NOT FOUND")

# 2. Add create_ad_groups key in groups dict
old_groups_dict = '''    groups = {
        "update_campaigns": [],
        "update_ad_groups": [],
        "update_targets":   [],
        "create_targets":   [],
        "delete_targets":   [],
    }'''
new_groups_dict = '''    groups = {
        "update_campaigns":  [],
        "update_ad_groups":  [],
        "update_targets":    [],
        "create_targets":    [],
        "delete_targets":    [],
        "create_ad_groups":  [],
    }'''
if old_groups_dict in s:
    s = s.replace(old_groups_dict, new_groups_dict)
    print("send.py groups_dict: OK")
else:
    print("send.py groups_dict: NOT FOUND")

# 3. Add negative_product_add handling in send_create_targets
old_neg_item = '''        elif et == "negative_add":
            item = {
                "adGroupId":  ag_id,
                "campaignId": camp_id,
                "negative":   True,
                "state":      "ENABLED",
                "targetDetails": {
                    "keywordTarget": {
                        "matchType": val.get("match_type", "NEGATIVE_EXACT"),
                        "keyword":   val["text"],
                    }
                }
            }
        else:
            continue'''
new_neg_item = '''        elif et == "negative_add":
            item = {
                "adGroupId":  ag_id,
                "campaignId": camp_id,
                "negative":   True,
                "state":      "ENABLED",
                "targetDetails": {
                    "keywordTarget": {
                        "matchType": val.get("match_type", "NEGATIVE_EXACT"),
                        "keyword":   val["text"],
                    }
                }
            }
        elif et == "negative_product_add":
            item = {
                "adGroupId":  ag_id,
                "campaignId": camp_id,
                "negative":   True,
                "state":      "ENABLED",
                "targetDetails": {
                    "productTarget": {
                        "product": {
                            "productId": val["asin"],
                            "productIdType": "ASIN",
                        }
                    }
                }
            }
        else:
            continue'''
if old_neg_item in s:
    s = s.replace(old_neg_item, new_neg_item)
    print("send.py negative_product_add: OK")
else:
    print("send.py negative_product_add: NOT FOUND")

# 4. Add send_create_ad_groups function (append before main)
if 'def send_create_ad_groups' not in s:
    # Find insertion point before main block
    insert_before = '\ndef main():'
    new_fn = '''
def send_create_ad_groups(endpoint, headers, changes, dry_run=False):
    """Создать новые группы объявлений"""
    payloads = []
    for c in changes:
        val = json.loads(c["new_value"])
        item = {
            "campaignId": val.get("campaign_id") or c["entity_id"],
            "name":       val["name"],
            "state":      "ENABLED",
            "bid":        {"defaultBid": float(val.get("default_bid", 0.5))},
        }
        payloads.append(item)

    if dry_run:
        print(f"  [DRY RUN] create/adGroups: {json.dumps(payloads, ensure_ascii=False)[:200]}")
        return {i: "SUCCESS" for i in range(len(changes))}

    resp = amz_post(endpoint, "/adsApi/v1/create/adGroups", headers, {"adGroups": payloads})
    return parse_multi_response(resp, "adGroups", len(changes))

'''
    if insert_before in s:
        s = s.replace(insert_before, new_fn + insert_before)
        print("send.py send_create_ad_groups: OK")
    else:
        print("send.py send_create_ad_groups: insert point not found")

# 5. Call send_create_ad_groups in main send loop
old_send_call = '''    if grouped["create_targets"]:
        results = send_create_targets(endpoint, headers, grouped["create_targets"], dry_run)
        for i, ch in enumerate(grouped["create_targets"]):
            r[ch["id"]] = results.get(i, "UNKNOWN")'''

new_send_call = '''    if grouped["create_targets"]:
        results = send_create_targets(endpoint, headers, grouped["create_targets"], dry_run)
        for i, ch in enumerate(grouped["create_targets"]):
            r[ch["id"]] = results.get(i, "UNKNOWN")

    if grouped.get("create_ad_groups"):
        results = send_create_ad_groups(endpoint, headers, grouped["create_ad_groups"], dry_run)
        for i, ch in enumerate(grouped["create_ad_groups"]):
            r[ch["id"]] = results.get(i, "UNKNOWN")'''

if old_send_call in s:
    s = s.replace(old_send_call, new_send_call)
    print("send.py create_ad_groups call: OK")
else:
    print("send.py create_ad_groups call: NOT FOUND")

with open(sp_path, 'w') as f:
    f.write(s)
print(f"send.py saved ({len(s)} chars)")
print("\nПатч применён успешно!")
