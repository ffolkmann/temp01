"""Közös DataTable -> Postgres koerció + séma.

Ezt osztja a `seed_dev.py` (JSON seed -> Postgres, dev) és a
`migrate_from_n8n.py` (élő n8n SQLite -> Postgres, prod parity). A koerciós
logika EGY helyen él, hogy a két út bitre ugyanúgy alakítsa az adatot.

A séma (bool/number oszlopok) forrása az n8n `data_table_column` registry:
 - dev:    a `seed/columns.json` (ennek exportja),
 - migrate: az élő SQLite `data_table_column` tábla (lásd `schema_from_db`).
A `popup_config` kivétel: az n8n-ben string-JSON, a registry is "string"-nek
jelöli, de Postgresben jsonb -> ezért külön `json_cols` halmazban kezeljük.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"

# --- DataTable ID-k (B. rész 5.) ---
TID_TENANTS = "ggNtMA5doynfs6Hn"   # config
TID_PLANS = "4BaX90AeTicjEcpx"     # plans
TID_COUPONS = "P4tJHZCaXejQkYzC"   # coupons

# n8n sor-metaadat, amit eldobunk (a Postgres modellben nincs megfelelője)
DROP = frozenset({"id", "createdAt", "updatedAt"})

# A tenants tábla mezője, ami n8n-ben string-JSON, Postgresben jsonb
TENANT_JSON = frozenset({"popup_config"})


# --------------------------------------------------------------------------- #
# Koerció (a régi seed_dev.py-ből emelve — egyetlen forrás)
# --------------------------------------------------------------------------- #
def to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "igen"}
    return False


def to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_json(v):
    if v is None or v == "":
        return None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------- #
# Séma: dataTableId -> { oszlopnév -> "boolean" | "number" | "string" }
# --------------------------------------------------------------------------- #
def _index_columns(columns) -> dict[str, dict[str, str]]:
    """`data_table_column` sorokból ({name, type, dataTableId}) típus-térkép."""
    out: dict[str, dict[str, str]] = {}
    for c in columns:
        out.setdefault(c["dataTableId"], {})[c["name"]] = c["type"]
    return out


def schema_from_columns_json(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Dev: a seed/columns.json (data_table_column export) -> típus-térkép."""
    path = path or (SEED / "columns.json")
    return _index_columns(json.loads(path.read_text(encoding="utf-8")))


def schema_from_db(conn) -> dict[str, dict[str, str]]:
    """Migrate: az élő SQLite `data_table_column` táblából -> típus-térkép.

    `conn` egy read-only sqlite3.Connection (sqlite3.Row factoryval).
    """
    rows = conn.execute(
        "SELECT name, type, dataTableId FROM data_table_column"
    ).fetchall()
    return _index_columns([dict(r) for r in rows])


# --------------------------------------------------------------------------- #
# Sor-tisztítás: n8n DataTable sor -> Postgres-kész dict
# --------------------------------------------------------------------------- #
def clean_row(
    col_types: dict[str, dict[str, str]],
    table_id: str,
    row: dict,
    json_cols: frozenset = frozenset(),
    keep: frozenset | None = None,
) -> dict:
    """Egy DataTable-sort Postgres-kész dict-té alakít.

    - a DROP mezőket eldobja,
    - json_cols -> to_json (popup_config),
    - a registry szerinti boolean/number -> to_bool/to_num,
    - minden más változatlan string,
    - ha `keep` adott (a célmodell oszlopai), az azon kívüli oszlopokat
      eldobja (drift-védelem: új n8n-oszlop ne döntse el a betöltést).
    """
    types = col_types.get(table_id, {})
    out: dict = {}
    for k, v in row.items():
        if k in DROP:
            continue
        if keep is not None and k not in keep:
            continue
        if k in json_cols:
            out[k] = to_json(v)
        elif types.get(k) == "boolean":
            out[k] = to_bool(v)
        elif types.get(k) == "number":
            out[k] = to_num(v)
        else:
            out[k] = v
    return out
