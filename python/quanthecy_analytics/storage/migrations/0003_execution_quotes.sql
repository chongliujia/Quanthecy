CREATE TABLE IF NOT EXISTS execution_quotes
(
    quote_id UUID,
    market_id UUID,
    platform LowCardinality(String),
    received_at DateTime64(6, 'UTC'),
    envelope String
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(received_at)
ORDER BY (market_id, received_at, quote_id);
