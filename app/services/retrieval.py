"""Dense retrieval + hibrid rerank — a prod `Embed Message` -> `Search Knowledge Base`
-> `Hybrid Rerank` lánc portja (lásd seed/prod_retrieval.txt).

FONTOS (parity): a fő Qdrant keresés CSAK `client_id`-re szűr, `type=product` NÉLKÜL,
limit 24 — így a KB-chunkok (elállás/ÁSZF/szállítás/FAQ) is előjönnek.
"""

from typing import Any

from app.core.embeddings import embed_query
from app.core.qdrant import get_qdrant
from app.core.settings import get_settings

_settings = get_settings()


async def retrieve(
    embed_input: str,
    message: str,
    client_id: str,
    page_url: str = "",
    page_url_norm: str = "",
) -> list[dict[str, Any]]:
    """A kérdésre dense találatok a Qdrantból (client_id-only, limit 24), majd hibrid rerank -> top 8.

    - `embed_input`: amit vektorizálunk (page_product_name + '. ' + message, vagy csak message)
    - `message`: a rerank token-számításhoz az EREDETI kérdés kell (nem az embed-input)
    """
    from app.services.rerank import rerank  # késleltetett import a körkörösség elkerülésére

    vector = await embed_query(embed_input)
    qdrant = get_qdrant()
    hits = await qdrant.search(
        vector=vector,
        client_id=client_id,
        limit=_settings.retrieval_top_k,
        product_only=False,  # parity: NINCS type=product szűrő a fő keresésben
    )
    return rerank(
        message,
        hits,
        page_url=page_url,
        page_url_norm=page_url_norm,
        top_n=_settings.context_top_n,
    )
