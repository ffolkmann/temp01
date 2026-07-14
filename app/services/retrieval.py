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
) -> tuple[list[dict[str, Any]], float]:
    """A kérdésre dense találatok a Qdrantból (client_id-only, limit 24), majd hibrid rerank -> top 8.

    Visszaad: (reranked top_n hits, top_dense_score) — a top score a megválaszolatlan-küszöbhöz.

    - `embed_input`: amit vektorizálunk (page_product_name + '. ' + message, vagy csak message)
    - `message`: a rerank token-számításhoz az EREDETI kérdés kell (nem az embed-input)
    """
    from app.services.rerank import rerank  # késleltetett import a körkörösség elkerülésére
    from app.services.policy_filter import filter_for_policy, policy_embed_input  # m34
    from app.services.query_cleanup import product_query_cleanup  # m36: zaj-tisztitas
    from app.services.superlative import WIDE_LIMIT, detect_price_superlative, price_context, topic_of  # m38/m39/m40

    # m34: policy-kerdesnel a beagyazando query-t policy-kulcsszavakkal dusitjuk, hogy a dense
    # kereses a KB-doksi (ASZF/garancia/elallas) fele billenjen, ne a termeknevek fele.
    # m36: koszones/toltelek-zaj ('Szia , ... keresek') eltavolitasa a BEAGYAZANDO
    # szovegbol — a latogato uzenete valtozatlanul megy az LLM-nek es a reranknak.
    # m38/m39: ar-szuperlativusz ("legolcsobb/legdragabb") -> szelesebb topikalis pool,
    # es KOR-FUGGETLEN tema-embed ('legolcsobb laptop' -> 'laptop'): igy az elso es a
    # folytato kerdes ugyanazt a poolt kapja -> konzisztens valasz. A rendezes lent
    # determinisztikus (ar szerint), a dense csak a temat szuri.
    superlative = detect_price_superlative(message)
    _topic = topic_of(message) if superlative else ""
    if superlative and len(_topic) >= 3:
        vector = await embed_query(_topic)
    else:
        vector = await embed_query(policy_embed_input(message, product_query_cleanup(embed_input)))
    qdrant = get_qdrant()
    hits = await qdrant.search(
        vector=vector,
        client_id=client_id,
        limit=(max(WIDE_LIMIT, _settings.retrieval_top_k) if superlative else _settings.retrieval_top_k),
        product_only=False,  # parity: NINCS type=product szűrő a fő keresésben
    )
    # a prod `Eval Unanswered` a SEARCH KB top dense score-ját nézi (rerank ELŐTT)
    top_score = float(hits[0].get("score") or 0.0) if hits else 0.0
    # m34: policy-temaju kerdesnel (garancia/szallitas/elallas...) a termek-chunkokat a NYERS
    # 24-es listabol dobjuk ki, MEG a rerank elott — kulonben a lexikai atfedes a termeknevekben
    # ('...3 ev garancia...') kiszoritja a KB-doksit a top-8-bol. A top_score a szures ELOTTI
    # (a megvalaszolatlan-kuszob valtozatlan marad).
    hits = filter_for_policy(message, hits)
    # m38: szuperlativusznal a rerank relevancia-sorrendje okozta az onellentmondast
    # (koronkent mas top-8 'legolcsobbja'). Determinisztikus ar-rendezes a szeles poolon:
    # igy a valasz korrol korre AZONOS, es tenyleg a legkedvezobb aru relevans termek.
    if superlative:
        # m40: fele ar-veg + fele tema-relevancia -- kiegeszito-beszivargas ellen (copygo eles eset)
        by_price = price_context(hits, superlative, _settings.context_top_n)
        if by_price:
            return by_price, top_score
    reranked = rerank(
        message,
        hits,
        page_url=page_url,
        page_url_norm=page_url_norm,
        top_n=_settings.context_top_n,
    )
    # m34: a rerank lexikai pontja a termeknevekben ('...3 ev garancia...') kiszorithatja a
    # KB-doksit a top_n-bol. Policy-kerdesnel a rerank UTAN ujra kiszurjuk a termekeket, hogy
    # a modell csak a hivatalos KB-szoveget lassa. (A hits mar szurt volt, de a rerank a teljes
    # bemenetbol valogat -> itt a vegleges top_n-en ervenyesitjuk.)
    reranked = filter_for_policy(message, reranked)
    return reranked, top_score
