from typing import Any, cast

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import F, OuterRef, QuerySet, Subquery
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.html import format_html

from quanthecy.api.auth import current_user
from quanthecy.operations.console import label

from .admin import HistoricalAdmin
from .documents import OfficialDocument
from .events import append_definition, append_evidence_review, validate_review
from .models import (
    EventDefinition,
    EventEvidence,
    EventEvidenceReview,
    EventMarketLink,
    EvidenceRevision,
    ResearchEvent,
)


@admin.register(ResearchEvent)
class ResearchEventAdmin(HistoricalAdmin):
    list_display = ("slug", "topic", "created_at")
    search_fields = ("slug",)


@admin.register(EventDefinition)
class EventDefinitionAdmin(HistoricalAdmin):
    list_display = ("title", "version", "starts_on", "ends_on", "observed_at")
    readonly_fields = ("version", "observed_at")
    search_fields = ("title", "title_zh")

    def save_model(
        self, request: HttpRequest, obj: EventDefinition, form: Any, change: bool
    ) -> None:
        append_definition(obj)


@admin.register(EventMarketLink)
class EventMarketLinkAdmin(HistoricalAdmin):
    list_display = ("event", "market", "created_at")
    readonly_fields = ("snapshot",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


class CandidateStateFilter(admin.SimpleListFilter):
    title = label("Review state", "审核状态")
    parameter_name = "review_state"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, Any]]:
        return [
            ("pending", label("Pending", "待审核")),
            ("reviewed", label("Reviewed", "已审核")),
            ("stale", label("Superseded", "已被新版本替代")),
        ]

    def queryset(self, request: HttpRequest, queryset: Any) -> Any:
        current = queryset.filter(
            revision_id=F("_current_revision"), definition_id=F("_current_definition")
        )
        if self.value() == "pending":
            return current.filter(_last_relation__isnull=True)
        if self.value() == "reviewed":
            return current.filter(_last_relation__isnull=False)
        if self.value() == "stale":
            return queryset.exclude(pk__in=current.values("pk"))
        return queryset


@admin.register(EventEvidence)
class EventEvidenceAdmin(HistoricalAdmin):
    list_display = (
        "document_title",
        "event_scope",
        "version",
        "review_status",
        "review_action",
        "created_at",
    )
    list_filter = (CandidateStateFilter, "definition__event")
    search_fields = ("revision__title", "definition__title")
    readonly_fields = ("review_action", "source_text")
    list_select_related = ("definition__event", "revision")
    ordering = ("-revision__published_at", "-created_at")

    def get_queryset(self, request: HttpRequest) -> QuerySet[EventEvidence]:
        return (
            super()
            .get_queryset(request)
            .annotate(
                _current_revision=Subquery(
                    EvidenceRevision.objects.filter(item_id=OuterRef("revision__item_id"))
                    .order_by("-version")
                    .values("id")[:1]
                ),
                _current_definition=Subquery(
                    EventDefinition.objects.filter(event_id=OuterRef("definition__event_id"))
                    .order_by("-version")
                    .values("id")[:1]
                ),
                _last_relation=Subquery(
                    EventEvidenceReview.objects.filter(candidate_id=OuterRef("pk"))
                    .order_by("-reviewed_at", "-id")
                    .values("relation")[:1]
                ),
            )
        )

    @admin.display(description=label("Official evidence", "官方证据"))
    def document_title(self, obj: EventEvidence) -> str:
        return obj.revision.title

    @admin.display(description=label("Event", "研究事件"))
    def event_scope(self, obj: EventEvidence) -> str:
        return str(obj.definition)

    @admin.display(description=label("Document version", "正文版本"))
    def version(self, obj: EventEvidence) -> int:
        return obj.revision.version

    @admin.display(description=label("Review status", "审核状态"))
    def review_status(self, obj: EventEvidence) -> str:
        if obj.revision_id != getattr(
            obj, "_current_revision", obj.revision_id
        ) or obj.definition_id != getattr(obj, "_current_definition", obj.definition_id):
            return str(label("Superseded; review the latest version", "已有新版本，请重新审核"))
        relation = getattr(obj, "_last_relation", None)
        return str(
            dict(EventEvidenceReview.Relation.choices).get(
                str(relation), label("Pending", "待审核")
            )
        )

    @admin.display(description=label("Review", "审核"))
    def review_action(self, obj: EventEvidence) -> str:
        url = reverse("admin:research_eventevidencereview_add")
        return format_html(
            '<a href="{}?candidate={}">{}</a>',
            url,
            obj.pk,
            label("Review this version →", "审核此版本 →"),
        )

    @admin.display(description=label("Numbered original text", "带编号原文"))
    def source_text(self, obj: EventEvidence) -> str:
        document = (
            OfficialDocument.model_validate(obj.revision.document)
            if obj.revision.document
            else None
        )
        text = (
            "\n\n".join(f"[{i}] {p}" for i, p in enumerate(document.text.split("\n\n"), 1))
            if document
            else obj.revision.excerpt
        )
        return format_html('<pre style="white-space:pre-wrap;max-width:100ch">{}</pre>', text)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


