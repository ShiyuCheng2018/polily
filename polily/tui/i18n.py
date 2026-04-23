# polily/tui/i18n.py
"""v0.8.0 user-facing Chinese translations per Q12 decision.

Rule: all user-facing label strings come from here. Internal logs / errors
remain English.

Exempt terms (Polymarket / industry canon, not translated):
YES, NO, bid, ask, CLOB, negRisk, API, URL, ID, P&L, ROI, %, $, USD
"""

# Scan log status enums
STATUS_LABELS = {
    "pending": "待执行",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    "superseded": "已覆盖",
}

# Trigger sources (scan_logs.trigger_source enum).
# 'scan' is kept in the DB CHECK constraint for backward compat but no code
# currently produces it; not included here.
TRIGGER_LABELS = {
    "manual": "手动",
    "scheduled": "定时",
    "movement": "监控",
}


def translate_status(status: str) -> str:
    """Translate scan_logs.status to Chinese. Unknown → return as-is."""
    return STATUS_LABELS.get(status, status)


def translate_trigger(source: str) -> str:
    """Translate scan_logs.trigger_source to Chinese. Unknown → return as-is."""
    return TRIGGER_LABELS.get(source, source)
