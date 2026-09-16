from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from quanthecy.markets.models import CollectionTarget, Market, ResearchTopic
from quanthecy.research.events import append_definition, sync_event_candidates
from quanthecy.research.models import EventDefinition, EventMarketLink, ResearchEvent
from quanthecy.research.reviews import snapshot


class Command(BaseCommand):
    help = "Initialize the October 2026 Fed event; no evidence is approved."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        topic = ResearchTopic.objects.filter(slug="fed-october-2026", is_public=True).first()
        if not topic:
            raise CommandError("Import the public fed-october-2026 collection topic first.")
        event, _ = ResearchEvent.objects.get_or_create(
            slug="fed-october-2026", defaults={"topic": topic}
        )
        ResearchEvent.objects.select_for_update().get(pk=event.pk)
        if not event.definitions.exists():
            append_definition(
                EventDefinition(
                    event=event,
                    title="Federal Reserve · October 2026 policy decision",
                    title_zh="美联储 · 2026 年 10 月利率决议",
                    scope=(
                        "Research the scheduled October 27–28 FOMC meeting. Each linked contract "
                        "has its own outcome and settlement rules. Calendar dates are a recorded "
                        "schedule, subject to official revision. Earlier statements and individual "
                        "speeches are candidates for background; they do not establish the October "
                        "outcome. Source-page text excludes linked PDFs and full minutes "
                        "attachments."
                    ),
                    scope_zh=(
                        "研究计划于 10 月 27–28 日召开的 FOMC 会议。"
                        "每份合约的结果定义与结算规则分别核对。日程为当前记录，仍可能由官方调整。"
                        "此前声明和官员讲话先作为背景候选，不代表十月结果。"
                        "已采集的网页正文不包含链接中的 PDF 或完整会议纪要附件。"
                    ),
                    starts_on=date(2026, 10, 27),
                    ends_on=date(2026, 10, 28),
                    calendar_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                    source_slugs=["fed-monetary", "fed-speeches"],
                )
            )
        count = 0
        for target in CollectionTarget.objects.filter(topic=topic, enabled=True).order_by(
            "platform", "exchange_id"
        ):
            market = (
                Market.objects.select_for_update()
                .filter(platform=target.platform, exchange_id=target.exchange_id)
                .first()
            )
            if market:
                _, added = EventMarketLink.objects.get_or_create(
                    event=event, market=market, defaults={"snapshot": snapshot(market)}
                )
                count += int(added)
        candidates = sync_event_candidates()
        self.stdout.write(
            f"Event ready: {count} new contract links, {candidates} new pending candidates. "
            "No human review was created."
        )