class EvidenceReviewForm(ModelForm):
    preview_candidate_id: str | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.preview_candidate_id and "candidate" in self.fields:
            self.initial["candidate"] = self.preview_candidate_id

    class Meta:
        model = EventEvidenceReview
        fields = ("candidate", "relation", "rationale", "paragraphs")
        labels = {
            "candidate": label("Evidence version", "证据版本"),
            "relation": label("Relevance", "关联程度"),
            "rationale": label("Review rationale", "审核依据"),
            "paragraphs": label("Original paragraph numbers", "原文段落编号"),
        }

    def clean(self) -> dict[str, Any]:
        values = super().clean() or {}
        if values.get("candidate") and str(values["candidate"].pk) != self.preview_candidate_id:
            raise ValidationError(
                "Open the candidate review link to load its original text first. / "
                "请从候选资料的审核链接打开原文后再提交。"
            )
        if all(key in values for key in ("candidate", "relation", "rationale", "paragraphs")):
            validate_review(EventEvidenceReview(**values), lock=True)
        return values


@admin.register(EventEvidenceReview)
class EventEvidenceReviewAdmin(HistoricalAdmin):
    form = EvidenceReviewForm
    change_form_template = "admin/research/event_review.html"
    list_display = ("candidate", "relation", "reviewed_by", "reviewed_at")
    list_filter = ("relation", "candidate__definition__event")
    search_fields = ("candidate__revision__title", "rationale")
    autocomplete_fields = ("candidate",)
    readonly_fields = ("reviewed_by", "reviewed_at")

    def get_form(
        self, request: HttpRequest, obj: Any = None, change: bool = False, **kwargs: Any
    ) -> Any:
        form = cast(type[EvidenceReviewForm], super().get_form(request, obj, change, **kwargs))
        form.preview_candidate_id = request.GET.get("candidate")
        if form.preview_candidate_id and "candidate" in form.base_fields:
            form.base_fields["candidate"].disabled = True
        return form

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict[str, Any],
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: Any = None,
    ) -> HttpResponse:
        candidate_id = (
            obj.candidate_id
            if obj
            else request.GET.get("candidate") or request.POST.get("candidate")
        )
        try:
            candidate = (
                EventEvidence.objects.select_related("definition", "revision")
                .filter(pk=candidate_id)
                .first()
                if candidate_id
                else None
            )
        except (ValidationError, ValueError):
            candidate = None
        if candidate:
            document = (
                OfficialDocument.model_validate(candidate.revision.document)
                if candidate.revision.document
                else None
            )
            context["review_candidate"] = candidate
            context["review_preview_bound"] = (
                str(candidate.pk) == request.GET.get("candidate") or obj is not None
            )
            context["review_preview_url"] = (
                reverse("admin:research_eventevidencereview_add")
                + "?candidate="
                + str(candidate.pk)
            )
            context["review_paragraphs"] = document.text.split("\n\n") if document else []
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(
        self, request: HttpRequest, obj: EventEvidenceReview, form: Any, change: bool
    ) -> None:
        obj.reviewed_by = current_user(request)
        append_evidence_review(obj)
