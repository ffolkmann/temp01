# CodeXpress AI Chatbot — Claude Code teljes handoff (EGY fájl)

> **Struktúra:** A. RÉSZ = build brief (a terv) · B. RÉSZ = rendszer-spec (a működés forrása) · C. RÉSZ = widget I/O kontaktus (a Fázis-1 pontos szerződése).
> **Olvasási sorrend:** A → C → B. Az A megmondja MIT és HOGYAN; a C a pontos endpoint-szerződés; a B a részletes referencia minden funkcióhoz.
> A kereszthivatkozások („lásd CHATBOT-INTERNAL.md", „lásd brief X. pont") ezen az egy fájlon belül a megfelelő A/B/C részre értendők.

---

# A. RÉSZ — BUILD BRIEF

# CodeXpress AI Chatbot — Kód-alapú újraírás · Claude Code build brief

> **Cél:** a jelenlegi n8n-alapú chatbot-platform **kód-alapú, sok-ügyfeles, skálázható** változata, UGYANAZOKKAL a funkciókkal, az n8n **hot-path** kiváltásával — **a most futó n8n rendszer MELLETT**, fokozatosan (strangler-fig), soha nem törve a prodot.
>
> **A működés forrása (source of truth):** `CHATBOT-INTERNAL.md` (ugyanebben a mappában / Google Drive). Minden viselkedést ahhoz mérünk. Ez a brief a HOGYAN (terv + architektúra + parity-lista), az nem ismétli meg.

Készült: 2026-06-28. Olvasd végig a 0. és 9. pontot először.

---

## 0. Alapelvek (guardrails — KÖTELEZŐ)

1. **Strangler-fig, NEM big-bang.** Az új rendszer az n8n mellett épül; ügyfelenként vándorlás; minden lépés után működő ÉS visszagörgethető prod. A „mindent egyszerre újraírok" tiltott (második-rendszer csapda).
2. **Az élő n8n prod sérthetetlen.** Az n8n-hez és a Qdrant-hoz csak **olvasás** (adatmigráció/parity). n8n workflow-t csak akkor kapcsolunk ki, ha a kiváltása prod-validált.
3. **Bevált logikát nem dobunk ki**, átültetjük: delta-embed, `content_hash`/`ps_hash`, hibrid rerank, per-tenant CORS, current-product injektálás.
4. **Qdrant marad.** Az **n8n nem cél kiirtani** — megmarad ops/glue rétegnek (ütemezés-trigger, lead-email, connectorök). Hibrid végállapot legitim: kód-mag + vékony n8n.
5. **Titok soha kódba/gitbe.** Env/secret-store. A meglévő értékek a VPS-ről olvashatók (lásd `CHATBOT-INTERNAL.md` 0.3).
6. **Architektúra-döntésnél kérdezz** (Fecó vezeti). Inkrementális PR-ek, ne egy óriás commit.

---

## 1. Célarchitektúra

- **API:** FastAPI (Python). Indok: a meglévő embedding/sync/hash-logika 1:1 átültethető Pythonban. (Alternatíva: Hono/Fastify TS, ha egy nyelv kell a widgettel — de a Python ajánlott a meglévő logika miatt.)
- **Vektor DB:** Qdrant (meglévő `cx_chatbot` kollekció; tenant-izoláció `client_id` payload-szűréssel; pont-ID séma marad: `detUuid(client_id+':'+forrás_id)`).
- **Állapot:** PostgreSQL — kiváltja az n8n DataTable-öket (config/plans/usage/leads/coupons/unanswered/feedback + `domain`). Ez a valódi multi-tenant fix: konkurens írás, query, backup, nincs n8n-csatolás.
- **Job queue:** arq (Redis) vagy Celery — a szinkronhoz. Ezzel a 100 s Cloudflare-timeout + early-respond + önhívó lánc + chunk-gimnasztika **eltűnik**.
- **LLM:** Anthropic SDK (Haiku) közvetlenül; **embedding** OpenAI `text-embedding-3-small`.
- **Deploy:** Docker; több API-replika Cloudflare mögött + 1+ sync-worker + Redis + Postgres. Skálához le a 8 GB-os egy-VPS-ről (külön DB/worker, vagy managed Postgres/Redis).
- **Observability:** strukturált JSON-log, `/health`, kérés-trace (tenant, latency, retrieval-hit), `sync_jobs` státusz-tábla.

---

## 2. Repó-struktúra (Claude Code hozza létre)

```
chatbot/
  app/
    main.py                 # FastAPI belépő
    api/                    # routes: chat, config, admin, stat, ingest, sync
    core/                   # settings(env), db(sqlalchemy), qdrant, llm, embeddings, security(cors)
    services/               # retrieval, rerank, current_product, coupons, leads,
                            #   handoff, feedback, unanswered, elallas, popup, plan_gating
    sync/                   # full_sync, fast_sync + platform adapterek:
                            #   sellvio.py, shoprenter.py, unas.py, woo.py, webdoc.py
    models/                 # pydantic (I/O) + SQLAlchemy (DB)
    workers/                # arq taskok (sync jobok)
  migrations/               # alembic
  scripts/                  # migrate_from_n8n.py (DataTable->Postgres, read-only)
  tests/                    # parity tesztek az n8n ellen
  docker/                   # Dockerfile, docker-compose.yml
  CLAUDE.md                 # = CHATBOT-INTERNAL.md ide másolva (a viselkedés-spec)
  README.md
```

---

## 3. Adatmodell → Postgres (migráció a DataTable-ökből)

A `CHATBOT-INTERNAL.md` 5–6. pontja adja a forrás-sémát. Postgres-táblák:

- **tenants** (a config DataTable, `ggNtMA5doynfs6Hn`): `client_id (PK), platform, bot_name, header_color, bubble_color, welcome_message, system_prompt, lead_email, plan, launcher_position, active, api_base, api_client_id, api_client_secret, auto_open, auto_open_delay, proactive_message, proactive_product_message, public_url, stat_key, elallas_url, configurator_shop, popup_config (jsonb), fast_sync_minutes, domain` — **figyelj: 2 új oszlop**, `fast_sync_minutes` (index 23) ÉS `domain` (index 24, lásd 6.).
- **plans** (`4BaX90AeTicjEcpx`): `plan (PK), live_api, white_label, monthly_limit`.
- **usage** (`JzNYwNTfh1rH4uBI`): `client_id, period, conversations, notified_pct`.
- **leads** (`3RskHrJIWRntS2jf`).
- **coupons** (`P4tJHZCaXejQkYzC`): `client_id, code, discount, kind, conditions, valid_until, active`.
- **unanswered** (`zZjInGVWN7WtqAPw`), **feedback** (`mw7LIVgo0PaX3yzg`).
- **sync_jobs** (ÚJ): `id, client_id, type(full|fast), status, started_at, finished_at, changed, total, error`.

