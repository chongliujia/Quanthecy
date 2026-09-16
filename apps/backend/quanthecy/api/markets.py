from datetime import datetime
from typing import Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from ninja import Query, Router

from quanthecy.markets import services
from quanthecy.markets.collection import collection_status
from quanthecy.markets.schemas import (
    CollectionStatus,
    HistoryPage,
    MarketDetail,
    MarketPage,
    SignalOut,
)

router = Router(tags=["Markets"])


@router.get("/collection/status", response=CollectionStatus)
def collection(request: HttpRequest) -> CollectionStatus:
    return collection_status()


@router.get("/markets", response=MarketPage)
def markets(
    request: HttpRequest,
    platform: Literal["polymarket", "kalshi"] | None = None,
    search: str = Query("", max_length=200),
    topic: str = Query("", max_length=50),
    sort: Literal["recent", "movement", "volume_anomaly"] = "recent",
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=100),
) -> MarketPage:
    return services.list_markets(
        platform=platform, search=search, sort=sort, offset=offset, limit=limit, topic=topic
    )


@router.get("/markets/{market_id}", response=MarketDetail)
def market(request: HttpRequest, market_id: UUID, cutoff: datetime | None = None) -> MarketDetail:
    return services.market_detail(market_id, cutoff)


@router.get("/markets/{market_id}/history", response=HistoryPage)
def history(
    request: HttpRequest,
    market_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(1000, ge=1, le=10000),
) -> HistoryPage:
    return services.market_history(market_id, start, end, limit)


@router.get("/markets/{market_id}/signals", response=list[SignalOut])
def signals(
    request: HttpRequest, market_id: UUID, cutoff: datetime | None = None
) -> list[SignalOut]:
    return services.market_signals(market_id, cutoff)


def download(data: bytes, name: str, file_format: str) -> HttpResponse:
    content_type = (
        "text/csv; charset=utf-8" if file_format == "csv" else "application/vnd.apache.parquet"
    )
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}.{file_format}"'
    response["Cache-Control"] = "private, no-store"
    return response


@router.get("/markets/{market_id}/export")
def export(
    request: HttpRequest,
    market_id: UUID,
    format: Literal["csv", "parquet"] = "csv",
    start: datetime | None = None,
    end: datetime | None = None,
) -> HttpResponse:
    return download(
        services.export_history(market_id, start, end, format), f"market-{market_id}", format
    )


@router.get("/signals/{signal_id}/inputs")
def signal_inputs(
    request: HttpRequest, signal_id: UUID, format: Literal["csv", "parquet"] = "csv"
) -> HttpResponse:
    return download(services.export_signal(signal_id, format), f"signal-{signal_id}-inputs", format)
