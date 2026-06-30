"""SQLAlchemy modellek — a CLAUDE.md B.rész 3+6 szerint.

A tenants tábla a config DataTable (ggNtMA5doynfs6Hn) 25 oszlopa (index 0–24),
benne a két új oszlop: fast_sync_minutes (23) ÉS domain (24).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    client_id: Mapped[str] = mapped_column(String, primary_key=True)        # 0
    platform: Mapped[str | None] = mapped_column(String)                    # 1
    bot_name: Mapped[str | None] = mapped_column(String)                    # 2
    header_color: Mapped[str | None] = mapped_column(String)                # 3
    bubble_color: Mapped[str | None] = mapped_column(String)                # 4
    welcome_message: Mapped[str | None] = mapped_column(Text)               # 5
    system_prompt: Mapped[str | None] = mapped_column(Text)                 # 6
    lead_email: Mapped[str | None] = mapped_column(String)                  # 7
    plan: Mapped[str | None] = mapped_column(String)                        # 8
    launcher_position: Mapped[str | None] = mapped_column(String)           # 9
    active: Mapped[bool] = mapped_column(Boolean, default=True)             # 10
    api_base: Mapped[str | None] = mapped_column(String)                    # 11
    api_client_id: Mapped[str | None] = mapped_column(String)               # 12
    api_client_secret: Mapped[str | None] = mapped_column(String)           # 13
    auto_open: Mapped[bool] = mapped_column(Boolean, default=False)         # 14
    auto_open_delay: Mapped[float | None] = mapped_column(Float)            # 15
    proactive_message: Mapped[str | None] = mapped_column(Text)             # 16
    proactive_product_message: Mapped[str | None] = mapped_column(Text)     # 17
    public_url: Mapped[str | None] = mapped_column(String)                  # 18
    stat_key: Mapped[str | None] = mapped_column(String)                    # 19
    elallas_url: Mapped[str | None] = mapped_column(String)                 # 20
    configurator_shop: Mapped[str | None] = mapped_column(String)           # 21
    popup_config: Mapped[dict | None] = mapped_column(JSONB)                # 22 (str-JSON -> jsonb)
    fast_sync_minutes: Mapped[float | None] = mapped_column(
        Float, default=1440, server_default="1440")                         # 23 (napi; adminból állítható)
    domain: Mapped[str | None] = mapped_column(String)                      # 24


class Plan(Base):
    __tablename__ = "plans"

    plan: Mapped[str] = mapped_column(String, primary_key=True)
    live_api: Mapped[bool] = mapped_column(Boolean, default=False)
    white_label: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_limit: Mapped[float | None] = mapped_column(Float)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("client_id", "period", name="uq_usage_client_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    period: Mapped[str] = mapped_column(String)          # pl. "2026-06"
    conversations: Mapped[int] = mapped_column(Integer, default=0)
    notified_pct: Mapped[int | None] = mapped_column(Integer)


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str | None] = mapped_column(String)
    discount: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str | None] = mapped_column(String)
    conditions: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[str | None] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    message: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String)
    history: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Unanswered(Base):
    __tablename__ = "unanswered"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String)
    question: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String)
    rating: Mapped[str | None] = mapped_column(String)       # "up" | "down"
    question: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    page_context: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    type: Mapped[str] = mapped_column(String)               # full | fast
    status: Mapped[str] = mapped_column(String)             # queued | running | done | error
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
