-- Схема таблиц статистики по плейсментам (Sponsored Products spCampaigns / campaignPlacement).
-- Заполняются скриптом collect_placements.py, используются страницей /automation/placements.
-- Выполнить один раз в BigQuery (проект amazon-ads-api-494412).

CREATE TABLE IF NOT EXISTS `amazon-ads-api-494412.amazon_ads.placement_stats_merch` (
  date          DATE,
  profile_id    STRING,
  marketplace   STRING,
  campaign_id   STRING,
  campaign_name STRING,
  placement     STRING,   -- placementClassification: "Top of Search on-Amazon" / "Detail Page on-Amazon" / "Other on-Amazon" / "Off Amazon"
  impressions   INT64,
  clicks        INT64,
  cost          FLOAT64,
  purchases_7d  INT64,
  sales_7d      FLOAT64,
  loaded_at     TIMESTAMP
) PARTITION BY date CLUSTER BY profile_id, campaign_id;

CREATE TABLE IF NOT EXISTS `amazon-ads-api-494412.amazon_ads.placement_stats_kdp` (
  date          DATE,
  profile_id    STRING,
  marketplace   STRING,
  campaign_id   STRING,
  campaign_name STRING,
  placement     STRING,
  impressions   INT64,
  clicks        INT64,
  cost          FLOAT64,
  purchases_7d  INT64,
  sales_7d      FLOAT64,
  loaded_at     TIMESTAMP
) PARTITION BY date CLUSTER BY profile_id, campaign_id;
