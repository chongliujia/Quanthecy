import json
from typing import Any

from django import template

from quanthecy.operations.console import MODEL_LABELS, tr

register = template.Library()

FIELD_LABELS = {
    "id": "ID",
    "title": "标题",
    "platform": "交易所",
    "status": "状态",
    "state": "任务状态",
    "created at": "创建时间",
    "updated at": "更新时间",
    "first observed at": "首次采集时间",
    "last observed at": "最近采集时间",
    "action": "操作",
    "actor": "操作人",
    "subject id": "对象 ID",
    "reason": "原因",
    "preview count": "预览数量",
    "requested by": "申请人",
    "error code": "错误代码",
    "is active": "账号启用",
    "is staff": "后台访问权限",
    "superuser status": "超级管理员",
    "name": "名称",
    "name zh": "中文名称",
    "slug": "主题标识",
    "is public": "前台展示",
    "enabled": "启用采集",
    "topic": "研究主题",
    "label": "市场名称",
    "rationale": "纳入理由",
    "exchange id": "交易所市场 ID",
    "research topic": "研究主题",
    "research topics": "个研究主题",
    "collection target": "采集目标",
    "collection targets": "个采集目标",
    "kind": "类型",
    "user": "用户",
    "users": "位用户",
    "market": "市场",
    "markets": "个市场",
    "organization": "工作空间",
    "organizations": "个工作空间",
    "raw payload deletion": "清理任务",
    "raw payload deletions": "项清理任务",
    "platform audit log": "审计记录",
    "platform audit logs": "条审计记录",
    "role": "角色",
    "provider": "身份提供方",
    "subject": "外部身份标识",
    "email": "邮箱",
    "source": "来源",
    "published at": "发布时间",
    "review state": "审核状态",
    "relation": "关联类型",
    "confidence": "置信度",
    "left market": "左侧市场",
    "right market": "右侧市场",
    "pending": "排队中",
    "running": "处理中",
    "succeeded": "已完成",
    "failed": "失败",
    "open": "开放",
    "closed": "已关闭",
    "resolved": "已结算",
}


@register.filter
def field_label(value: str) -> str:
    text = str(value)
    return tr(text, FIELD_LABELS.get(text.lower(), text))


@register.simple_tag
def ct(english: str, chinese: str) -> str:
    return tr(english, chinese)


@register.filter
def model_label(model: dict[str, Any]) -> str:
    names = MODEL_LABELS.get(f"{model['model']._meta.app_label}_{model['model']._meta.model_name}")
    return tr(*names) if names else str(model["name"])


@register.filter
def json_display(value: str) -> str:
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        return value


@register.filter
def action_label(value: str) -> str:
    names = {
        "collection.plan_changed": ("Collection plan updated", "更新采集计划"),
        "user.activated": ("Account enabled", "启用账号"),
        "user.deactivated": ("Account disabled", "停用账号"),
        "user.email_changed": ("Email updated", "修改邮箱"),
        "admin.password_changed": ("Password updated", "修改密码"),
        "raw_payload.deletion_requested": ("Cleanup requested", "提交数据清理"),
        "raw_payload.deletion_completed": ("Cleanup completed", "数据清理完成"),
        "raw_payload.deletion_failed": ("Cleanup failed", "数据清理失败"),
    }.get(value)
    return tr(*names) if names else value