**Migráció:** `scripts/migrate_from_n8n.py` olvassa az n8n SQLite-ot **read-only** (`/var/lib/docker/volumes/n8n-cxxz_n8n_data/_data/database.sqlite`, `data_table_user_*` táblák), és tölti Postgresbe. `popup_config` → jsonb. A Qdrant-pontokat NEM kell migrálni (ugyanaz a kollekció/ID-séma).

---

## 4. Fázisok (strangler-fig — minden fázis után működő + rollback)

- **Fázis 0 — Scaffold.** Repó, Docker compose (api+postgres+redis), `/health`, settings env-ből, Qdrant+LLM+embedding kliens. Olvasás a meglévő Qdrant-ból read-only. CLAUDE.md = CHATBOT-INTERNAL.md.
- **Fázis 1 — Chat-szerviz árnyékban (shadow).** `POST /chat` implementálva (retrieval+rerank+current-product+modulok+LLM), **AZONOS input/output kontaktussal** (lásd 5.). Shadow: egy ügyfél valós kérdéseit az új API-n is lefuttatod (offline replay vagy duplázott hívás), és összeveted a választ/latencyt az n8n-ével. **Prod még n8n.**
- **Fázis 2 — Cutover 1 ügyfél.** A widget config (vagy Cloudflare route) az új `/chat`-re mutat **egy** ügyfélnél (kis kockázatú, pl. teslashop vagy egy belső). Figyelés. Bővítés ügyfelenként. **Rollback = vissza az n8n webhookra** (config-flag).
- **Fázis 3 — Sync engine kódban.** Full + fast sync job-queue-val (delta-embed, `ps_hash`, `set_payload`). Platform-adapterek. Az n8n sync workflow-k leszerelése ahogy kiváltod. **Itt szűnik meg a chunk/önhívás/timeout-tánc.**
- **Fázis 4 — Állapot Postgresbe.** Config/coupons/stb. átmigrálva; admin + widget-config az új API-ra; az n8n DataTable-ök read-only/archive.
- **Fázis 5 — Dekommisszió.** A kiváltott n8n workflow-k kikapcsolása. n8n marad email/connector/trigger glue-nak.

---

## 5. Parity-kritikus viselkedés (1:1 átültetni — részletek a CHATBOT-INTERNAL.md-ben)

- **Chat I/O kontaktus** (manual 3.): `POST /chat` body `{client_id, session_id, message, type, history, page_context:{is_product, product_name, url}}`. A válasz formátumát a widgethez kell illeszteni (nézd meg a widget.js-ben mit vár).
- **Retrieval + rerank**: dense + lexikai + token-boost (manual 11.).
- **Current-product injektálás**: `page_context.url` → `# AKTUALIS TERMEK` blokk.
- **content_hash (szemantikus) vs ps_hash (ár+készlet)** — delta-embed (csak változott szemantika → re-embed) + fast ár/készlet (`set_payload`, nincs embed). Manual 4. és 7.2.
- **Modulok**: coupons (aktív/nem lejárt), lead/handoff e-mail, feedback 👍/👎, unanswered naplózás, elállás-gomb (`elallas_url`), popup (`popup_config`).
- **System prompt / hangnem** tenantonként; **plan-gating** (`live_api`, `white_label`, `monthly_limit`) + usage-számlálás.
- **Platform-adapterek** (sync): Sellvio/Shoprenter/Unas/Woo élő ár/készlet + rendelés; Webdoc feed pillanatkép. Auth a manual 10. szerint.

---

## 6. Biztonsági réteg — a MÁSIK chat hardeningje (KÖTELEZŐEN portolni)

> Ez most n8n-ben/widget.js-ben él (élesben). Az új rendszerbe át kell vinni. A widget.js maradhat ugyanaz — csak a config/chat endpoint mutat majd az új API-ra.

### 6.1 widget.js (már hardened, élesben — `/root/weboldal_fajlok/chatbot/widget.js`, `?v=fb1`)
- iframe `sandbox`: `allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-top-navigation-by-user-activation`.
- 3× `postMessage(...,"*")` → explicit `CX.parentOrigin` / `location.origin`.
- bejövő iframe-listener origin-ellenőrzés: `ev.origin === CX.parentOrigin`.
- `parentOrigin` = `location.origin`, a srcdoc CX-be injektálva.
- **A beillesztő kód VÁLTOZATLAN** — egyik kliensnél sem kell újra beilleszteni; az új rendszernél se kelljen.
- backupok a VPS-en: `widget.js.bak-20260627-155600`, `widget.js.bak2-20260627-161538`.

### 6.2 Per-tenant CORS (most: Chatbot – Config `gwGmkSVpSmI5i90Q`; ÚJ rendszerben a `/config` és minden böngészőből hívott végpont)
- A kérés `Origin`-jét a tenant doménjéhez méri. **SORREND:** (1) DB `domain` oszlop → (2) beépített `DOMAIN_MAP` fallback → (3) ha egyik sincs: **fail-open reflect**.
- Mapped tenant → a doménjére zárva: **apex + www + aldomén + http/https** engedve; idegen origin **blokk**.
- `Access-Control-Allow-Origin` a tenant doménjére; **`Vary: Origin`** kötelező.
- **Kódban EGYETLEN helyen** állítsd az ACAO-t (az n8n-ben az `allowedOrigins`-t törölni kellett, nehogy dupla ACAO menjen — a FastAPI-nál ne tegyél rá globális CORSMiddleware `*`-ot ezekre az endpontokra; saját, tenant-tudatos CORS-függvény).
- n8n backup: `/docker/claude-exec/work/wf_config.bak-20260627-162854.json`.

### 6.3 `domain` adat (a tenants táblába migrálandó)
Most: config DataTable új `domain` oszlop (index 24, col id `tdXsW9jlSsWNxAGj`), mind a 14 kitöltve. Seed:
```
welltechnik=welltechnik.hu        teslashop=teslashop.hu
cegalkusz=cegalkusz.hu            ecowindoor=ecowin.hu
mastercool=klimaszereles-budapest-karbantartas.hu
plcomfort=plcomfortwebshop.hu     [ELLENŐRIZENDŐ]
adlogic=adlogic.unas.hu           smartzilla=smartzilla.hu
4mfrigo=webshop.4mfrigo.hu        rmweb=rmweb.hu
kellegyszerszam=kellegyszerszam.hu codexpress=codexpress.hu
nagyonallatshop=nagyonallatshop.hu notebookstore=notebookstore.hu
```
(A `DOMAIN_MAP` a kódban csak fallback; a `domain` oszlop a forrás.)

