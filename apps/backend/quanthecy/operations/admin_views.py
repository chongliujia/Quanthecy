from datetime import timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods
from quanthecy_analytics.storage.clickhouse import AnalyticsUnavailable

from quanthecy.api.auth import current_user
from quanthecy.markets.collection import collection_status
from quanthecy.markets.models import IngestionCheckpoint

from .console import tr
from .dependencies import dependency_status
from .forms import DeletionConfirmationForm, RawWindowForm
from .models import RawPayloadDeletion
from .policies import require_operator
from .quality import quality_overview
from .raw_data import enqueue_deletion, preview_deletion, repository


def render(request: HttpRequest, template: str, **context: Any) -> TemplateResponse:
    return TemplateResponse(
        request, f"admin/quanthecy/{template}.html", {**admin.site.each_context(request), **context}
    )


@require_http_methods(["POST"])
def language(request: HttpRequest) -> HttpResponse:
    selected = request.POST.get("language", "")
    if selected not in {"en", "zh-hans"}:
        return HttpResponseBadRequest("Unsupported language")
    target = request.POST.get("next", "/admin/")
    if not target.startswith("/admin/") or not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = "/admin/"
    response = redirect(target)
    response.set_cookie(
        "quanthecy_admin_language",
        selected,
        max_age=31536000,
        httponly=True,
        secure=request.is_secure(),
        samesite="Lax",
    )
    return response


@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    require_operator(current_user(request), "operations.view_collection_status")
    checkpoints = {str(row.collector_id): row for row in IngestionCheckpoint.objects.all()}
    batches = []
    error = ""
    try:
        committed = repository().collector_batches()
        for row in committed:
            checkpoint = checkpoints.pop(str(row["collector_id"]), None)
            reconciled = checkpoint.batch_id if checkpoint else 0
            batches.append(
                {
                    **row,
                    "reconciled": reconciled,
                    "lag": int(row["latest_batch"]) - reconciled,
                    "updated_at": checkpoint.updated_at if checkpoint else None,
                }
            )
        for collector, checkpoint in checkpoints.items():
            if len(batches) >= 101:
                break  # The bounded history query cannot prove other collectors are missing.
            batches.append(
                {
                    "collector_id": collector,
                    "reconciled": checkpoint.batch_id,
                    "latest_batch": tr("Missing", "缺失"),
                    "lag": tr("Check storage consistency", "检查存储一致性"),
                    "updated_at": checkpoint.updated_at,
                }
            )
    except AnalyticsUnavailable:
        error = "Historical storage is unavailable. Batch progress cannot be verified."
    return render(
        request,
        "dashboard",
        title=tr("Collection health", "数据采集"),
        batches=batches,
        collection=collection_status(),
        dependencies=dependency_status(),
        error=error,
        pending=RawPayloadDeletion.objects.filter(state__in=["PENDING", "RUNNING"]).count(),
    )


@require_GET
def data_quality(request: HttpRequest) -> HttpResponse:
    require_operator(current_user(request), "operations.view_collection_status")
    platform = request.GET.get("platform", "")
    state = request.GET.get("state", "")
    search = request.GET.get("q", "")[:200]
    try:
        offset = int(request.GET.get("offset", "0"))
    except ValueError:
        return HttpResponseBadRequest("Invalid offset")
    if (
        platform not in {"", "polymarket", "kalshi"}
        or state not in {"", "ready", "limited", "blocked"}
        or not 0 <= offset < 1000
    ):
        return HttpResponseBadRequest("Invalid quality filter")
    report = quality_overview(platform=platform, search=search, state=state, offset=offset)
    filters = {"platform": platform, "state": state, "q": search}
    return render(
        request,
        "data_quality",
        title=tr("Data quality", "数据质量"),
        report=report,
        **filters,
        previous_query=urlencode({**filters, "offset": max(0, offset - 50)}) if offset else "",
        next_query=urlencode({**filters, "offset": offset + 50}) if report["has_next"] else "",
    )


