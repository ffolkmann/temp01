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

# m82c/2: a kerdesbol felismert KATEGORIA-SZANDEK feloldasahoz a tenant VALODI
# `category` payload-ertekei kellenek (a crawl-terkep csak slugokat ismer).
# Qdrant facet API, tenantonkent gyorsitotarazva -- keresesenkent nem hivjuk.
_CATALOG_TTL = 1800.0
_catalog_cache: dict[str, tuple[float, list[str]]] = {}


async def category_catalog(client_id: str) -> list[str]:
    """A tenant kulonbozo `category` payload-ertekei (cache-elt; hiba -> [])."""
    import time as _time
    now = _time.monotonic()
    hit = _catalog_cache.get(client_id)
    if hit and (now - hit[0]) < _CATALOG_TTL:
        return hit[1]
    try:
        vals = await get_qdrant().facet_values("category", client_id)
    except Exception:  # noqa: BLE001 — katalogus nelkul csak a kategoria-szandek esik ki
        return hit[1] if hit else []
    _catalog_cache[client_id] = (now, vals)
    return vals


# m86: a KATEGORIA-KAPU facet-terkep NELKUL. A `cat_tags` listas payload kategoria-
# NEVEKET tartalmaz (paramextract.category_tags), tehat onmagaban is eleg szotarnak.
# A facet API a listas keyword-mezo EGYEDI ertekeit adja, gyakorisag szerint.
_CAT_TAG_LIMIT = 400
_cattag_cache: dict[str, tuple[float, list[str]]] = {}


async def cat_tag_catalog(client_id: str) -> list[str]:
    """A tenant kulonbozo `cat_tags` payload-ertekei (cache-elt; hiba -> [])."""
    import time as _time
    now = _time.monotonic()
    hit = _cattag_cache.get(client_id)
    if hit and (now - hit[0]) < _CATALOG_TTL:
        return hit[1]
    try:
        vals = await get_qdrant().facet_values("cat_tags", client_id, limit=_CAT_TAG_LIMIT)
    except Exception:  # noqa: BLE001 — katalogus nelkul csak a kategoria-kapu esik ki
        return hit[1] if hit else []
    _cattag_cache[client_id] = (now, vals)
    return vals


