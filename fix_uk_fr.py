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

# Маппинг marketplaceId
MARKETPLACE_MAP = {
    "APJ6JRA9NG5V4":  "IT",
    "A1RKKUPIHCS9HS": "ES",
    "A1F83G8C2AR07P": "UK",
    "A1PA6795UKMFR9": "DE",
    "A13V1IB3VIYZZH": "FR",
    "A2MFUE2XK8ZSSY": "FR_alt",
    "A1AM78C64UM0Y8": "MX",
    "ATVPDKIKX0DER":  "US",
}

# Полный вывод всех аккаунтов Nikolaienko Artem из EU managerAccounts
r = requests.get("https://advertising-api-eu.amazon.com/managerAccounts", headers=headers)
print("ALL linked accounts (EU):")
for ma in r.json().get("managerAccounts", []):
    for acc in ma.get("linkedAccounts", []):
        if "Nikolaienko" in (acc.get("accountName") or ""):
            mkt_id = acc.get("marketplaceId", "")
            mkt    = MARKETPLACE_MAP.get(mkt_id, mkt_id)
            print(f"  {mkt:15} | profileId: {acc.get('profileId'):20} | type: {acc.get('accountType'):8} | entity: {acc.get('accountId')}")
