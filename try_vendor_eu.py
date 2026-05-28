import requests, json

BASE_DIR = "/home/nikolaenkots/amazon-ads"
with open(f"{BASE_DIR}/config/amazon_secrets.json") as f:
    AMZ = json.load(f)

resp = requests.post(
    "https://api.amazon.com/auth/o2/token",
    data={
        "grant_type":    "refresh_token",
        "refresh_token": AMZ["refresh_token"],
        "client_id":     AMZ["client_id"],
        "client_secret": AMZ["client_secret"],
    }
)
token = resp.json()["access_token"]
headers = {
    "Authorization":                   f"Bearer {token}",
    "Amazon-Advertising-API-ClientId":  AMZ["client_id"],
}

# Пробуем EU /v2/profiles с фильтром по типу vendor
print("=== EU profiles with type filter ===")
for type_filter in ["vendor", "seller"]:
    r = requests.get(
        "https://advertising-api-eu.amazon.com/v2/profiles",
        params={"accountTypeFilter": type_filter},
        headers=headers
    )
    print(f"\ntype={type_filter}: status={r.status_code}")
    for p in r.json() if isinstance(r.json(), list) else []:
        ai = p.get("accountInfo", {}) or {}
        print(f"  {p.get('profileId')} | {p.get('countryCode')} | {ai.get('type')} | {ai.get('subType')} | {ai.get('name')} | {ai.get('id')}")

# Пробуем через managerAccounts EU endpoint
print("\n=== managerAccounts EU ===")
r = requests.get("https://advertising-api-eu.amazon.com/managerAccounts", headers=headers)
print(f"status={r.status_code}")
print(json.dumps(r.json(), indent=2, default=str)[:2000])
