CREATE TABLE IF NOT EXISTS market_observations
(
    collector_id UUID,
    batch_id UInt64,
    observation_id UUID,
    platform LowCardinality(String),
    market_id UUID,
    outcome_id UUID,
    received_at DateTime64(6, 'UTC'),
    probability Nullable(Float64),
    best_bid Nullable(Float64),
    best_ask Nullable(Float64),
    volume Nullable(Float64),
    volume_unit LowCardinality(String),
    quality_flags Array(String),
    envelope String CODEC(ZSTD),
    raw_payload String CODEC(ZSTD)
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(received_at)
ORDER BY (market_id, received_at, observation_id);

CREATE TABLE IF NOT EXISTS ingestion_batches
(
    collector_id UUID,
    batch_id UInt64,
    row_count UInt32,
    committed_at DateTime64(6, 'UTC')
)
ENGINE = ReplacingMergeTree
ORDER BY (collector_id, batch_id);

CREATE TABLE IF NOT EXISTS signals
(
    signal_id UUID,
    market_id UUID,
    outcome_id UUID,
    received_at DateTime64(6, 'UTC'),
    signal_type LowCardinality(String),
    score Float64,
    report String CODEC(ZSTD)
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(received_at)
ORDER BY (market_id, received_at, signal_id);