async def retrieve(
    embed_input: str,
    message: str,
    client_id: str,
    page_url: str = "",
    page_url_norm: str = "",
    hide_oos: bool = False,
) -> tuple[list[dict[str, Any]], float, str]:
    """A kérdésre dense találatok a Qdrantból (client_id-only, limit 24), majd hibrid rerank -> top 8.

    Visszaad: (reranked top_n hits, top_dense_score) — a top score a megválaszolatlan-küszöbhöz.

    - `embed_input`: amit vektorizálunk (page_product_name + '. ' + message, vagy csak message)
    - `message`: a rerank token-számításhoz az EREDETI kérdés kell (nem az embed-input)
    """
    from app.services.rerank import rerank  # késleltetett import a körkörösség elkerülésére
    from app.services.policy_filter import (  # m34 / m82d
        _is_product as _isprod82, filter_for_policy, is_policy_query, policy_embed_input,
    )
    from app.services.query_cleanup import product_query_cleanup  # m36: zaj-tisztitas
    from app.services.paramextract import build_filter_conditions, detect_constraints  # m79c
    from app.services.superlative import (  # m38/m39/m40/m58/m64
        AVAIL_WIDE_LIMIT, USAGE_WIDE_LIMIT, WIDE_LIMIT, accessory_filter, detect_price_superlative,
        detect_stock_filter, merge_available_extras,
        needs_available_boost, price_context_stock, topic_of,
    )

    # m34: policy-kerdesnel a beagyazando query-t policy-kulcsszavakkal dusitjuk, hogy a dense
    # kereses a KB-doksi (ASZF/garancia/elallas) fele billenjen, ne a termeknevek fele.
    # m36: koszones/toltelek-zaj ('Szia , ... keresek') eltavolitasa a BEAGYAZANDO
    # szovegbol — a latogato uzenete valtozatlanul megy az LLM-nek es a reranknak.
    # m38/m39: ar-szuperlativusz ("legolcsobb/legdragabb") -> szelesebb topikalis pool,
    # es KOR-FUGGETLEN tema-embed ('legolcsobb laptop' -> 'laptop'): igy az elso es a
    # folytato kerdes ugyanazt a poolt kapja -> konzisztens valasz. A rendezes lent
    # determinisztikus (ar szerint), a dense csak a temat szuri.
    superlative = detect_price_superlative(message)
    stock_only = bool(superlative) and (detect_stock_filter(message) or hide_oos)  # m58 + m73: tenant-tiltas is kenyszeriti
    # m82c: a kulon m76-os `usage` payload-ag KIVEZETVE -- a felhasznalas-jelleget
    # (uzleti/otthoni/gamer/...) a generikus, crawl-olt facets-szotar kezeli
    # (facetdict), kategoria-kapuval; igy nincs ket parhuzamos cimke-ut.
    _cons79c = detect_constraints(message, client_id)  # m79c + m82h/2 (tenant marka-szotar)
    _pextra = build_filter_conditions(_cons79c)  # m79c: param-szures (bag-gate, konzervativ)
    if _cons79c.get("brand"):  # m82h/2: merheto legyen, hogy a marka-szuro tenyleg lefutott
        import logging as _lg82h
        _lg82h.getLogger("cx.retrieval").info(
            "m82h2 brand filter: %s vals=%s client=%s",
            _cons79c.get("brand"), _cons79c.get("brand_vals") or "(kezi lista)", client_id,
        )
    _wide82 = False  # m82c: facets-szurt poolnal a TELJES cimkezett halmaz kell (USAGE_WIDE_LIMIT)
    _topic = topic_of(message) if superlative else ""
    # m82h/3: ha a marka mar MUST-feltetel, a marka NEVE kikerul az embedelt
    # szovegbol -- a szurt poolban minden termek ugyanattol a markatol van,
    # tehat a marka-jel nulla informacio, viszont elnyomja az ALTIPUST.
    # Meres (tools/m82h3_sweep.py): "Milyen Delphin satratok van?" a top-8-ban
    # 0 -> 6 sator; a pool-limit emelese NEM segit (300-nal 4 -- higitja a
    # rerank lexikai jelet), ezert csak az embed valtozik.
    _ein82h3 = embed_input
    if _cons79c.get("brand") and not superlative:
        try:
            from app.services.branddict import strip_brand as _sb82h3
            _rest82h3 = _sb82h3(embed_input, str(_cons79c.get("brand") or ""))
            if _rest82h3:
                _ein82h3 = _rest82h3
                import logging as _lg82h3
                _lg82h3.getLogger("cx.retrieval").info(
                    "m82h3 brand-free embed: %r -> %r client=%s",
                    embed_input[:80], _rest82h3[:80], client_id,
                )
        except Exception:  # noqa: BLE001 - fail-safe: marad a mai embed
            pass
    if superlative and len(_topic) >= 3:
        vector = await embed_query(_topic)
    else:
        vector = await embed_query(policy_embed_input(message, product_query_cleanup(_ein82h3)))
    qdrant = get_qdrant()
    hits = await qdrant.search(
        vector=vector,
        client_id=client_id,
        limit=(max(WIDE_LIMIT, _settings.retrieval_top_k) if superlative else _settings.retrieval_top_k),
        product_only=False,  # parity: NINCS type=product szűrő a fő keresésben
        extra_must=_pextra or None,  # m79c
    )
    if not hits and _pextra:  # m79c fail-safe: ures param-szurt lista -> szuretlen fallback
        import logging as _logging
        _logging.getLogger("cx.retrieval").info("m79c param filter empty -> fallback (client=%s)", client_id)
        hits = await qdrant.search(
            vector=vector,
            client_id=client_id,
            limit=(max(WIDE_LIMIT, _settings.retrieval_top_k) if superlative else _settings.retrieval_top_k),
            product_only=False,
        )
    # a prod `Eval Unanswered` a SEARCH KB top dense score-ját nézi (rerank ELŐTT)
    top_score = float(hits[0].get("score") or 0.0) if hits else 0.0
    # m34: policy-temaju kerdesnel (garancia/szallitas/elallas...) a termek-chunkokat a NYERS
    # 24-es listabol dobjuk ki, MEG a rerank elott — kulonben a lexikai atfedes a termeknevekben
    # ('...3 ev garancia...') kiszoritja a KB-doksit a top-8-bol. A top_score a szures ELOTTI
    # (a megvalaszolatlan-kuszob valtozatlan marad).
    # m82b: generikus bolt-szuro (facets payload) — a kontextus-talalatok
    # kategoriaja a KAPU, a crawl-olt facet-ertekek a szotar. Csak
    # ar-szuperlativusznal fut (ott dont a pool-minimum), igy a KB/policy
    # ut erintetlen; ures szurt talalat -> valtozatlan pool (fail-safe).
    # m82d: a szures a NEM-szuperlativusz termek-kerdesekre is fut. Eloméres
    # (tools/m82d_nonsuper.py, notebookstore, 12 kerdes): a mai szuretlen top-24-bol
    # atlagosan CSAK 20% felelt meg annak a bolti szuronek, amit a kerdes megnevezett
    # ("gamer laptop" es "otthoni notebook": 0/24 -- a modell olyan halmazbol valaszolt,
    # amiben egyetlen megfelelo termek sem volt). KAPU: policy-kerdesnel SOHA nem fut,
    # mert a `facets` must-feltetel a KB-chunkokat kizarna a poolbol.
    _plain82 = not superlative and not is_policy_query(message)
    if hits and (superlative or _plain82):
        try:
            from app.services.facetdict import build_facet_conditions as _bfc82
            from app.services.facetdict import category_value as _cv82
            from app.services.facetdict import detect_facet_tags as _dft82
            from app.services.linkfacet import load_map as _lm82
            _cats82 = [str((h.get("payload") or {}).get("category") or "") for h in hits]
            _fmap82 = _lm82(client_id)
            # m82c/2: a kapu ELSOSORBAN a kerdesbol feloldott kategoria; a
            # talalatok top-kategoriaja csak fallback. E nelkul a
            # notebook-dominans pool elnyomta a "gamer asztali szamitogep"-et
            # (a kapu notebookra allt be -> a 6 asztali gamer gep sosem jott be).
            from app.services.facetdict import detect_category as _dcat82
            _qcat82 = _dcat82(message, await category_catalog(client_id))
            _tags82 = _dft82(message, _cats82, _fmap82, category=_qcat82)
            if _tags82:
                # m82c: KATEGORIA-KAPU a szuresen is (nem csak a felismeresen).
                # A cimkek kategoria-agnosztikusak, a bolt szuro-oldala nem az.
                _cat82 = _cv82(_cats82, _fmap82, category=_qcat82)
                _fc82 = _bfc82(_tags82, _cat82)
                # m82d: szuperlativusznal szeles pool kell (ott ar szerint rendezunk),
                # sima termek-kerdesnel viszont a megszokott top-k -- igy a pool
                # TARTALMA valtozik, a merete nem (a rerank valtozatlan koltseggel fut).
                _lim82 = max(WIDE_LIMIT, _settings.retrieval_top_k) if superlative \
                    else _settings.retrieval_top_k
                _fh82 = await qdrant.search(
                    vector=vector, client_id=client_id, limit=_lim82,
                    product_only=False, extra_must=(_pextra or []) + _fc82,
                )
                if not _fh82 and _cat82:  # fail-safe: kategoria-kapu nelkul ujra
                    _fc82 = _bfc82(_tags82)
                    _fh82 = await qdrant.search(
                        vector=vector, client_id=client_id, limit=_lim82,
                        product_only=False, extra_must=(_pextra or []) + _fc82,
                    )
                import logging as _lg82
                _lg82.getLogger("cx.retrieval").info(
                    "m82b facet filter %s cat=%r mode=%s -> %d hit (client=%s)",
                    _tags82, _cat82, ("super" if superlative else "plain"),
                    len(_fh82), client_id,
                )
                if _fh82:
                    if superlative:
                        hits = _fh82
                    else:
                        # m82d: plain modban a szuro csak a TERMEK-halmazt csereli le --
                        # a KB/doksi-talalatok bennmaradnak, kulonben egy vegyes kerdes
                        # ("van 4K monitorotok, es mennyi a szallitas?") elveszitene a
                        # KB-reszt. Atfedes nincs: a KB-chunknak nincs `facets` payloadja,
                        # tehat a szurt keresesbe eleve nem kerulhet bele.
                        hits = _fh82 + [h for h in hits if not _isprod82(h)]
                    _pextra = (_pextra or []) + _fc82
                    _wide82 = True
        except Exception:  # noqa: BLE001 — a facet-szures hibaja ne torje a chatet
            pass
    # m86: KATEGORIA-KAPU facet-TERKEP NELKUL. A fenti m82b-s ut kotelezoen crawl-olt
    # facet-terkepet igenyel (linkfacet.load_map), az viszont CSAK a notebookstore-ra
    # letezik -- a tobbi 11 tenanton a kerdesben megnevezett kategoria eddig SEMMIT nem
    # szurt. MERES (tools/m86_catgate.py, valodi kerdes-korpusz): teslashop a kerdesek
    # 24%-ara old fel kategoriat (median fedes 98 termek az 5289-bol), kellegyszerszam
    # 13% (59/15461), nagyonallatshop 11% (550/1580).
    # Csak akkor fut, ha a facets-ut NEM szurt (ott mar van kategoria-feltetel);
    # ures szurt talalat -> valtozatlan pool (fail-safe).
    if hits and not _wide82 and (superlative or _plain82):
        try:
            from app.services.facetdict import detect_category as _dcat86
            from app.services.linkfacet import load_map as _lm86
            # m86 HATOKOR: csak ott, ahol NINCS crawl-olt facet-terkep. Ahol van
            # (ma: notebookstore), ott a m82-es sav a gazda -- az attributum-szintu
            # szures pontosabb, es a teljes onboarding-keszlet arra van hangolva;
            # ket parhuzamos kategoria-mechanizmus csak zajt vinne bele.
            # KOCKAZAT-TERKEP (tools/m86_gate_sweep.py, valodi korpusz): a kapu
            # kellegyszerszam 71 kerdesre old fel kategoriat, ebbol ~6 hamis
            # ("csavarhuzo" -> Csavar, "anyagbol" -> Anya) a facetdict 4 betus
            # toldalek-turese miatt; teslashop 7/7 tiszta; nagyonallatshop 27,
            # tulnyomorest a szeles "Kutya" (914/1580 = alig szur).
            _qcat86 = "" if _lm86(client_id) else _dcat86(message, await cat_tag_catalog(client_id))
            if _qcat86:
                _fc86 = [{"key": "cat_tags", "match": {"value": _qcat86}}]
                _lim86 = max(WIDE_LIMIT, _settings.retrieval_top_k) if superlative \
                    else _settings.retrieval_top_k
                _fh86 = await qdrant.search(
                    vector=vector, client_id=client_id, limit=_lim86,
                    product_only=False, extra_must=(_pextra or []) + _fc86,
                )
                import logging as _lg86
                _lg86.getLogger("cx.retrieval").info(
                    "m86 category gate: cat=%r mode=%s -> %d hit (client=%s)",
                    _qcat86, ("super" if superlative else "plain"), len(_fh86), client_id,
                )
                if _fh86:
                    if superlative:
                        hits = _fh86
                    else:
                        # m82d minta: plain modban CSAK a termek-halmaz cserelodik,
                        # a KB/doksi-talalatok bennmaradnak.
                        hits = _fh86 + [h for h in hits if not _isprod82(h)]
                    _pextra = (_pextra or []) + _fc86
                    _wide82 = True
        except Exception:  # noqa: BLE001 — a kategoria-kapu hibaja ne torje a chatet
            pass
    hits = filter_for_policy(message, hits)
    # m38: szuperlativusznal a rerank relevancia-sorrendje okozta az onellentmondast
    # (koronkent mas top-8 'legolcsobbja'). Determinisztikus ar-rendezes a szeles poolon:
    # igy a valasz korrol korre AZONOS, es tenyleg a legkedvezobb aru relevans termek.
    _mode = ""
    if superlative:
        # m40: fele ar-veg + fele tema-relevancia -- kiegeszito-beszivargas ellen (copygo eles eset)
        # m58: keszlet-szuro ("raktaron levo") -> csak available==True jeloltek; a mode a promptnak megy
        # m60: available==True SZURT dense pool kozvetlenul a Qdrantbol — a szuretlen 120-as
        # poolbol az olcso raktaros gepek kiszorulhatnak (eles eset: Vivobook 109 900 raktaron,
        # de a pool legolcsobb raktarosa 325 990 volt). SR/Unas-nal (nincs available mezo) a
        # filter 0 talalatot ad -> fallback a pool klienses szuresere (avail_pool=None).
        avail_pool = None
        try:
            _ap = await qdrant.search(
                vector=vector, client_id=client_id,
                limit=(USAGE_WIDE_LIMIT if _wide82 else AVAIL_WIDE_LIMIT),
                product_only=True, available_only=True,
                extra_must=_pextra or None,  # m79c/m82c
            )
            if not _ap and _pextra:  # m79c/m82c fallback: param-hiany -> regi ut
                _ap = await qdrant.search(
                    vector=vector, client_id=client_id,
                    limit=AVAIL_WIDE_LIMIT, product_only=True, available_only=True,
                )
            avail_pool = _ap or None
        except Exception:  # noqa: BLE001 — a szurt pool hibaja ne torje a chatet
            avail_pool = None
        # m75: eszkoz-temaju szuperlativusznal (notebook/laptop) a kiegeszito-zaj
        # (taska/dokkolo/tolto...) kiszurese a poolokbol, mielott az ar-rendezes fut.
        _hits_f = accessory_filter(hits, _topic or message)
        _ap_f = accessory_filter(avail_pool, _topic or message) if avail_pool else avail_pool
        by_price, _mode = price_context_stock(
            _hits_f, superlative, _settings.context_top_n, stock_only, avail_pool=_ap_f
        )
        if by_price:
            return by_price, top_score, _mode
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
    # m64: ha a kontextus termekei kozott nincs raktaron levo, de van keszlet-adat,
    # max 3 raktaros jeloltet fuzunk hozza relevancia szerint (available-szurt keresesbol),
    # hogy az m63-as "csak raktarost ajanlj" szabalynak legyen mibol ajanlania.
    if hide_oos or needs_available_boost(reranked):  # m73: OOS-tiltasnal mindig legyen raktaros jelolt
        try:
            _pool64 = await qdrant.search(
                vector=vector, client_id=client_id, limit=40,
                product_only=True, available_only=True,
                extra_must=_pextra or None,  # m79c/m82c
            )
            if not _pool64 and _pextra:  # m79c/m82c fallback
                _pool64 = await qdrant.search(
                    vector=vector, client_id=client_id, limit=40,
                    product_only=True, available_only=True,
                )
            reranked = merge_available_extras(reranked, _pool64, 3)
        except Exception:  # noqa: BLE001 — a boost hibaja ne torje a chatet
            pass
    return reranked, top_score, _mode
