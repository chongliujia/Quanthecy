"""Presentation context for the operator console; permissions remain in Django Admin."""

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.functional import lazy


def tr(english: str, chinese: str) -> str:
    return chinese if (translation.get_language() or "").startswith("zh") else english


label = lazy(tr, str)


class AdminLanguageMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.path.startswith("/admin/"):
            return self.get_response(request)
        language = request.COOKIES.get("quanthecy_admin_language", "zh-hans")
        if language not in {"en", "zh-hans"}:
            language = "zh-hans"
        with translation.override(language):
            request.LANGUAGE_CODE = language
            response = self.get_response(request)
            response.headers["Content-Language"] = language
            return response


MODEL_LABELS = {
    "accounts_user": ("Users", "用户管理"),
    "accounts_authidentity": ("External identities", "外部身份"),
    "auth_group": ("Permission groups", "权限组"),
    "markets_researchtopic": ("Research topics", "研究主题"),
    "markets_collectiontarget": ("Collection targets", "采集名单"),
    "markets_market": ("Collected markets", "已采集行情"),
    "markets_event": ("Events", "市场事件"),
    "markets_outcome": ("Outcomes", "合约结果"),
    "markets_ingestioncheckpoint": ("Ingestion checkpoints", "采集检查点"),
    "operations_platformauditlog": ("Audit trail", "操作审计"),
    "operations_rawpayloaddeletion": ("Cleanup jobs", "清理任务"),
    "organizations_organization": ("Workspaces", "工作空间"),
    "organizations_organizationmembership": ("Workspace members", "空间成员"),
    "research_comparison": ("Market comparisons", "市场对比"),
    "research_comparisonreview": ("Comparison reviews", "对比审核"),
    "research_evidenceitem": ("Evidence library", "证据库"),
    "research_evidencelink": ("Evidence links", "证据关联"),
    "research_evidencerevision": ("Evidence revisions", "证据版本"),
    "research_researchevent": ("Research events", "研究事件"),
    "research_eventdefinition": ("Event scope revisions", "事件范围版本"),
    "research_eventmarketlink": ("Event contracts", "事件合约"),
    "research_eventevidence": ("Evidence review queue", "证据审核队列"),
    "research_eventevidencereview": ("Evidence review history", "证据审核记录"),
    "research_evidencesource": ("Evidence sources", "证据来源"),
}


