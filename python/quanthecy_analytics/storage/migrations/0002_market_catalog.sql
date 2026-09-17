CREATE TABLE IF NOT EXISTS market_catalog_pages
(
    collector_id UUID,
    page_id UInt64,
    received_at DateTime64(6, 'UTC'),
    envelope String CODEC(ZSTD)
)
ENGINE = ReplacingMergeTree
ORDER BY (collector_id, page_id);
