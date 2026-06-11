from google.cloud import bigquery

_client = None

def get_client():
    global _client
    if _client is None:
        _client = bigquery.Client(project='amazon-ads-api-494412')
    return _client