### 6.4 admin (most admin.html + Chatbot – Admin `zyCefQXtQ0c9ZsLt`)
- Új „Engedélyezett domain" mező (`f_domain`, a Publikus URL alatt); `setForm` betölti, `gatherForm` menti (`row.domain`); az `Upsert Config` map-ben `domain = {{ $json.row.domain || "" }}`. Az új admin API-nak ugyanezt kell tudnia.

### 6.5 NYITOTT (nem kód-feladat — kézi, jelzem a teljesség kedvéért)
- Google Ads újrabírálás (policy-gomb, Mastercool).
- codexpress.hu **Avast/Safe Browsing FP review** (Search Console + Avast űrlap; esetleg `plugins.js` karcsúsítás) — **MÉG NINCS kész**.
- plcomfort domén megerősítése (`plcomfortwebshop.hu`?).

---

## 7. Titkok / env

`.env` (soha gitbe): `ANTHROPIC_API_KEY, OPENAI_API_KEY, QDRANT_URL, DATABASE_URL, REDIS_URL, ADMIN_TOKEN` + platform-kulcsok a tenants táblából (per ügyfél). A meglévő értékek a VPS-ről olvashatók (`CHATBOT-INTERNAL.md` 0.3): n8n REST kulcs `cat /docker/n8n-cxxz/.n8n_restkey`; admin token a `zyCefQXtQ0c9ZsLt` `Auth OK?` node-jában.

---

## 8. Tesztelés / parity

- **Chat-parity:** ~50 valós kérdés (a `unanswered` + gyakori kérdésekből) → futtatás mindkét rendszeren → válasz/latency összevetés. Aranystandard a jelenlegi n8n-válasz.
- **Sync-parity:** ugyanarra a feedre a Qdrant point-count + payload mezők (`content_hash`, `ps_hash`, `price`, `available`, `text`) egyezzenek.
- **CORS-teszt:** mapped tenant idegen origin → blokk; saját origin (apex/www/sub, http/https) → engedi; nem-mapped → reflect; `Vary: Origin` jelen.
- **Load:** API-replika skálázás; nagy katalógusú sync queue-val (nincs timeout); konkurens tenant-írás Postgresen.

---

## 9. Amit Claude Code NE tegyen

- NE big-bang; NE nyúljon az élő n8n prod-hoz (csak olvasás az adatmigrációhoz/parityhez).
- NE töröljön/álljon le n8n workflow-t, amíg a kiváltás nincs prod-validálva.
- NE tegyen titkot kódba/gitbe.
- NE írja át a widget beillesztő kódját (változatlan marad).
- Bizonytalan architektúra-döntésnél kérdezzen.

---

## 10. Első konkrét feladat

**Fázis 0 + Fázis 1 (chat-szerviz váz):**
1. Repó + `docker-compose` (api + postgres + redis), `/health`, settings env-ből.
2. Qdrant + Anthropic + OpenAI-embedding kliens (read-only a meglévő `cx_chatbot`-ra).
3. `POST /chat` váz: retrieval + rerank + current-product + LLM (a modulok eleinte stub), **azonos I/O kontaktus**.
4. `scripts/migrate_from_n8n.py` (DataTable→Postgres, read-only) — tenants + a 25 oszlop (benne `fast_sync_minutes`, `domain`).
5. CLAUDE.md = CHATBOT-INTERNAL.md.
6. Shadow-teszt **egy** ügyfélen (pl. teslashop): vesd össze az új `/chat` válaszát az n8n-ével.

Innen ügyfelenkénti cutover (Fázis 2), majd sync engine (Fázis 3).

---

## 11. Jelenlegi élő állapot (amit az új rendszernek tükröznie kell)

- **2 párhuzamos session eredménye él:**
  - *(ez a fő szál)* Webdoc gyors ár/készlet sync (`HrKM5Ca0eGRpYOJ3`) + Fast Scheduler (`c1wI7ZgUdxH67e96`) + `fast_sync_minutes` oszlop (index 23); notebookstore `platform=webdoc`, `fast_sync_minutes=60`, 12 691 termék.
  - *(a másik szál)* widget.js hardening + per-tenant CORS a `gwGmkSVpSmI5i90Q`-ban + `domain` oszlop (index 24) mind a 14 kitöltve + admin domain mező.
- 14 ügyfél, max ~12k termék/ügyfél → **az adatmennyiség nem szűk keresztmetszet**; a refaktor célja a stabilitás/karbantarthatóság/konkurencia, nem a „nagy adat".

*Vége. A részletes viselkedés a CHATBOT-INTERNAL.md-ben; ez a brief a terv + a parity-lista.*


---

# B. RÉSZ — RENDSZER-SPEC (CHATBOT-INTERNAL.md)

# CodeXpress AI Chatbot — Belső technikai / üzemeltetési kézikönyv

> **Bizalmas — belső használatra.** Ez a dokumentum a multi-tenant AI chatbot SaaS teljes működési leírása fejlesztéshez/üzemeltetéshez (Claude Code handoff is). Élő titkokat (n8n REST kulcs, admin token) **helymegjelöléssel** tartalmaz, nem literálként — futásidőben a VPS-ről olvasandók (lásd 0.3). Ne tedd publikus webroot alá.

Utolsó frissítés: 2026-06-28. Verzió: élő rendszer pillanatképe.

---

## 0. Hozzáférés, exec-csatorna, titkok

### 0.1 VPS
- Hostinger Frankfurt KVM2 — 2 vCPU, 8 GB RAM, 100 GB. IP `187.77.69.247`. Ubuntu 25.10. Hostname `codexpress.cloud`.
- SSL/DNS: Cloudflare előtt. **Nincs hagyományos SSH** — Hostinger panel böngészős Terminal / konténerenként. Fájlfeltöltés: WinSCP (SFTP).
- Publikus webroot: `/root/weboldal_fajlok/` (NEM `/var/www/html`). Statikus + PHP. Pl. `chatbot/admin.html` → `https://codexpress.cloud/chatbot/admin.html`.

