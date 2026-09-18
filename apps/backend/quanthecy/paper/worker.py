import logging
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from quanthecy_analytics.assistant import EXPERIMENT_VERSION as ASSISTANT_EXPERIMENT
from quanthecy_analytics.paper import VERSION, ExecutionQuote
from quanthecy_analytics.paper_review import EXPERIMENT_VERSION

from .accounting import execute_order, mark_equity, settle
from .models import Experiment
from .repository import ExecutionRepository
from .reviews import schedule_reviews
from .services import execution_market_ids, publish_execution_universe
from .strategy import decide

logger = logging.getLogger(__name__)


@transaction.atomic
def process_experiment(
    experiment_id: UUID, quotes: dict[UUID, ExecutionQuote], now: datetime
) -> None:
    experiment = (
        Experiment.objects.select_for_update(skip_locked=True).filter(id=experiment_id).first()
    )
    if experiment is None:
        return
    if experiment.version not in {VERSION, EXPERIMENT_VERSION, ASSISTANT_EXPERIMENT}:
        raise ValueError("Unsupported paper policy version")
    targets = list(experiment.universe.select_related("market", "market__event"))
    # Prevent a mismapped public quote from affecting any account.
    for target in targets:
        quote = quotes.get(target.market_id)
        if quote and (
            quote.platform != target.market.platform
            or quote.exchange_id != target.market.exchange_id
            or quote.outcome_id != target.market.latest["outcome"]["exchange_id"]
        ):
            raise ValueError("Execution quote identity mismatch")
    for account in experiment.accounts.select_related(
        "experiment", "experiment__organization", "assistant_version"
    ).order_by("id"):
        settle(account, quotes, now)
        if experiment.running:
            for order in (
                account.orders.filter(status="PENDING")
                .select_related("market")
                .order_by("eligible_at", "id")
            ):
                target = next(row for row in targets if row.market_id == order.market_id)
                if target.rules_version != order.market.latest["market"]["rules_version"]:
                    order.status, order.reason, order.finished_at = (
                        "CANCELLED",
                        "rules_changed",
                        now,
                    )
                    order.save()
                else:
                    execute_order(order, account, quotes.get(order.market_id), now)
            for target in targets:
                if target.market.platform == account.platform:
                    decide(account, target, quotes.get(target.market_id), now)
        mark_equity(account, quotes, now)
    experiment.checked_at, experiment.error_code = now, ""
    experiment.save(update_fields=["checked_at", "error_code"])


def run_once(repository: ExecutionRepository | None = None) -> int:
    publish_execution_universe()
    now = timezone.now()
    quotes = (repository or ExecutionRepository()).latest(execution_market_ids(), now)
    processed = 0
    for experiment_id in Experiment.objects.order_by("created_at").values_list("id", flat=True)[
        :100
    ]:
        try:
            process_experiment(experiment_id, quotes, timezone.now())
            processed += 1
        except Exception:
            logger.exception("Paper experiment failed; account transaction rolled back")
            Experiment.objects.filter(id=experiment_id).update(error_code="processing_failed")
    schedule_reviews()
    return processed
