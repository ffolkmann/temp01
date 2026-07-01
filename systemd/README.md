# CodeXpress sync — systemd nightly timer

Az `app.sync` streamelő termék-szinkront futtatja minden aktív tenantra éjszakánként a
`cx_chatbot_v2` Qdrant kollekcióba (az n8n nightly Sync Scheduler kiváltása). Az élő chat
read-kollekcióját nem érinti.

## Telepítés (VPS, root)

```bash
# a repo /docker/chatbot-prod alatt van; a compose fájl docker-compose.prod.yml
cp systemd/cx-sync.service systemd/cx-sync.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cx-sync.timer
```

## Ellenőrzés

```bash
systemctl list-timers cx-sync.timer          # következő futás
systemctl start cx-sync.service              # kézi indítás (egyszeri)
journalctl -u cx-sync.service -f             # log (tenantonkénti JSON összegzők)
```

## Megjegyzések

- A `.service` `docker compose run --rm api python -m app.sync --all`-t hív; a `WorkingDirectory`
  a `/docker/chatbot-prod` (ahol a `docker-compose.prod.yml` van). Ha más a compose-fájl neve/útja,
  igazítsd a `.service` `ExecStart`/`WorkingDirectory` sorát.
- Ütemezés: `OnCalendar=*-*-* 03:30` + `Persistent=true` (kihagyott futás bepótlása) +
  `RandomizedDelaySec=300` (jitter). Módosításhoz szerkeszd a `.timer`-t és `daemon-reload`.
- Ár/készlet gyors frissítés (`--pricestock`) külön timerrel adható hozzá, ha kell (pl. óránként):
  másold a `.service`-t `python -m app.sync --all --pricestock`-kal, és tegyél mellé sűrűbb `.timer`-t.
- Egy tenant kézi (dry-run) próbája:
  `docker compose -f docker-compose.prod.yml run --rm api python -m app.sync --tenant fishingoutlet --dry-run`
