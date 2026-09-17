"""Best-effort liveness. Redis outages do not stop durable news collection."""

from datetime import datetime

from django.conf import settings
from django.utils import timezone
from redis import Redis

NEWS_KEY = "worker:news:heartbeat:v1"


def news_heartbeat(*, publish: bool = False) -> datetime | None:
    try:
        with Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=0.3, socket_timeout=0.3
        ) as cache:
            if publish:
                at = timezone.now()
                cache.set(NEWS_KEY, at.isoformat(), ex=90)
                return at
            raw = cache.get(NEWS_KEY)
        if isinstance(raw, (str, bytes)):
            at = datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw)
            if at.tzinfo is not None and 0 <= (timezone.now() - at).total_seconds() <= 90:
                return at
    except Exception:
        pass
    return None
