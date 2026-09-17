import copy
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.test import Client
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.markets.ingestion import reconcile
from quanthecy.markets.models import Market, ResearchTopic
from quanthecy.research.event_charts import event_chart
from quanthecy.research.events import append_definition
from quanthecy.research.models import EventDefinition, EventMarketLink, ResearchEvent
from quanthecy.research.reviews import snapshot
from quanthecy_analytics.event_chart import align_contract
from quanthecy_analytics.signals import analyze


def observation(at, price=0.4):
    row = json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )[0]
    row.update(observation_id=str(uuid4()), received_at=at.isoformat(), recorded_at=at.isoformat())
    row["probability"].update(value=price, as_of=at.isoformat())
    row.update(best_bid=price - 0.01, best_ask=price + 0.01)
    row["volume"]["as_of"] = at.isoformat()
    return row


def test_alignment_is_backward_only_and_leaves_gaps():
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    rows = [
        observation(start + timedelta(seconds=20)),
        observation(start + timedelta(seconds=250), 0.7),
    ]
    points = align_contract(rows, start=start, end=start + timedelta(minutes=5))
    assert [p["probability"] for p in points] == [None, 0.4, None, None, None, 0.7]
    assert points[1]["observed_at"] == start + timedelta(seconds=20)
    assert points[2]["issue"] == "stale"


def test_late_recording_future_quotes_and_invalid_latest_do_not_leak():
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    first = observation(start)
    late = observation(start + timedelta(seconds=30), 0.5)
    late["recorded_at"] = (start + timedelta(seconds=75)).isoformat()
    crossed = observation(start + timedelta(seconds=130), 0.6)
    crossed["best_bid"] = 0.8
    future = observation(start + timedelta(minutes=10), 0.9)
    points = align_contract(
        [future, crossed, late, first], start=start, end=start + timedelta(minutes=3)
    )
    assert [p["probability"] for p in points] == [0.4, 0.4, 0.5, None]
    assert points[-1]["issue"] == "invalid_quote"


@pytest.mark.parametrize("kind", ["contract_changed", "closed", "source_stale", "gap"])
def test_unsafe_quotes_remain_blank(kind):
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    row = observation(start)
    if kind == "contract_changed":
        row[kind] = True
    elif kind == "closed":
        row["market"]["status"] = "CLOSED"
    elif kind == "source_stale":
        row["probability"]["as_of"] = (start - timedelta(seconds=91)).isoformat()
    else:
        row["quality_flags"].append("GAP")
    assert align_contract([row], start=start, end=start)[0]["probability"] is None


@pytest.fixture
def linked_event(db):
    now = timezone.now()
    row = observation(now - timedelta(seconds=10))
    with transaction.atomic():
        reconcile(row, analyze([row])[0])
    market = Market.objects.get()
    topic = ResearchTopic.objects.create(slug="chart-fed", name="Fed")
    event = ResearchEvent.objects.create(slug="chart-fed", topic=topic)
    append_definition(
        EventDefinition(
            event=event,
            title="Fed meeting",
            source_slugs=["fed-monetary"],
            scope="Related contracts, not an exhaustive partition.",
            starts_on=date(2026, 10, 27),
            ends_on=date(2026, 10, 28),
            calendar_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        )
    )
    link = EventMarketLink.objects.create(event=event, market=market, snapshot=snapshot(market))
    return event, link, row


def test_chart_respects_scope_cutoff_and_frozen_rules(linked_event):
    event, link, row = linked_event
    repo = Mock()
    repo.history.return_value = [row]
    with patch("quanthecy.research.event_charts.history_repository", return_value=repo):
        end = timezone.now()
        result = event_chart(event.slug, end, 1, "polymarket", str(link.market_id))
        assert result.series[0].points[-1].probability == 0.4
        assert result.contracts[0].title == row["market"]["title"]
        assert repo.history.call_args.kwargs["known_at"] == end.isoformat()
        assert repo.history.call_args.kwargs["limit"] == 3001
        before_link = link.created_at - timedelta(microseconds=1)
        assert event_chart(event.slug, before_link, 1, "", "").series == []
        changed = copy.deepcopy(row)
        changed["market"]["rules_version"] = "revised"
        repo.history.return_value = [changed]
        result = event_chart(event.slug, None, 1, "", "")
        assert result.series[0].points[-1].issue == "contract_changed"
        assert result.series[0].points[-1].probability is None
        event.topic.is_public = False
        event.topic.save()
        with pytest.raises(Http404):
            event_chart(event.slug, None, 1, "", "")


def test_chart_rejects_unlinked_duplicate_wrong_platform_and_reports_truncation(linked_event):
    event, link, row = linked_event
    repo = Mock()
    repo.history.return_value = [row] * 3001
    with patch("quanthecy.research.event_charts.history_repository", return_value=repo):
        for ids, platform in [
            (str(uuid4()), ""),
            (f"{link.market_id},{link.market_id}", ""),
            (str(link.market_id), "kalshi"),
            ("bad", ""),
        ]:
            with pytest.raises(ValidationError):
                event_chart(event.slug, None, 1, platform, ids)
        assert not repo.history.called
        assert event_chart(event.slug, None, 1, "", "").series[0].truncated


def test_chart_api_auth_and_parameter_bounds(linked_event):
    event, _, row = linked_event
    client = Client()
    url = f"/api/v1/research/events/{event.slug}/chart"
    assert client.get(url).status_code == 401
    client.force_login(User.objects.create_user("chart@example.com", "test-only-password"))
    assert client.get(url, {"hours": 25}).status_code == 422
    assert client.get(url, {"platform": "unknown"}).status_code == 422
    assert (
        client.get(url, {"market_ids": ",".join(str(uuid4()) for _ in range(7))}).status_code == 422
    )
    with patch("quanthecy.research.event_charts.history_repository") as factory:
        factory.return_value.history.return_value = [row]
        response = client.get(url, {"hours": 1})
        assert response.status_code == 200
        body = response.json()
        assert body["step_seconds"] == 60 and body["max_age_seconds"] == 90
        assert 60 <= len(body["series"][0]["points"]) <= 62
        assert body["series"][0]["points"][-1]["probability"] == 0.4