### 0.2 Docker stackek (root `/`-ből)
| Stack | Tartalom | Port / domain | Mappa |
|---|---|---|---|
| `n8n-cxxz` | n8n 2.x | 1234:5678, n8n.codexpress.cloud | `/docker/n8n-cxxz/` |
| `webszerver` | publikus web | codexpress.cloud | webroot `/root/weboldal_fajlok/` |
| `portainer` | Docker UI | — | — |
| `nyilatkozat` | (külön app) | — | — |
- n8n konténer: `n8n-cxxz-n8n-1` (általánosan: `docker ps --format '{{.Names}}' | grep -i n8n`).
- Qdrant: `http://qdrant:6333` (csak a docker-hálón belülről; nincs auth). Kollekció: `cx_chatbot`.

### 0.3 Titkok (helymegjelölés — NE másold dokumentumba/publikus helyre)
- **n8n REST kulcs**: `/docker/n8n-cxxz/.n8n_restkey` — csak a VPS-en olvasd (`cat`), soha ne emeld ki kontextusba. Fejléc: `X-N8N-API-KEY: <kulcs>`. UA mindig `curl/8.5.0` (Cloudflare 1010 elkerülés; a REST `http://localhost:1234`-en megy, Cloudflare-t megkerüli).
- **Chatbot admin token** (közös bearer az összes admin+sync webhookhoz): a `Chatbot – Admin` (`zyCefQXtQ0c9ZsLt`) `Auth OK?` node `rightValue` mezőjében, és minden `Chatbot – * Sync` Auth node-jában. Lekérés: `GET /api/v1/workflows/zyCefQXtQ0c9ZsLt` → `Auth OK?` node. A chat-admin body mezője: `admin_token`. A sync/fast webhookoknál query: `?token=...`.
- **Platform API-kulcsok (tenantonként)**: a config DataTable `api_client_id` / `api_client_secret` mezőiben; csak a háttér-workflow-k használják.

### 0.4 claude-exec csatorna (autonóm shell a VPS-en)
- Mechanizmus: tölts fel egy `<job>.sh`-t ide: `/docker/claude-exec/queue/<job>.sh`, az utolsó sor legyen `#__READY__`. Egy systemd `claude-exec` service lefuttatja; kimenet: `/docker/claude-exec/out/<job>.log`. Kész, ha az utolsó sor `=== END ===`.
- A futó **max 1800 s/job** → hosszú munka `setsid` detached driverrel a `/docker/claude-exec/work/`-ben. A queue **egyszálú**.
- A VPS host: van `python3` (beépített `sqlite3`-mal) + `curl`, **nincs node** és **nincs pip/venv** → node-hoz `docker exec $N8N node -e '...'`; python csomag kell → `apt-get install -y python3-<pkg>` (root). `python3-docx` így települ.
- SFTP olvasás néha „Connection closed" → újrapróbálni. A read gyorsabban tér vissza, mint a falióra → türelmes pollozás vagy szerveroldali watcher.

---

## 1. n8n működési szabályok (gotchas — KÖTELEZŐ betartani)

- **Nagy workflow-szerkesztés CSAK a publikus REST-en** (`/api/v1` a `http://localhost:1234`-en), SOHA `update_workflow` MCP (~13k token → hibás válasz). Minta:
  1. `GET /api/v1/workflows/{id}` → backup.
  2. Python JSON-szerkesztés.
  3. `PUT /api/v1/workflows/{id}` — body **CSAK** `{name, nodes, connections, settings}`. A `settings`-ből csak az engedett kulcsok: `saveExecutionProgress, saveManualExecutions, saveDataErrorExecution, saveDataSuccessExecution, executionTimeout, errorWorkflow, timezone, executionOrder`. Az `availableInMCP`/`binaryMode` kulcsokat hagyd ki (n8n megőrzi).
  - A PUT az **aktív verziót** frissíti közvetlenül — nincs külön publish.
- Új workflow: `POST /api/v1/workflows` (body `{name,nodes,connections,settings}`) → visszaadja az `id`-t; aktiválás: `POST /api/v1/workflows/{id}/activate`.
- **Sikeres futások NEM mentődnek** (csak error/canceled jelenik meg az executions listában) → „nincs új error execution" = siker. (Kivétel: némelyik újabb workflow `saveDataSuccessExecution` miatt menti — pl. a fast sync 48580-as success látszott.)
- **Expression mezők**: a Code-ban SOHA `=` prefix; mindig `{{ ... }}` formátum (n8n tárolásnál teszi rá a `=`-t). Set node value, ami `=`-rel kezdődik, futásidőben kiértékeli a `{{...}}`-t → ellenőrizd/töröld a véletlen vezető `=`-t.
- **Anthropic node** válasza: `content[0].text`.
- **Code node JSON-kulcsok ASCII-only** (magyar ékezet a kulcsban → validációs hiba). Értékben mehet ékezet, de a szövegépítésnél `\uXXXX` a bevált.
- **Belső webhook hívás** Code/HTTP node-ból: `http://127.0.0.1:5678/webhook/<path>` (megerősítve, működik). A Cloudflare-on át (`n8n.codexpress.cloud`) **100 s válasz-timeout** van → minden webhook **korán válaszoljon** (early-respond), a nehéz munka utána fusson.
- **n8n DB (élő, WAL)**: `/var/lib/docker/volumes/n8n-cxxz_n8n_data/_data/database.sqlite`. DataTable **sor**-adat írása közvetlen SQLite-tal a bevett módszer (n8n a sor-adatot frissen olvassa; csak az oszlop-SÉMA lehet cache-elt). Mindig `PRAGMA busy_timeout=10000`.

---

## 2. Architektúra

Multi-tenant SaaS egyetlen háttérrendszerből:
- **n8n** (önállóan, Dockerben) — minden logika workflow-kban.
- **Qdrant** — termék + tudásbázis embeddingek; tenantonként `client_id` payload-szűrés.
- **Claude (Haiku)** — chat-válasz generálás (Anthropic node).
- **OpenAI `text-embedding-3-small`** — indexeléskor vektorizálás.
- **Admin/Stat** — statikus HTML a webrootban, n8n webhookokat hív.

Tenant-izoláció: minden config és minden Qdrant-pont a `client_id`-hoz kötött; a chat/sync mindig erre szűr.

---

## 3. Workflow-k (ID + webhook + szerep)

