import type { Signal } from './marketTypes'

export type Source = { slug: string; name: string; url: string; last_checked_at: string | null; last_success_at: string | null; error: string; kind: 'OFFICIAL' | 'MEDIA' | 'UNKNOWN'; enabled: boolean; poll_interval_seconds: number; next_poll_at: string; status: 'paused' | 'pending' | 'healthy' | 'partial' | 'empty' | 'retrying' | 'stale'; last_entry_count: number; last_rejected_count: number; last_duplicate_count: number; last_undated_count: number; latest_published_at: string | null }
export type SourcePage = { sources: Source[]; polling_enabled: boolean }
export type Overview = { markets: number; fresh_markets: number; reviewed_pairs: number; evidence_items: number; latest_observation: string | null; sources: Source[]; news_polling_enabled: boolean }
export type FrozenMarket = { platform: string; exchange_id: string; source: string; observation_id: string;
  market: { id: string; title: string; rules_version: string; resolution_rules: string; closes_at: string | null; resolution_source: string | null };
  outcome: { id: string; label: string } }
export type Review = { id: string; comparison_id: string; title: string; topic: string; version: number; relation: 'EQUIVALENT' | 'RELATED' | 'INCOMPATIBLE'; alignment: 'SAME' | 'COMPLEMENT'; confidence: number; rationale: string; differences: string; reviewer_label: string; reviewed_at: string; left_snapshot: FrozenMarket; right_snapshot: FrozenMarket }
export type Quote = { observation_id: string; received_at: string; recorded_at: string; probability: number | null; bid: number | null; ask: number | null; basis: string | null; source: string | null; quality_flags: string[] }
export type Point = { at: string; left: Quote | null; right: Quote | null; difference: number | null; skew_seconds: number | null; issues: string[]; review_version: number | null }
export type Comparison = { review: Review; revisions: Review[]; cutoff: string; current: Point; history: Point[]; max_age_seconds: number; max_skew_seconds: number }
export type DocumentSummary = { title: string; kind: 'MONETARY_RELEASE' | 'SPEECH'; url: string; observed_at: string; extractor_version: string; text_sha256: string; raw_sha256: string; character_count: number }
export type OfficialDocument = Omit<DocumentSummary, 'character_count'> & { text: string }
export type DocumentCollection = { state: 'pending' | 'available' | 'retrying' | 'disabled' | 'unsupported'; last_checked_at: string | null; last_success_at: string | null; next_poll_at: string; error: string }
export type Evidence = { id: string; revision_id: string; version: number; source_slug: string; source_name: string; source_kind?: 'OFFICIAL' | 'MEDIA' | 'UNKNOWN'; quality_flags?: string[]; document_supported?: boolean; title: string; excerpt: string; url: string; published_at: string | null; first_observed_at: string; observed_at: string; content_hash: string; document?: DocumentSummary | null }
export type EvidenceLink = { id: string; market_id: string; status: 'TOPIC_ONLY' | 'REVIEWED' | 'REJECTED'; rationale: string; method: string; created_at: string }
export type EvidenceDetail = { item: Evidence; revisions: Evidence[]; links: EvidenceLink[]; cutoff: string; document?: OfficialDocument | null; document_collection?: DocumentCollection | null }
export type Timeline = { items: { evidence: Evidence; association: EvidenceLink }[]; cutoff: string; truncated: boolean }
export type FeedSignal = Signal & { market_id: string; market_title: string; platform: string; score: number; parameters: Record<string, number> }
