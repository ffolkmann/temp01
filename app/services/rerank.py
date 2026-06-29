"""Hibrid rerank — a prod `Hybrid Rerank` Code node 1:1 portja (lásd seed/prod_retrieval.txt).

A Qdrant a dense (cosine) score-t adja. Erre rakunk egy lexikai átfedés-pontot
(a kérdés szó-tokenjei közül hány szerepel a találat szövegében) és egy token-boostot
(a kérdés szám-tartalmú modell-tokenjei). A végső `fused` sorrend:

    fused = 0.65*dense + 0.35*lex + boost

Majd a page_url-egyező terméket a top-listához pinneljük (ha kimaradt).
"""

import re
import unicodedata
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-/.]{1,}")


def fold(s: str) -> str:
    """lowercase + ékezet-strip (NFD, combining-mark eltávolítás) — prod `fold`."""
    s = str(s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(message: str) -> tuple[list[str], list[str]]:
    """(wordTokens, modelTokens) a prod szerint.

    qTokens     : /[a-z0-9][a-z0-9\\-/.]{1,}/ és len >= 3
    modelTokens : van benne számjegy és len >= 3
    wordTokens  : nincs benne számjegy és len >= 4
    """
    q = fold(message)
    q_tokens = [t for t in _TOKEN_RE.findall(q) if len(t) >= 3]
    model_tokens = [t for t in q_tokens if any(c.isdigit() for c in t) and len(t) >= 3]
    word_tokens = [t for t in q_tokens if not any(c.isdigit() for c in t) and len(t) >= 4]
    return word_tokens, model_tokens


def rerank(
    message: str,
    hits: list[dict[str, Any]],
    page_url: str = "",
    page_url_norm: str = "",
    top_n: int = 8,
) -> list[dict[str, Any]]:
    """A Qdrant találatokat újrarangsorolja és visszaadja a top_n-t + a pinnelt page-terméket."""
    word_tokens, model_tokens = _tokens(message)
    page_url = (page_url or "").strip()
    page_url_norm = (page_url_norm or "").strip()

    scored: list[dict[str, Any]] = []
    for r in hits:
        p = r.get("payload", {}) or {}
        txt = fold(
            str(p.get("text") or p.get("content") or p.get("chunk") or "")
            + " "
            + str(p.get("name") or "")
        )
        hit_count = sum(1 for t in word_tokens if t in txt)
        lex = (hit_count / len(word_tokens)) if word_tokens else 0.0

        boost = 0.25 * sum(1 for t in model_tokens if t in txt)
        if boost > 0.5:
            boost = 0.5

        dense = float(r.get("score") or 0.0)
        fused = 0.65 * dense + 0.35 * lex + boost

        url = str(p.get("url") or "").strip()
        is_page = bool(
            url and ((page_url and url == page_url) or (page_url_norm and url == page_url_norm))
        )
        scored.append({"r": r, "fused": fused, "is_page": is_page})

    scored.sort(key=lambda s: s["fused"], reverse=True)
    out = [s["r"] for s in scored[:top_n]]
    pinned = next((s for s in scored if s["is_page"]), None)
    if pinned and pinned["r"] not in out:
        out.append(pinned["r"])
    return out