| Workflow | ID | Webhook | Node | Szerep |
|---|---|---|---|---|
| Chat | `7ZtoREZGxJUxLYFU` | `POST /webhook/chat` | 101 | Beszélgetés: retrieval+rerank, current-product injektálás, LLM, modulok |
| Ingest | `pbOOjl6Ad5KBQkOZ` | `POST /webhook/chat-ingest` | 12 | Tudásbázis-dokumentumok feltöltés/chunk/index |
| Admin | `zyCefQXtQ0c9ZsLt` | `POST /webhook/chat-admin` | 27 | Config/kupon/lead/dokumentum kezelés |
| Config | `gwGmkSVpSmI5i90Q` | `GET /webhook/chat-config` | 4 | Widget config kiszolgálás, per-tenant CORS |
| Stat API | `arkF2LcNO605RHvN` | `GET /webhook/stat-a49f070449f77ede5c6d234e` | 17 | Statisztika, megválaszolatlan, feedback |
| Popup | `ACVMhs9NUIIWFMPj` | `GET /webhook/chat-popup` | 8 | Proaktív popup logika |
| Sellvio Sync | `RMlmusDY3K58gm3N` | `POST /webhook/chat-sync-sellvio` | 15 | Termékszinkron |
| Shoprenter Sync | `GvzOXxllrtuTTPBK` | `POST /webhook/chat-sync` | 20 | Termékszinkron |
| Unas Sync | `48aImzQW4QEncluH` | `POST /webhook/chat-sync-unas` | 23 | Termékszinkron |
| WC Sync | `bnCd9mTgHVMNg8OZ` | `POST /webhook/chat-sync-woo` | 14 | Termékszinkron |
| Webdoc Sync (full) | `BRyFj4UvunsJY9ZA` | `POST /webhook/chat-sync-webdoc` | 14 | Feed-alapú teljes szinkron (auto-chunk) |
| **Webdoc PriceStock Fast** | `HrKM5Ca0eGRpYOJ3` | `POST /webhook/chat-sync-webdoc-fast` | 9 | **Payload-only ár/készlet (nincs embed)** |
| Sync Scheduler (nightly) | `kXRb4yknqkUEFQmL` | Schedule | — | Éjszakai teljes szinkron, platform szerint routol |
| **Webdoc Fast Scheduler** | `c1wI7ZgUdxH67e96` | Schedule (cron `*/10 * * * *`) | 4 | Gyors ár/készlet esedékesség (modulo-kapu) |

**Chat input contract** (`POST /webhook/chat`, allowedOrigins `*`):
```json
{ "client_id": "...", "session_id": "...", "message": "...", "type": "...",
  "history": [...], "page_context": { "is_product": true, "product_name": "...", "url": "..." } }
```
A `page_context.url` alapján injektálódik az AKTUÁLIS termék (lásd 9.).

---

## 4. Qdrant

- URL `http://qdrant:6333`, kollekció `cx_chatbot`.
- **Pont-ID** (determinisztikus UUID): `detUuid(client_id + ':' + <forrás-termék-id>)` — az FNV-alapú `detUuid` helper a sync Code node-okban (Build Product Points / Build PS azonos implementáció).
- **Payload séma (termék)**:
  `client_id, filename('__webdoc_products__' feednél), type('product'), text, name, price(str), url, sku, webdoc_id, brand, related_similar, related_additional, content_hash, available(bool), ps_hash`
- **content_hash**: SZEMANTIKUS ujjlenyomat (név|márka|kategória|leírás|paraméterek|url) — ez vezérli az újra-embedet. Ár/készlet NINCS benne.
- **ps_hash**: ár+készlet ujjlenyomat — ezt a gyors szinkron figyeli.
- Hasznos Qdrant-minták (node-on belül `this.helpers.httpRequest`):
  - Scroll: `POST /collections/cx_chatbot/points/scroll` `{filter:{must:[{key:'client_id',match:{value}},{key:'type',match:{value:'product'}}]}, limit:1000, with_payload:[...], with_vector:false}` + `offset=next_page_offset` lapozás.
  - Upsert: `PUT /collections/cx_chatbot/points?wait=true` `{points:[...]}` (batch ~200).
  - Payload-only batch: `POST /collections/cx_chatbot/points/batch?wait=true` `{operations:[{set_payload:{payload:{...},points:[id]}}, ...]}` (batch ~400) — **megerősítve működik**.
  - Count: `POST /collections/cx_chatbot/points/count` `{exact:true, filter:{...}}`.

---

## 5. DataTable-ök (ID + séma)

n8n DataTable tárolás: metaadat `data_table`, oszlop-registry `data_table_column` (`id,name,type,index,dataTableId`), sor-adat `data_table_user_<id>`.

| Tábla | ID | Tartalom |
|---|---|---|
| config | `ggNtMA5doynfs6Hn` | tenant-konfiguráció (lásd 6.) |
| plans | `4BaX90AeTicjEcpx` | `plan, live_api(bool), white_label(bool), monthly_limit(num)` |
| usage | `JzNYwNTfh1rH4uBI` | `client_id, period, conversations, notified_pct` |
| leads | `3RskHrJIWRntS2jf` | ember-átadásból rögzített leadek |
| coupons | `P4tJHZCaXejQkYzC` | `client_id, code, discount, kind, conditions, valid_until, active` |
| unanswered | `zZjInGVWN7WtqAPw` | megválaszolatlan kérdések |
| feedback | `mw7LIVgo0PaX3yzg` | 👍/👎 értékelések |

**DataTable írási megjegyzések:**
- A nyilvános DataTable REST PATCH/DELETE = **405** → sor-adat módosítás közvetlen SQLite-tal.
- **Oszlop hozzáadása** (megerősítve ebben a sessionben, restart NÉLKÜL látja az n8n): (1) `INSERT` a `data_table_column`-ba (`id`=random 16 char, `name`, `type`='number'/'string'/'boolean', `index`=következő, `dataTableId`); (2) `ALTER TABLE data_table_user_<id> ADD COLUMN <name> <DOUBLE/TEXT/BOOLEAN>`. Az n8n a sémát frissen olvassa (a `list_config` és a Scheduler `get` is azonnal látta az új `fast_sync_minutes`-t).
- Az `Upsert Config` node **defineBelow** explicit oszlop-térképet használ → új mezőhöz (a) kell a DataTable-oszlop, (b) be kell venni a node térképébe.

---

## 6. config DataTable — teljes mezőlista (`ggNtMA5doynfs6Hn`)

Sor-tábla: `data_table_user_ggNtMA5doynfs6Hn`. Oszlopok (index 0–23):

`client_id(0,str), platform(1,str), bot_name(2,str), header_color(3), bubble_color(4), welcome_message(5), system_prompt(6), lead_email(7), plan(8), launcher_position(9), active(10,bool), api_base(11), api_client_id(12), api_client_secret(13), auto_open(14,bool), auto_open_delay(15,num), proactive_message(16), proactive_product_message(17), public_url(18), stat_key(19), elallas_url(20), configurator_shop(21), popup_config(22,str-JSON), fast_sync_minutes(23,num)`

