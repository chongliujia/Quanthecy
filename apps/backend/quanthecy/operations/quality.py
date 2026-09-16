"""Bounded operator view of persisted research eligibility; no history scans in HTTP."""

from collections import Counter
from typing import Any

from django.utils import timezone
from pydantic import ValidationError
from quanthecy_analytics.contracts.market import MarketObservation
from quanthecy_analytics.quality import ResearchQuality, research_quality

from quanthecy.markets.models import Market

from .console import tr

REASONS = {
    "insufficient_history": ("Insufficient continuous history", "连续历史样本不足"),
    "sampling_gap_or_invalid_quote": (
        "Sampling gap or excluded quality flag",
        "采样中断或质量标记不合格",
    ),
    "quality_flags_excluded": (
        "Observation quality flag excludes research",
        "观测含不合格质量标记",
    ),
    "incompatible_observations": (
        "Market, outcome or rules changed",
        "市场、结果或结算规则发生变化",
    ),
    "market_not_open": ("Market is not open", "市场不在交易中"),
    "missing_resolution_rules": ("Settlement rules missing", "缺少结算规则"),
    "invalid_recording_time": ("Recorded before receipt", "入库时间早于接收时间"),
    "missing_midpoint": ("No valid two-sided midpoint", "缺少有效双边报价中间价"),
    "unsupported_price_basis": ("Price is not a midpoint", "价格口径不是中间价"),
    "invalid_quote": ("Invalid or crossed bid/ask", "买卖报价无效或交叉"),
    "midpoint_mismatch": ("Midpoint disagrees with bid/ask", "中间价与买卖报价不一致"),
    "invalid_price_time": ("Price timestamp is invalid or stale", "报价时间无效或过期"),
    "missing_volume": ("Volume missing", "缺少成交量"),
    "invalid_volume": ("Invalid cumulative volume", "累计成交量无效"),
    "invalid_volume_time": ("Volume timestamp is invalid or stale", "成交量时间无效或过期"),
    "price_source_changed": ("Price source changed in window", "窗口内价格来源变化"),
    "volume_basis_changed": ("Volume unit or basis changed", "成交量单位或口径变化"),
    "volume_counter_reset": ("Cumulative volume counter reset", "累计成交量计数器回退"),
    "constant_volume_baseline": (
        "Volume baseline has no variation",
        "成交量基线无波动，无法计算 Z 分数",
    ),
    "invalid_volume_rate": ("Invalid volume change rate", "成交量变化率无效"),
    "future_observation": ("Observation timestamp is in the future", "观测时间位于未来"),
    "stale_observation": ("No observation in the past 180 seconds", "超过 180 秒未收到观测"),
    "quality_not_evaluated": ("Awaiting current quality policy", "等待新版质量规则评估"),
    "analytics_pending": ("New quote awaits window analysis", "新报价正在等待窗口分析"),
    "conflicting_duplicate": (
        "Conflicting copies of the same observation",
        "同一观测 ID 对应不同内容",
    ),
    "history_truncated": ("History query exceeded its bound", "历史查询超限，窗口不完整"),
    "invalid_stored_observation": (
        "Stored observation failed schema validation",
        "已存观测未通过结构校验",
    ),
    "source_time_missing": (
        "Exchange timestamp unavailable; receipt time used",
        "交易所时间缺失，使用本地接收时间",
    ),
    "liquidity_unavailable": ("Liquidity depth unavailable", "缺少流动性深度数据"),
}


def reason_label(code: str) -> str:
    return tr(*REASONS[code]) if code in REASONS else code


def quality_overview(*, platform: str, search: str, state: str, offset: int) -> dict[str, Any]:
    at = timezone.now()
    query = Market.objects.order_by("-last_observed_at", "id")
    if platform:
        query = query.filter(platform=platform)
    if search:
        query = query.filter(title__icontains=search)
    total = query.count()
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    rows = []
    checked = 0
    for market in query.only("id", "platform", "title", "latest", "metrics", "last_observed_at")[
        :1000
    ]:
        try:
            latest = MarketObservation.model_validate(market.latest).model_dump(mode="json")
            quality = research_quality(latest, market.metrics, at)
        except (ValidationError, ValueError, KeyError, TypeError):
            quality = ResearchQuality(
                checked_at=at,
                state="blocked",
                price_usable=False,
                volume_usable=False,
                reasons=["invalid_stored_observation"],
                limitations=[],
                age_seconds=None,
            )
        checked += 1
        counts[quality.state] += 1
        reasons.update(quality.reasons)
        if not state or quality.state == state:
            rows.append(
                {
                    "market": market,
                    "quality": quality,
                    "reasons": [reason_label(code) for code in quality.reasons],
                    "limitations": [reason_label(code) for code in quality.limitations],
                }
            )
    return {
        "checked_at": at,
        "total": total,
        "checked": checked,
        "truncated": total > checked,
        "counts": {key: counts[key] for key in ("ready", "limited", "blocked")},
        "issues": [
            {"label": reason_label(code), "count": count} for code, count in reasons.most_common()
        ],
        "rows": rows[offset : offset + 50],
        "matched": len(rows),
        "has_next": len(rows) > offset + 50,
    }
