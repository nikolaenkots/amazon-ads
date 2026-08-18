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

# Маппинг marketplaceId → страна
MARKETPLACE_MAP = {
    "APJ6JRA9NG5V4":  "IT",
    "A1RKKUPIHCS9HS": "ES",
    "A1F83G8C2AR07P": "UK",
    "A1PA6795UKMFR9": "DE",
    "A13V1IB3VIYZZH": "FR",
    "ATVPDKIKX0DER":  "US",
    "A2EUQ1WTGCTBG2": "CA",
}

r = requests.get("https://advertising-api-eu.amazon.com/managerAccounts", headers=headers)
print("Merch EU profiles (VENDOR type, Nikolaienko Artem):")
for ma in r.json().get("managerAccounts", []):
    for acc in ma.get("linkedAccounts", []):
        if acc.get("accountType") == "VENDOR" and acc.get("accountName") == "Nikolaienko Artem":
            mkt = MARKETPLACE_MAP.get(acc.get("marketplaceId", ""), acc.get("marketplaceId"))
            print(f"  {mkt:3} | profileId: {acc.get('profileId'):20} | entityId: {acc.get('accountId')}")