- **platform**: `sellvio|shoprenter|unas|woocommerce|webdoc|egyeb` — a nightly routing EZ alapján megy (lásd 7.4). Hibás platformnál a tenant kimarad a nightlyból.
- **api_base**: API base-URL; Webdoc esetén a JSON feed URL.
- **popup_config** (JSON string): `{enabled, trigger_product, product_delay, text_product, trigger_exit, text_exit, exit_coupon, exit_cta_label, exit_cta_url}`.
- **fast_sync_minutes** (ÚJ, index 23, type number): Webdoc gyors ár/készlet gyakorisága percben — `0`=ki, `60`=óránként (default ha hiányzik), `10/20/30`=sűrűbben. Registry oszlop-id: `laifBEY4thcq0kvn`.

---

## 7. Termékszinkron

### 7.1 Teljes szinkron (Webdoc referencia, `BRyFj4UvunsJY9ZA`)
Node-lánc: `Sync Webhook` → `Auth Sync?`(token eq) → `Get Sync Config`(dataTable get, filter `client_id` eq `query.client_id.lower`) → `Prep`(client_id/base/cid/sec a configból) → `Build Product Points`(letölti a feedet `base`-ről; sorokat épít; helperek: `dec/strip/huf/fnv32/hx/detUuid/catArr/relSimilarCat`; payload + content_hash[szemantikus] + ps_hash + available) → **`Respond Sync`** (korai `{started:true,total,client_id}`) → `Delta Filter`(Qdrant content_hash scroll, `CAP=3000`, `capped` flag, allIds FULL) → `Chunk Texts`(`SIZE=50`, üres tömb védelem `texts:[' ']`) → `Embed Products`(OpenAI text-embedding-3-small, `batchInterval 4000ms`, `maxTries 12`, `waitBetweenTries 6000ms`) → `Make Point`(chunk↔emb zip) → `Upsert Product Points`(PUT Qdrant, batch 200) → `Purge Stale`(skip ha capped) → `Continue`(önhívás `chat-sync-webdoc`-ra ha capped, 4 s fire-forget).
- **Auto-chunk**: nagy katalógusnál a `capped` lánc önhívással fut tovább, amíg a delta ki nem ürül (Cloudflare 100 s alatt marad). A korábbi kézi chunkolt seed elavult.
- **OOM-fix** (gyökérok megoldva): n8n szinkron progress-mentés kikapcsolva (`saveExecutionProgress:false`, `saveDataSuccessExecution:"none"`), így a ~750 MB payload nem blokkolja az event loopot. Streaming upsert (batch ~200) a nagy tömb-akkumuláció helyett.

### 7.2 Gyors ár/készlet szinkron (`HrKM5Ca0eGRpYOJ3`, ÚJ — ez a session)
Node-lánc: `Fast Webhook` → `Auth Fast` → `Get Config Fast` → `Prep Fast` → `Build PS`(letölti a feedet; termékenként `{id:detUuid, price, available, text, ps_hash}` — a text-helperek **bitre azonosak** a full sync BPP-jével) → **`Respond Fast`**(korai `{started,total}`) → `PS Delta`(Qdrant ps_hash scroll, csak a változott/hiányzó ps_hash-ú emittál) → `Set Payload`(Qdrant `/points/batch?wait=true` `set_payload`, `SIZE=400`, **nincs embed**). Auth-false → `Respond Forbidden` (403).
- A `set_payload` MERGE: csak `price, available, text, ps_hash` íródik felül; a vektor és a szemantikus mezők érintetlenek.
- Teszt (notebookstore, 12 691 termék): respond ~10 s, count stabil 12 691, a payload frissült (ps_hash/available/ár/text) embed nélkül.

### 7.3 Fast Scheduler (`c1wI7ZgUdxH67e96`, ÚJ — ez a session)
`Every 10 min`(cron `*/10 * * * *`) → `List Webdoc Configs`(dataTable get, filter `platform` eq `webdoc`, returnAll) → `Due Gate`(Code: `msm=óra*60+perc; tick=floor(msm/10)`; tenantonként `fsm=fast_sync_minutes||60`; ha `fsm<=0` skip; `step=round(fsm/10)`; due ha `tick%step==0` → emittál `{client_id}`) → `Fire Fast Sync`(httpRequest POST belső `chat-sync-webdoc-fast?token=...&client_id=...`, 4 s timeout, `onError:continueRegularOutput`).
- Állapotmentes modulo-kapu (nincs last-run tárolás). Megerősítve: 16:20-kor lefutott és meghívta a fast syncet (exec 48580 success).
- **Költség**: a gyors sync OpenAI-szinten ingyen (nincs token), DE a teljes feedet minden futáskor letölti (notebookstore ~70 MB). 10 perc ≈ ~10 GB/nap a forrásból; ezért nagy feednél óránkénti az ajánlott default. Sűrűbbnek csak akkor van értelme, ha a forrás-feed maga is gyakrabban frissül.

### 7.4 Nightly routing (`kXRb4yknqkUEFQmL`, `Build Targets` node)
```js
const MAP={ sellvio:'chat-sync-sellvio', woocommerce:'chat-sync-woo', unas:'chat-sync-unas',
            shoprenter:'chat-sync', webdoc:'chat-sync-webdoc' };
// platform → webhook; cid-enként dedup; belső http://localhost:5678/webhook/<path>?token=...&client_id=...
```
**KRITIKUS**: a `platform` mező nem szerepel a MAP-ben (pl. `egyeb`) → a tenant **kimarad** a nightlyból. Webdoc shopnál a platform legyen `webdoc`. (Ez a session: notebookstore `egyeb`→`webdoc` javítva — eddig nem kapott nightlyt.)

---

## 8. Admin felület

