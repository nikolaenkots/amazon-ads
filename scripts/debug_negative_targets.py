import json, os, requests
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/nikolaenkots/amazon-ads/config/bigquery_key.json"

with open("/home/nikolaenkots/amazon-ads/config/amazon_secrets.json") as f:
    AMZ = json.load(f)

r = requests.post("https://api.amazon.com/auth/o2/token", data={
    "grant_type": "refresh_token",
    "refresh_token": AMZ["refresh_token"],
    "client_id": AMZ["client_id"],
    "client_secret": AMZ["client_secret"],
})
token = r.json()["access_token"]

profile = next(p for p in AMZ["profiles"] if p["type"] == "KDP" and p["marketplace"] == "US")
headers = {
    "Authorization": f"Bearer {token}",
    "Amazon-Advertising-API-ClientId": AMZ["client_id"],
    "Amazon-Advertising-API-Scope": str(profile["id"]),
    "Content-Type": "application/json",
}
endpoint = profile.get("api_endpoint", "https://advertising-api.amazon.com")
campaign_id = "222098592884072"

# ── 1. Собрать ВСЕ таргеты с пагинацией ─────────────────
print("=== /query/targets (all pages) ===")
all_targets = []
next_token = None
while True:
    body = {
        "adProductFilter": {"include": ["SPONSORED_PRODUCTS"]},
        "campaignIdFilter": {"include": [campaign_id]},
        "negativeFilter": {"include": [True]},
        "maxResults": 100,
    }
    if next_token:
        body["nextToken"] = next_token
    resp = requests.post(f"{endpoint}/adsApi/v1/query/targets", headers=headers, json=body)
    data = resp.json()
    batch = data.get("targets", [])
    all_targets.extend(batch)
    next_token = data.get("nextToken")
    if not next_token:
        break

product_negs = [t for t in all_targets if t.get("targetType") != "KEYWORD"]
kw_negs      = [t for t in all_targets if t.get("targetType") == "KEYWORD"]
print(f"Total: {len(all_targets)} | Keywords: {len(kw_negs)} | Product: {len(product_negs)}")
if product_negs:
    for t in product_negs[:3]:
        print(json.dumps(t, indent=2))

# ── 2. Попробовать /query/negativeTargets ────────────────
print("\n=== /query/negativeTargets ===")
resp2 = requests.post(f"{endpoint}/adsApi/v1/query/negativeTargets", headers=headers, json={
    "adProductFilter": {"include": ["SPONSORED_PRODUCTS"]},
    "campaignIdFilter": {"include": [campaign_id]},
    "maxResults": 20,
})
print(f"Status: {resp2.status_code}")
if resp2.status_code == 200:
    data2 = resp2.json()
    neg_targets = data2.get("negativeTargets", data2.get("targets", []))
    print(f"Found: {len(neg_targets)}")
    for t in neg_targets[:3]:
        print(json.dumps(t, indent=2))
else:
    print(resp2.text[:300])

# ── 3. Проверить group-level через adGroupIdFilter ───────
print("\n=== All groups for this campaign ===")
resp3 = requests.post(f"{endpoint}/adsApi/v1/query/adGroups", headers=headers, json={
    "adProductFilter": {"include": ["SPONSORED_PRODUCTS"]},
    "campaignIdFilter": {"include": [campaign_id]},
    "maxResults": 20,
})
groups = resp3.json().get("adGroups", [])
print(f"Ad groups: {[g.get('adGroupId') for g in groups]}")