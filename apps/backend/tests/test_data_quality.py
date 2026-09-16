import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from django.contrib.auth.models import Permission
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from quanthecy.accounts.models import User
from quanthecy.agents.context import build_context
from quanthecy.markets.ingestion import reconcile
from quanthecy.markets.models import Market
from quanthecy_analytics.signals import analyze

pytestmark = pytest.mark.django_db


@pytest.fixture
def rows():
    values = json.loads(
        (Path(__file__).resolve().parents[3] / "tests/fixtures/research-window.json").read_text()
    )
    with transaction.atomic():
        reconcile(values[-1], analyze(values)[0])
    return values


def test_quality_console_permissions_bilingual_filters_and_corrupt_record(rows):
    actor = User.objects.create_user("quality@example.com", is_staff=True)
    client = Client()
    client.force_login(actor)
    url = reverse("platform_ops:data_quality")
    assert client.get(url).status_code == 403
    actor.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="operations", codename="view_collection_status"
        )
    )
    response = client.get(url)
    assert response.status_code == 200
    assert "数据质量" in response.content.decode()
    assert response.context_data["report"]["counts"]["blocked"] == 1
    assert "超过 180 秒" in response.content.decode()
    client.cookies["quanthecy_admin_language"] = "en"
    response = client.get(url + "?state=blocked")
    assert b"Data quality" in response.content
    assert response.context_data["report"]["matched"] == 1
    assert client.get(url + "?platform=kalshi").context_data["report"]["checked"] == 0
    assert client.get(url + "?state=invalid").status_code == 400
    assert client.get(url + "?offset=-1").status_code == 400
    Market.objects.update(latest={})
    assert b"failed schema validation" in client.get(url).content


def test_agent_cannot_forecast_with_bad_historical_price_even_when_latest_is_valid(rows):
    rows[5]["probability"] = None
    repository = Mock()
    repository.history.return_value = rows
    news = Mock(items=[Mock()], truncated=False)
    news.items[0].evidence.revision_id = UUID("12345678-1234-5678-1234-567812345678")
    news.items[0].evidence.title = "Fixture evidence"
    news.items[0].evidence.url = "https://example.com/evidence"
    news.items[0].evidence.excerpt = "Fixture evidence excerpt"
    news.items[0].model_dump.return_value = {"evidence": {"excerpt": "Fixture evidence excerpt"}}
    with (
        patch("quanthecy.agents.context.history_repository", return_value=repository),
        patch("quanthecy.agents.context.timeline", return_value=news),
        patch("quanthecy.agents.context.comparisons", return_value=[]),
    ):
        context = build_context(
            Market.objects.get().id, datetime.fromisoformat(rows[-1]["recorded_at"])
        )
    assert not context["quality"]["forecast_eligible"]
    assert "missing_midpoint" in context["quality"]["data"]["reasons"]


def test_faster_cache_cannot_borrow_quality_from_older_window(rows):
    market = Market.objects.get()
    client = Client()
    client.force_login(User.objects.create_user("reader@example.com"))
    newer = copy.deepcopy(rows[-1])
    newer["observation_id"] = rows[0]["observation_id"]
    now = timezone.now().replace(microsecond=0)
    for key in ("received_at", "recorded_at"):
        newer[key] = now.isoformat().replace("+00:00", "Z")
    newer["probability"]["as_of"] = newer["received_at"]
    newer["volume"]["as_of"] = newer["received_at"]
    with patch("quanthecy.markets.services.Redis.from_url") as cache:
        cache.return_value.__enter__.return_value.get.return_value = json.dumps(newer)
        response = client.get(f"/api/v1/markets/{market.id}")
    assert response.status_code == 200 and response.json()["live_cache"]
    quality = response.json()["data_quality"]
    assert quality["state"] == "blocked" and "analytics_pending" in quality["reasons"]


def test_future_market_not_counted_as_fresh_or_ranked(rows):
    client = Client()
    client.force_login(User.objects.create_user("future-reader@example.com"))
    Market.objects.update(last_observed_at=timezone.now() + timedelta(hours=1))
    with patch("quanthecy.markets.collection.Redis.from_url", side_effect=OSError):
        status = client.get("/api/v1/collection/status").json()["sources"][0]
    assert status["state"] == "delayed" and status["fresh_markets"] == 0
    assert client.get("/api/v1/markets?sort=movement").json()["total"] == 0