- Fájl: `/root/weboldal_fajlok/chatbot/admin.html` → `https://codexpress.cloud/chatbot/admin.html`. A `chat-admin` webhookot hívja.
- Auth: body `admin_token` == közös admin token (lásd 0.3). Akciók (Route Action switch): `list_config, save_config, list_leads, list_plans, delete_config, list_coupons` (+ kupon insert/update/delete, docs lista/törlés).
- `save_config` írási út: `Normalize` → `Get Existing Cfg` → `Prep Save Row`(stat_key generálás; elallas_url/configurator_shop/popup_config/**fast_sync_minutes** öröklés a meglévőből ha hiányzik, fsm default 60, 0 megőrződik) → `Upsert Config`(dataTable upsert, matching `client_id`, **defineBelow** explicit oszlop-térkép — MINDEN mezőt térképez, ezért a frontend a TELJES sort küldje, különben kiürülnek a nem küldött mezők).
- Frontend (admin.html) kulcs-függvények: `setForm()` (config→űrlap), `gatherForm()` (űrlap→row), `applyPlatformUI()` (platformfüggő mezők). A `fast_sync_minutes` legördülő (Webdoc-only) a Szinkron kártyában: `wrap_fast_sync` / `f_fast_sync_minutes` (Auto60/30/20/10/Ki); `applyPlatformUI` csak `webdoc`-nál mutatja.
- **Cache**: admin.html/widget módosítás után böngésző Ctrl+F5, szükség esetén Cloudflare cache-purge az adott fájlra.

---

## 9. Widget / beágyazás

- A láblécbe **dinamikus IIFE script-injektálás**: JS hozza létre a `<script>` elemet, `src` + `async` + `setAttribute('data-client-id', ID)` + `append`. **Soha** statikus `<script data-client-id>` — az Unas admin lestrippeli az egyedi attribútumokat. Nem `type=module`.
- **Biztonsági hardening** (Mastercool/Google Ads incidens után): iframe `sandbox`; wildcard `postMessage` target → explicit origin; bejövő origin szűrés; a `chat-config` (`gwGmkSVpSmI5i90Q`) per-tenant CORS-validációval. **Nyitott**: 6 kliens fail-open CORS, domain-megerősítésre vár — `ecowindoor, plcomfort, 4mfrigo, rmweb, nagyonallatshop, notebookstore` (8/14 már domainhez kötve).
- Current-product injektálás: a chat a `page_context.url` alapján a megnyitott termék adatait a kontextusba teszi (`# AKTUALIS TERMEK` blokk).

---

## 10. Platform-beállítás (kulcsok / forrás)

| Platform | Hitelesítés / forrás | Sync webhook |
|---|---|---|
| Shoprenter | OAuth `client_id`+`client_secret` + API base (`…api2.myshoprenter.hu/api/`) | `chat-sync` |
| Sellvio | OAuth `client_id`+`client_secret` + shop URL (REST v2 olvasásra; bulk write a Forrás-importtal) | `chat-sync-sellvio` |
| Unas | API-kulcs (login→token) | `chat-sync-unas` |
| WooCommerce | Consumer Key (`ck_`)+Secret (`cs_`) + shop URL | `chat-sync-woo` |
| Webdoc / feed | JSON feed URL (nincs OAuth/API) | `chat-sync-webdoc` (+ `-fast`) |

---

## 11. Funkció-modulok (chat workflow)

- **Hibrid retrieval + rerank**: dense + lexikai + token-boost.
- **Aktuális termék**: `page_context.url`-horgony (`# AKTUALIS TERMEK`).
- **Kupon**: `chatbot_coupons` (P4tJHZCaXejQkYzC) — aktív, nem lejárt; a bot AJÁNL, a működő kupont a webshop saját adminjában is létre kell hozni.
- **Lead / ember-átadás**: e-mail a `lead_email`-re.
- **Visszajelzés** 👍/👎: `chatbot_feedback` (mw7LIVgo0PaX3yzg).
- **Megválaszolatlan**: `chatbot_unanswered` (zZjInGVWN7WtqAPw) → tudásbázis-bővítés az Ingesten.
- **Elállás**: `elallas_url` alapján gomb a chatben (2026.06.19-től kötelező tájékoztató + nyilatkozat).
- **Popup**: termék- és kilépési trigger a `popup_config` szerint.
- **Konfigurátor** (opcionális): `configurator_shop` — pl. klíma ár-kalkulátor a chatben (klíma backend `68vt4CG4MNJkHRDe`).

---

## 12. Ez a session — elvégzett változások

1. **content_hash szétválasztás**: a Webdoc `Build Product Points`-ban a content_hash már csak szemantikus; új `ps_hash` (ár+készlet) és `available`(bool) a payloadban. (PUT, `BRyFj4UvunsJY9ZA`.)
2. **Fast sync workflow** létrehozva+aktiválva (`HrKM5Ca0eGRpYOJ3`, `chat-sync-webdoc-fast`) — payload-only `set_payload`, nincs embed. Tesztelve: count stabil, payload frissül.
3. **Fast Scheduler** (`c1wI7ZgUdxH67e96`, cron `*/10`, modulo-kapu) — aktiválva, lefutás megerősítve.
4. **fast_sync_minutes oszlop** (config DataTable, index 23) hozzáadva (registry+ALTER); n8n restart nélkül látja.
5. **Admin write path**: `Upsert Config` térkép + `Prep Save Row` normalizálás kiegészítve; save round-trip tesztelve (perzisztál, más mező nem ürül).
6. **Admin UI**: webdoc-only `fast_sync_minutes` legördülő az admin.html-ben (backup mentve).
7. **Platform-fix**: notebookstore `egyeb`→`webdoc` (nightly routing + scheduler pickup + admin display). Mellékhatás: eddig kimaradt a nightlyból, mostantól fut.
8. notebookstore production default `fast_sync_minutes=60`.

---

## 13. Hibakeresés

| Tünet | Teendő |
|---|---|
| Nem fut a szinkron egy shopra | `platform` mező! a nightly routing platform szerint megy; rossz platformnál kimarad (7.4) |
| Elavult ár/készlet (feed shop) | `fast_sync_minutes` növelése; a forrás-feed frissülési gyakoriságának ellenőrzése |
| Widget/admin nem frissül | böngésző/Cloudflare cache → Ctrl+F5, cache-purge |
| Embed 400 „0 input" | üres delta — a Chunk Texts `texts:[' ']` fallback fedezi |
| OOM / konténer-crash szinkronnál | progress-mentés kikapcsolva maradjon (7.1); streaming upsert |
| Megválaszolatlan szaporodik | Ingest tudásfeltöltés vagy `system_prompt` pontosítás |
| Havi limit elérve | `plans.monthly_limit` — plan-váltás |
| Kupon nem érvényes pénztárnál | a webshop saját adminjában is létre kell hozni |

---

## 14. Aktuális állapot / nyitott pontok

- **notebookstore**: 12 691/12 691 Qdrant-ban; `platform=webdoc`; `fast_sync_minutes=60`. Feed: `https://notebookstore.hu/export/aD6hG3iO1bG0wU3nL2lH.json` (~70 MB, 16 disztinkt upgrade-árpont a konfigurátorhoz).
- **CORS fail-open (domain-megerősítésre vár)**: ecowindoor, plcomfort, 4mfrigo, rmweb, nagyonallatshop, notebookstore.
- **Cloudflare MCP** csak Workers/D1/KV/R2 — DNS/Tunnel/Rules kézi dashboard. Új konténer: proxied A-rekord + Origin Rule (port-rewrite).
- **Branded docx-ek** (ügyfél-kiajánlók) generálva: `/root/weboldal_fajlok/docs/CodeXpress-AI-Chatbot-{Kiajanlo,Reszletes,Technikai-Kezikonyv}.docx` (publikus URL kintről). A host a saját publikus domainjét belülről nem éri el (curl 000) — kintről jó.
- docx generálás a VPS-en: `apt-get install -y python3-docx` (host pythonban nincs pip); logó `/root/weboldal_fajlok/assets/codexpress-logo.png` (108 KB); accent `#a08b6e`.

---

*Vége. A titkok futásidőben a VPS-ről olvasandók (0.3). Élő rendszer — módosítás előtt manuális Hostinger-snapshot ajánlott.*

---

# C. RÉSZ — Widget ↔ backend I/O kontaktus (widget.js `?v=fb1` alapján, 100% pontos)

> Ez a Fázis 1 chat-szerviz **pontos szerződése**. Az új `POST /chat`-nak ezt a választ kell adnia, hogy a widget változatlanul működjön (a beillesztő kód nem módosul).

## C.1 Endpontok (widget → backend)
- `GET /webhook/chat-config?client_id=<id>` (credentials: omit) → tenant megjelenítési config (a widget `DEFAULTS`-szal merge-eli).
- `POST /webhook/chat` — a `type` mező szerint multiplexelt (lásd C.3–C.4).
- `GET /webhook/chat-popup?...` → popup teaser (`cxTeaser`).

## C.2 `chat-config` válasz (amit a widget használ)
A widget ezeket a kulcsokat olvassa (DEFAULTS-szal merge): `bot_name, header_color, bubble_color, welcome_message, launcher_position, powered_by, auto_open, auto_open_delay, proactive_message`, és `popup: { enabled, trigger_product, product_delay, trigger_exit, text_product, text_exit, exit_coupon, exit_cta_label, exit_cta_url }`. (A teljes config-mezőkészlet a B. rész 6. pontjában; a widgetnek ez a részhalmaz kell.) **CORS: per-tenant** (lásd B. rész 6.2) — `Vary: Origin`.

## C.3 `POST /webhook/chat` — ÜZENET (a fő hívás)
**Kérés:**
```json
{ "client_id": "...", "session_id": "...", "message": "...",
  "history": [ { "role": "user|assistant", "content": "..." } ],
  "page_context": { "is_product": true, "product_name": "...", "url": "..." } }
```
- `history`: az utolsó 10 üzenet. `page_context` lehet `null`.

**Válasz (a widget EZT várja):**
```json
{ "reply": "<markdown válasz>",
  "action": "collect_lead" | "order_status_form" | "quote_configurator" | null,
  "configurator": { "config_url": "...", "calculate_url": "...", "email_url": "..." } }
```
- **`reply`** (KÖTELEZŐ): markdown, a widget `mdToHtml`-lel rendereli. Hiányában fallback: „Elnézést, most nem tudok válaszolni.".
- **`action`** (opcionális):
  - hiányzik / `null` → a widget **👍/👎 visszajelző sort** mutat a válasz alatt.
  - `"collect_lead"` → e-mail + telefon űrlap (`showLead`).
  - `"order_status_form"` → rendelésszám + e-mail űrlap (`showOrderForm`).
  - `"quote_configurator"` → konfigurátor a `configurator` objektummal (`showConfigurator`).
- **`configurator`**: csak `action=quote_configurator` esetén; `config_url` kötelező benne.

## C.4 `POST /webhook/chat` — ESEMÉNYEK (`type` mezővel; a válasz IGNORÁLVA, csak `.catch`)
- **Visszajelzés:** `{ client_id, session_id, type:"feedback", rating:"up"|"down", question, answer, page_context }`
- **Lead (űrlapból):** `{ client_id, session_id, type:"lead", email, phone, history }`
- **Lead (konfigurátorból):** `{ client_id, session_id, type:"lead", source:"configurator", name, email, phone, message, history:[] }`

→ A `/chat` dispatch a `type` szerint: **nincs `type`** → üzenet (C.3); **`feedback`** → feedback tárolás (`chatbot_feedback`); **`lead`** → lead tárolás (`chatbot_leads`) + handoff e-mail a `lead_email`-re.

## C.5 Rendelés-státusz
Az `order_status_form` beküldése **NEM külön type** — egy NORMÁL üzenet:
`message: "rendelésszám #<num>, e-mail: <email>"` (a `/chat` parse-olja, majd a platform-adapter lekérdezi). A válasz a szokásos `reply`.

## C.6 Konfigurátor al-endpontok (a `configurator` objektum URL-jei — KÜLÖN a `/chat`-tól)
- `GET config_url` → `{ steps:[ {type, ...}, ... ], companyInfo:{...} }` (a `customer_form` típusú lépés a végére kerül).
- `POST calculate_url` `{ customer, answers, customValues, timestamp }` → `{ items:[...], total, notifyEmail, companyInfo }`.
- `POST email_url` `{ email, customer, answers, customValues, result, companyInfo }`.
- (Ez a meglévő klíma-konfigurátor backend, `!  - KLÍMA KONFIGURÁTOR - Multi-tenant Backend` / `68vt4CG4MNJkHRDe`. Az új chat-mag csak `action=quote_configurator`-ral ide irányít — nem kell újraírni.)

## C.7 Session
A `session_id`-t a widget kezeli (`sessionStorage` kulcs: `cx_sess_<clientId>`, formátum `s_<ts>_<rand>`). A backend a session-állapotot (history-n túli kontextus, rate-limit, usage-számlálás) a `session_id` köré építse. A widget amúgy is küldi az utolsó 10 `history`-t minden kérésben.

## C.8 Fázis-1 következmény (KRITIKUS)
Az új `POST /chat`-nak pontosan ezt a séma-szerződést kell teljesítenie (reply + opcionális action + configurator) ÉS a `type`-multiplexálást kezelnie. Ha igen, a widget **változatlanul** ráköthető (csak az endpoint-bázis cseréje kell a cutovernél — ami a `chat-config`-ból vagy a widget endpoint-konstansból jön). A widget beillesztő kódja és a `widget.js` logikája **nem módosul**.

*Vége (C. rész).*
