"""Termék-szinkron motor (Fázis 3) — platform API -> embedding -> Qdrant (cx_chatbot_v2).

CLI: python -m app.sync --tenant <client_id> | --all  [--dry-run]
"""

from app.sync.engine import sync_tenant

__all__ = ["sync_tenant"]
