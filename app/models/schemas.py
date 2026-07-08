"""Pydantic I/O sémák — a CLAUDE.md C.rész szerződése szerint.

A POST /chat a `type` mező szerint multiplexál:
  - nincs type / null  -> ÜZENET  (C.3): válasz {reply, action, configurator}
  - "feedback"         -> 👍/👎 tárolás (C.4)
  - "lead"             -> lead tárolás + handoff e-mail (C.4)
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class PageContext(BaseModel):
    is_product: bool | None = None
    product_name: str | None = None
    url: str | None = None


class HistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    """Egységes bejövő body — minden /chat hívás ezt használja.

    A `type` jelenléte dönti el az ágat. A mezők unió-szerűek: feedback/lead
    eseteknél a megfelelő mezők jönnek (rating/email/phone/...).
    """

    client_id: str
    session_id: str | None = None
    message: str | None = None
    type: str | None = None
    history: list[HistoryItem] = Field(default_factory=list)
    page_context: PageContext | None = None

    # feedback (C.4)
    rating: Literal["up", "down"] | None = None
    question: str | None = None
    answer: str | None = None

    # lead (C.4)
    email: str | None = None
    phone: str | None = None
    name: str | None = None
    source: str | None = None

    # event (m22): widget-esemény (jelenleg: link_click)
    event: str | None = None
    url: str | None = None
    title: str | None = None

    model_config = {"extra": "ignore"}


class ConfiguratorRef(BaseModel):
    config_url: str
    calculate_url: str | None = None
    email_url: str | None = None


class ChatResponse(BaseModel):
    """A widget EZT várja (C.3)."""

    reply: str
    action: (
        Literal["collect_lead", "order_status_form", "quote_configurator", "operator_wait"]
        | None
    ) = None
    configurator: ConfiguratorRef | None = None


class EventAck(BaseModel):
    """Esemény (feedback/lead) nyugta — a widget a választ amúgy ignorálja (C.4)."""

    ok: bool = True
    stored: str | None = None


# belső segéd-típus a retrievalhoz
class RetrievedProduct(BaseModel):
    id: str
    score: float
    payload: dict[str, Any]
