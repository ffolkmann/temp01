"""KB-ingest + kézi sync — a panel write-útja FastAPI-n (az n8n chat-ingest / chat-sync-* webhookok kiváltása).

POST /ingest?client_id=&filename=&token=   body: nyers fájl (.txt/.md/.docx/.pdf)
  -> szöveg-kinyerés, 1000 char chunk (v1 paritás), ugyanazon filename törlése, embed (TPM-throttle),
     upsert a settings.qdrant_collection-be. Payload: {client_id, filename, idx, text} (v1 paritás).
  Válasz: {"ok": true, "chunks": N}  (a panel uploadDoc() kontraktusa)

POST /sync?client_id=&token=
  -> `python -m app.sync --tenant <cid>` külön processzben (az event loopot nem fogja).
  Válasz: {"started": true}  (a panel syncProducts() kontraktusa)
"""

from __future__ import annotations

import asyncio
import html
import json
import io
import logging
import re
import sys
import uuid
import zipfile
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.embeddings import embed_texts
from app.core.settings import get_settings
from app.models.db_models import Tenant
from app.services.events import log_event

logger = logging.getLogger("cx.ingest")
router = APIRouter()

_settings = get_settings()
_CHUNK = 1000          # v1 paritás (n8n ingest ~1000 char szeletek)
_MAX_BYTES = 15 * 1024 * 1024

_sync_running: set[str] = set()   # per-tenant dupla-indítás elleni zár


def _auth_fail(token: str) -> JSONResponse | None:
    if not _settings.admin_panel_token:
        return JSONResponse({"error": "server_token_unset"}, status_code=503)
    if token != _settings.admin_panel_token:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return None


# --- szöveg-kinyerés --------------------------------------------------------- #
_DOCX_PART = re.compile(r"^word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml$")


def _extract_docx(raw: bytes) -> str:
    out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = [n for n in z.namelist() if _DOCX_PART.match(n)]
        names.sort(key=lambda n: (n != "word/document.xml", n))
        for n in names:
            xml = z.read(n).decode("utf-8", "replace")
            xml = re.sub(r"<w:(?:br|cr)[^>]*/?>", "\n", xml)
            xml = xml.replace("</w:p>", "\n")
            txt = re.sub(r"<[^>]+>", "", xml)
            out.append(html.unescape(txt))
    return "\n".join(out)


def _extract_pdf(raw: bytes) -> str:
    from pypdf import PdfReader  # lazy import

    reader = PdfReader(io.BytesIO(raw))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_text(filename: str, raw: bytes) -> str:
    low = filename.lower()
    if low.endswith(".docx"):
        return _extract_docx(raw)
    if low.endswith(".pdf"):
        return _extract_pdf(raw)
    for enc in ("utf-8", "cp1250", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _chunks(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    out = []
    for i in range(0, len(text), _CHUNK):
        c = text[i:i + _CHUNK].strip()
        if c:
            out.append(c)
    return out


def _doc_point_id(client_id: str, filename: str, idx: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cxdoc|{client_id}|{filename}|{idx}"))


async def _tenant_exists(client_id: str) -> bool:
    async with SessionLocal() as session:
        t = (await session.execute(
            select(Tenant.client_id).where(Tenant.client_id == client_id)
        )).scalar_one_or_none()
    return t is not None


@router.post("/ingest")
async def ingest(request: Request) -> Any:
    qp = request.query_params
    fail = _auth_fail(str(qp.get("token") or ""))
    if fail:
        return fail
    client_id = str(qp.get("client_id") or "").strip().lower()
    filename = str(qp.get("filename") or "").strip()
    if not client_id or not filename:
        return JSONResponse({"error": "missing_params"}, status_code=400)
    if not await _tenant_exists(client_id):
        return JSONResponse({"error": "unknown_client"}, status_code=404)

    raw = await request.body()
    if not raw or len(raw) < 2:
        return JSONResponse({"error": "empty_body"}, status_code=400)
    if len(raw) > _MAX_BYTES:
        return JSONResponse({"error": "file_too_large"}, status_code=413)

    try:
        text = _extract_text(filename, raw)
    except Exception as e:  # noqa: BLE001
        logger.exception("INGEST[%s] extract hiba: %s", client_id, filename)
        return JSONResponse({"error": "extract_failed", "detail": str(e)}, status_code=422)

    parts = _chunks(text)
    if not parts:
        return JSONResponse({"error": "no_text"}, status_code=422)

    coll = _settings.qdrant_collection
    async with httpx.AsyncClient(base_url=_settings.qdrant_url.rstrip("/"), timeout=60) as cl:
        # ugyanazon fájlnév újrafeltöltése felülír: előbb a régi chunkok törlése
        r = await cl.post(
            f"/collections/{coll}/points/delete?wait=true",
            json={"filter": {"must": [
                {"key": "client_id", "match": {"value": client_id}},
                {"key": "filename", "match": {"value": filename}},
            ]}},
        )
        r.raise_for_status()

        eb = _settings.sync_embed_batch
        total = 0
        for i in range(0, len(parts), eb):
            batch = parts[i:i + eb]
            vectors = await embed_texts(batch)
            points = [
                {
                    "id": _doc_point_id(client_id, filename, i + j),
                    "vector": vec,
                    "payload": {"client_id": client_id, "filename": filename,
                                "idx": i + j, "text": batch[j]},
                }
                for j, vec in enumerate(vectors)
            ]
            r = await cl.put(f"/collections/{coll}/points?wait=true", json={"points": points})
            r.raise_for_status()
            total += len(points)

    logger.info("INGEST[%s] %s -> %d chunk (%s)", client_id, filename, total, coll)
    return {"ok": True, "chunks": total}


@router.post("/sync")
async def sync(request: Request) -> Any:
    qp = request.query_params
    fail = _auth_fail(str(qp.get("token") or ""))
    if fail:
        return fail
    client_id = str(qp.get("client_id") or "").strip().lower()
    if not client_id:
        return JSONResponse({"error": "missing_params"}, status_code=400)
    if not await _tenant_exists(client_id):
        return JSONResponse({"error": "unknown_client"}, status_code=404)
    if client_id in _sync_running:
        return {"started": True, "note": "már fut"}

    _sync_running.add(client_id)

    async def _run() -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.sync", "--tenant", client_id,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            rc = proc.returncode
            lines = (out or b"").decode(errors="replace").splitlines()
            for ln in lines:
                logger.info("SYNC-PANEL[%s] %s", client_id, ln)
            # observability (m25): a futás eredménye tartós nyomot hagy az events táblában,
            # mert az api-konténer logja recreate-nél elvész (FO pontszám-rejtély tanulsága).
            meta: dict[str, Any] = {"rc": rc, "trigger": "admin_panel"}
            for ln in reversed(lines):
                ln = ln.strip()
                if ln.startswith("{") and ln.endswith("}"):
                    try:
                        res = json.loads(ln)
                    except ValueError:
                        continue
                    for k in ("source", "embed", "stale", "ps_update", "total", "failed", "error"):
                        if k in res:
                            meta[k] = res[k]
                    break
            try:
                async with SessionLocal() as session:
                    await log_event(session, client_id, "admin_panel", "sync_run", meta)
            except Exception:  # noqa: BLE001
                logger.exception("SYNC-PANEL[%s] event-írás hiba", client_id)
            logger.info("SYNC-PANEL[%s] kész rc=%s", client_id, rc)
        except Exception:  # noqa: BLE001
            logger.exception("SYNC-PANEL[%s] indítási hiba", client_id)
        finally:
            _sync_running.discard(client_id)

    asyncio.create_task(_run())
    return {"started": True}
