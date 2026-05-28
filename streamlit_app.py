import streamlit as st
import pandas as pd
import requests
from google.cloud import bigquery
import os

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.expanduser("~/amazon-ads/config/bigquery_key.json")

PROJECT_ID = "amazon-ads-api-494412"
client = bigquery.Client(project=PROJECT_ID)

st.set_page_config(page_title="Amazon Ads Manager", layout="wide")

# ── Навигация ──────────────────────────────────────────────
page = st.sidebar.selectbox("Страница", ["Portfolios", "Campaigns"])

# ── Portfolios ─────────────────────────────────────────────
if page == "Portfolios":
    st.title("Portfolios")

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🔄 Sync"):
            r = requests.post("https://nikolaenkots.pythonanywhere.com/portfolios/sync")
            data = r.json()
            st.success(f"Добавлено: {data.get('inserted')}, всего: {data.get('total')}")

    df = client.query("""
        SELECT portfolio_id, account_type, marketplace, portfolio_name, notes
        FROM `amazon-ads-api-494412.amazon_ads.portfolio_labels`
        ORDER BY account_type, marketplace, portfolio_name
    """).to_dataframe()

    edited = st.data_editor(
        df,
        use_container_width=True,
        disabled=["portfolio_id", "account_type", "marketplace"],
        hide_index=True,
        key="portfolios_editor"
    )

    if st.button("💾 Save changes"):
        changes = []
        for i, row in edited.iterrows():
            orig = df.iloc[i]
            if row["portfolio_name"] != orig["portfolio_name"] or row["notes"] != orig["notes"]:
                changes.append({
                    "portfolio_id":   str(row["portfolio_id"]),
                    "account_type":   str(row["account_type"]),
                    "marketplace":    str(row["marketplace"]),
                    "portfolio_name": str(row["portfolio_name"] or ""),
                    "notes":          str(row["notes"] or "")
                })

        if changes:
            r = requests.post(
                "https://nikolaenkots.pythonanywhere.com/portfolios/bulk-update",
                json={"changes": changes}
            )
            st.success(f"Сохранено: {len(changes)} изменений")
        else:
            st.info("Нет изменений")