def console_context(request: HttpRequest) -> dict[str, Any]:
    if not request.path.startswith("/admin/"):
        return {}
    context: dict[str, Any] = {
        "console_language": translation.get_language(),
        "console_is_zh": (translation.get_language() or "").startswith("zh"),
        "console_now": timezone.now(),
    }
    if not request.user.is_authenticated or not request.user.is_staff:
        return context
    current = request.resolver_match.view_name if request.resolver_match else ""
    specs: list[tuple[str, str, list[tuple[str, str, str, str, str | None]]]] = [
        (
            "Workspace",
            "工作台",
            [
                ("admin:index", "Overview", "运行总览", "overview", None),
                (
                    "platform_ops:collection_controls",
                    "Collection controls",
                    "采集控制",
                    "settings",
                    "markets.change_collectionplan",
                ),
                (
                    "platform_ops:dashboard",
                    "Collection health",
                    "数据采集",
                    "pulse",
                    "operations.view_collection_status",
                ),
            ],
        ),
        (
            "Data",
            "数据管理",
            [
                (
                    "platform_ops:market_directory",
                    "Market discovery",
                    "市场发现",
                    "market",
                    "operations.view_collection_status",
                ),
                (
                    "admin:research_evidencesource_changelist",
                    "News sources",
                    "新闻来源",
                    "file",
                    "research.view_evidencesource",
                ),
                (
                    "platform_ops:collection_coverage",
                    "Collection coverage",
                    "主题与采集覆盖",
                    "pulse",
                    "operations.view_collection_status",
                ),
                (
                    "admin:markets_researchtopic_changelist",
                    "Research topics",
                    "研究主题",
                    "market",
                    "markets.view_researchtopic",
                ),
                (
                    "admin:markets_collectiontarget_changelist",
                    "Collection targets",
                    "采集名单",
                    "database",
                    "markets.view_collectiontarget",
                ),
                (
                    "platform_ops:data_quality",
                    "Data quality",
                    "数据质量",
                    "shield",
                    "operations.view_collection_status",
                ),
                (
                    "platform_ops:raw_payloads",
                    "Raw observations",
                    "原始数据",
                    "database",
                    "operations.view_raw_payloads",
                ),
                (
                    "admin:markets_market_changelist",
                    "Collected markets",
                    "已采集行情",
                    "market",
                    "markets.view_market",
                ),
                (
                    "admin:research_comparison_changelist",
                    "Comparisons",
                    "市场对比",
                    "compare",
                    "research.view_comparison",
                ),
                (
                    "admin:research_eventevidence_changelist",
                    "Evidence review",
                    "证据审核",
                    "file",
                    "research.view_eventevidence",
                ),
                (
                    "admin:research_researchevent_changelist",
                    "Research events",
                    "研究事件",
                    "file",
                    "research.view_researchevent",
                ),
                (
                    "admin:research_evidenceitem_changelist",
                    "Evidence",
                    "证据库",
                    "file",
                    "research.view_evidenceitem",
                ),
            ],
        ),
        (
            "Administration",
            "平台管理",
            [
                (
                    "admin:accounts_user_changelist",
                    "Users",
                    "用户管理",
                    "users",
                    "accounts.view_user",
                ),
                (
                    "admin:organizations_organization_changelist",
                    "Workspaces",
                    "工作空间",
                    "building",
                    "organizations.view_organization",
                ),
                (
                    "admin:operations_rawpayloaddeletion_changelist",
                    "Cleanup jobs",
                    "清理任务",
                    "queue",
                    "operations.view_rawpayloaddeletion",
                ),
                (
                    "admin:operations_platformauditlog_changelist",
                    "Audit trail",
                    "操作审计",
                    "shield",
                    "operations.view_platformauditlog",
                ),
            ],
        ),
    ]
    sections = []
    for english, chinese, items in specs:
        links = []
        for route, en, zh, icon, permission in items:
            if permission and not request.user.has_perm(permission):
                continue
            url = reverse(route)
            active = current == route
            if route.endswith("_changelist"):
                active = current.startswith(route.removesuffix("changelist"))
            if route == "platform_ops:raw_payloads":
                active = current in {
                    route,
                    "platform_ops:raw_observation",
                    "platform_ops:confirm_deletion",
                }
            links.append({"url": url, "title": tr(en, zh), "icon": icon, "active": active})
        if links:
            sections.append({"title": tr(english, chinese), "links": links})
    context["console_navigation"] = sections
    for key, names in MODEL_LABELS.items():
        if current.startswith(f"admin:{key}_"):
            context["console_heading"] = tr(*names)
            break
    if current == "admin:index":
        context.update(overview_context(request))
    return context


def overview_context(request: HttpRequest) -> dict[str, Any]:
    from quanthecy.accounts.models import User
    from quanthecy.markets.collection import collection_status
    from quanthecy.markets.models import Market

    from .models import PlatformAuditLog, RawPayloadDeletion

    cards = []
    sources = None
    if request.user.has_perm("operations.view_collection_status"):
        sources = collection_status()
        cards.append(
            {
                "label": tr("Tracked markets", "已采集市场"),
                "value": Market.objects.count(),
                "note": tr("Across connected exchanges", "来自已连接的交易所"),
                "icon": "market",
            }
        )
    if request.user.has_perm("accounts.view_user"):
        cards.append(
            {
                "label": tr("Active users", "有效用户"),
                "value": User.objects.filter(is_active=True).count(),
                "note": tr("Accounts with access enabled", "当前允许登录的平台账号"),
                "icon": "users",
            }
        )
    if request.user.has_perm("operations.view_rawpayloaddeletion"):
        cards.extend(
            [
                {
                    "label": tr("Active cleanup jobs", "待处理清理任务"),
                    "value": RawPayloadDeletion.objects.filter(
                        state__in=["PENDING", "RUNNING"]
                    ).count(),
                    "note": tr("Queued or being processed", "包含排队和处理中任务"),
                    "icon": "queue",
                },
                {
                    "label": tr("Failed cleanup jobs", "需检查的失败任务"),
                    "value": RawPayloadDeletion.objects.filter(state="FAILED").count(),
                    "note": tr("Review details before retrying", "查看任务详情后再处理"),
                    "icon": "shield",
                },
            ]
        )
    recent_activity = []
    if request.user.has_perm("operations.view_platformauditlog"):
        recent_activity = list(PlatformAuditLog.objects.select_related("actor")[:5])
    return {
        "console_cards": cards,
        "console_collection": sources,
        "console_activity": recent_activity,
    }