@require_http_methods(["GET", "POST"])
def raw_payloads(request: HttpRequest) -> HttpResponse:
    actor = current_user(request)
    require_operator(actor, "operations.view_raw_payloads")
    now = timezone.now().replace(microsecond=0)
    defaults = {
        "platform": "polymarket",
        "start": (now - timedelta(hours=1)).isoformat(),
        "end": now.isoformat(),
    }
    form = RawWindowForm(request.POST if request.method == "POST" else request.GET or defaults)
    rows: list[dict[str, Any]] = []
    summary = None
    confirmation = None
    next_query = ""
    previous_query = ""
    if form.is_valid():
        try:
            if request.method == "POST":
                summary, token = preview_deletion(actor, form.window())
                confirmation = DeletionConfirmationForm(initial={"token": token})
            else:
                offset = int(request.GET.get("offset", 0))
                results = repository().observations(form.window(), offset=offset)
                rows = results[:50]
                if offset > 0:
                    previous_query = urlencode(
                        {
                            **form.window().model_dump(mode="json"),
                            "market_id": form.cleaned_data["market_id"] or "",
                            "offset": max(offset - 50, 0),
                        }
                    )
                if len(results) > 50 and offset < 5000:
                    next_query = urlencode(
                        {
                            **form.window().model_dump(mode="json"),
                            "market_id": form.cleaned_data["market_id"] or "",
                            "offset": min(offset + 50, 5000),
                        }
                    )
        except AnalyticsUnavailable:
            form.add_error(
                None,
                tr(
                    "Historical storage is unavailable. Try again when it recovers.",
                    "历史存储暂时不可用，请恢复后重试。",
                ),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        except ValueError:
            form.add_error(
                None,
                tr(
                    "Invalid page offset. Narrow the range after 5,000 observations.",
                    "分页位置无效，超过 5,000 条后请缩小查询范围。",
                ),
            )
    return render(
        request,
        "raw_payloads",
        title=tr("Raw observations", "原始数据"),
        form=form,
        rows=rows,
        summary=summary,
        confirmation=confirmation,
        next_query=next_query,
        previous_query=previous_query,
    )


@require_http_methods(["POST"])
def confirm_deletion(request: HttpRequest) -> HttpResponse:
    actor = current_user(request)
    require_operator(actor, "operations.purge_raw_payloads")
    form = DeletionConfirmationForm(request.POST)
    if form.is_valid():
        try:
            job = enqueue_deletion(actor, form.cleaned_data["token"], form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                tr(
                    f"Cleanup job {job.pk} queued. Review it in Cleanup jobs.",
                    f"清理任务 {job.pk} 已加入队列，可在「清理任务」中查看进度。",
                ),
            )
            return redirect("platform_ops:raw_payloads")
    return render(
        request, "confirm_deletion", title=tr("Confirm cleanup", "确认数据清理"), form=form
    )


@require_GET
def raw_observation(request: HttpRequest, market_id: UUID, observation_id: UUID) -> HttpResponse:
    require_operator(current_user(request), "operations.view_raw_payloads")
    try:
        record = repository().observation(market_id, observation_id)
    except AnalyticsUnavailable:
        return render(
            request,
            "raw_observation",
            title=tr("Observation detail", "观测数据详情"),
            error=tr("Historical storage is unavailable.", "历史存储暂时不可用。"),
        )
    if record is None:
        raise Http404("Observation not found")
    return render(
        request, "raw_observation", title=tr("Observation detail", "观测数据详情"), record=record
    )


@require_GET
def collection_coverage(request: HttpRequest) -> HttpResponse:
    from quanthecy.markets.models import ResearchTopic
    from quanthecy.markets.selection import selection_status
    from quanthecy.markets.topics import coverage

    from .quality import reason_label

    require_operator(current_user(request), "operations.view_collection_status")
    topics = list(ResearchTopic.objects.all()[:50])
    selected = request.GET.get("topic", "")
    if selected and selected not in {topic.slug for topic in topics}:
        return HttpResponseBadRequest("Invalid topic")
    reports, rows = coverage([topic for topic in topics if not selected or topic.slug == selected])
    sections = []
    labels = {
        "paused": ("Paused", "已暂停"),
        "missing": ("Awaiting first observation", "等待首次采集"),
        "closed": ("Market closed", "市场已关闭"),
        "delayed": ("Collection delayed", "采集延迟"),
        "warming": ("Building history", "积累连续历史中"),
        "ready": ("Both indicators available", "两类指标可用"),
        "limited": ("Partially available", "部分指标可用"),
        "blocked": ("Quality check failed", "质量检查未通过"),
    }
    for report in reports:
        sections.append(
            {
                "report": report,
                "rows": [
                    {
                        "target": row,
                        "state_label": tr(*labels[row.state]),
                        "reasons": [reason_label(code) for code in row.reasons],
                    }
                    for row in rows[report.slug]
                ],
            }
        )
    return render(
        request,
        "collection_coverage",
        title=tr("Collection coverage", "主题与采集覆盖"),
        topics=topics,
        selected=selected,
        sections=sections,
        plan=selection_status(),
    )
