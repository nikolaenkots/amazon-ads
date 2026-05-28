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

for profile in [
    {"marketplace": "UK", "profileId": "180261448232436"},
    {"marketplace": "FR", "profileId": "613747068444603"},
]:
    headers = {
        "Authorization":                   f"Bearer {token}",
        "Amazon-Advertising-API-ClientId":  AMZ["client_id"],
        "Amazon-Advertising-API-Scope":     profile["profileId"],
        "Content-Type":                     "application/vnd.createasyncreportrequest.v3+json"
    }
    body = {
        "name":      f"test Merch {profile['marketplace']}",
        "startDate": "2026-04-20",
        "endDate":   "2026-04-20",
        "configuration": {
            "adProduct":    "SPONSORED_PRODUCTS",
            "reportTypeId": "spCampaigns",
            "groupBy":      ["campaign"],
            "timeUnit":     "SUMMARY",
            "format":       "GZIP_JSON",
            "columns":      ["campaignId", "impressions", "clicks", "cost"]
        }
    }
    r = requests.post(
        "https://advertising-api-eu.amazon.com/reporting/reports",
        headers=headers, json=body
    )
    print(f"{profile['marketplace']}: status={r.status_code} | {r.json().get('reportId', r.json().get('message', ''))}")
