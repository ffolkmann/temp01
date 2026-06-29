# CodeXpress AI Chatbot — kód-alapú újraírás (Fázis 1)

FastAPI chat-szerviz a CLAUDE.md A/B/C rész szerint, **lokálisan, az éles n8n-től
függetlenül**. Saját dev Qdrant konténer (NEM az éles `cx_chatbot`!), Postgres, Redis.

## Mit tud (Fázis 1)
- `POST /chat` (és `POST /webhook/chat`) a **C.rész szerződése** szerint:
  válasz `{reply, action, configurator}`, `type`-multiplexálás (üzenet / `feedback` / `lead`).
- Üzenet-pipeline: **dense retrieval** (OpenAI `text-embedding-3-small` a kérdésre) →
  **hibrid rerank** (dense + lexikai + token-boost) → **current-product injektálás**
  (`page_context.url` → `# AKTUALIS TERMEK`) → **Anthropic Haiku** a tenant `system_prompt`-jával.
- Modulok: kupon (aktív/nem lejárt — a promptba), feedback-tárolás (Postgres),
  lead-tárolás (Postgres) + handoff e-mail **stub** (csak logol).
- Állapot Postgresben: `tenants` (25 oszlop, benne `fast_sync_minutes` + `domain`),
  `plans`, `coupons`, `usage`, `leads`, `unanswered`, `feedback`, `sync_jobs`.

## Előfeltétel
- Docker + Docker Compose (a host gépen nincs pip/Qdrant — mindent konténerben futtatunk).
- A `seed/` mappában: `teslashop_cx_chatbot.jsonl`, `collection_config.json`,
  `tenants.json`, `plans.json`, `coupons.json`, `load_dev_qdrant.py` (gitignore).

## Indítás

1. **`.env`** a `.env.example` alapján (töltsd ki a kulcsokat):
   ```bash
   cp .env.example .env
   # ANTHROPIC_API_KEY=..., OPENAI_API_KEY=...
   ```

2. **Stack fel** (api indításkor `alembic upgrade head`-et futtat):
   ```bash
   docker compose -f docker-compose.local.yml up -d --build
   curl localhost:8000/health
   ```

3. **Postgres seed** (tenants/plans/coupons):
   ```bash
   docker compose -f docker-compose.local.yml exec api python scripts/seed_dev.py
   ```

4. **Qdrant betöltés** (teslashop, 5289 pont — a dev Qdrantba):
   ```bash
   docker compose -f docker-compose.local.yml exec -w /app/seed api python load_dev_qdrant.py
   ```

5. **Chat teszt**:
   ```bash
   curl -s localhost:8000/chat -H 'content-type: application/json' -d '{
     "client_id":"teslashop","session_id":"s1",
     "message":"Milyen felnikupakokat ajánlasz a Model 3 Highlandhez?",
     "history":[],"page_context":null}' | jq
   ```

6. **Shadow parity** az éles n8n ellen (read-only chat-hívások):
   ```bash
   docker compose -f docker-compose.local.yml exec api python scripts/shadow_compare.py
   ```

## Megjegyzések
- A host gépen **nincs pip és nincs Docker a PATH-ban** — a scripteket a konténerből
  futtasd (`docker compose ... exec api ...`), így a függőségek és a hostnevek (postgres/
  qdrant/redis) készen vannak.
- Hostról futtatáshoz (ha van venv+pip): `DATABASE_URL=...@localhost:5432/...`,
  `QDRANT_URL=http://localhost:6333` env-override kell (a `.env` a konténer-hostneveket tartja).
- Az `action` mező jelenleg `null` (a widget 👍/👎-t mutat). A `collect_lead/
  order_status_form/quote_configurator` ágak a következő fázis(ok)ban élesednek,
  ahogy a prod-logika parity-jét pontosítjuk.

## Guardrailek (CLAUDE.md 0. + 9.)
- Az éles n8n/Qdrant prodhoz **nem nyúlunk** (a shadow csak felhasználói chat-hívás).
- Titok **nem megy gitbe** (`.env` gitignore).
- A widget beillesztő kódját **nem módosítjuk**.
