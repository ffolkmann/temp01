"""m67 - qdrant payload-indexek build-idoben (ensure_collection / ensure_payload_indexes).

A qdrant.py-t fajlbol toltjuk fake app.core.settings-szel; a httpx-klienst
felvevo fake-re csereljuk. Ellenorizzuk: meglevo kollekcion csak a hianyzo
indexek jonnek letre; uj kollekcion a kollekcio + mind az 5 index; ha minden
megvan, nincs iras (idempotens).
"""

import asyncio
import importlib.util
import pathlib
import sys
import types

_app_snapshot = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
for _k in list(_app_snapshot):
    del sys.modules[_k]

for _name in ("app", "app.core"):
    _m = sys.modules.setdefault(_name, types.ModuleType(_name))
    _m.__path__ = []

_settings_mod = types.ModuleType("app.core.settings")
_settings_mod.get_settings = lambda: types.SimpleNamespace(
    qdrant_url="http://q:6333", qdrant_collection="cx_test"
)
sys.modules["app.core.settings"] = _settings_mod

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("qdrant_m67_under_test", ROOT / "app" / "core" / "qdrant.py")
_q = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_q)

for _k in [x for x in list(sys.modules) if x == "app" or x.startswith("app.")]:
    del sys.modules[_k]
sys.modules.update(_app_snapshot)


class _Resp:
    def __init__(self, code, data=None):
        self.status_code = code
        self._data = data or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeHttp:
    def __init__(self, exists=True, schema=None):
        self.exists = exists
        self.schema = dict(schema or {})
        self.puts: list[tuple[str, dict]] = []

    async def get(self, path):
        if not self.exists:
            return _Resp(404, {})
        payload_schema = {k: {"data_type": v, "points": 1} for k, v in self.schema.items()}
        return _Resp(200, {"result": {"payload_schema": payload_schema}})

    async def put(self, path, json=None):
        self.puts.append((path, json))
        if "/index" in path:
            self.schema[json["field_name"]] = json["field_schema"]
        else:
            self.exists = True
        return _Resp(200, {})


def _client(fake):
    c = _q.QdrantClient(url="http://q:6333", collection="cx_test")
    c._client = fake
    return c


def _index_fields(fake):
    return [j["field_name"] for p, j in fake.puts if "/index" in p]


def test_existing_collection_creates_only_missing_indexes():
    fake = _FakeHttp(exists=True, schema={"client_id": "keyword"})
    asyncio.run(_client(fake).ensure_collection("cx_test", 1536))
    assert not any(p == "/collections/cx_test" for p, _ in fake.puts)  # nincs re-create
    assert sorted(_index_fields(fake)) == ["available", "sku", "type", "url"]
    put_path = [p for p, _ in fake.puts if "/index" in p][0]
    assert put_path == "/collections/cx_test/index?wait=true"


def test_new_collection_gets_all_indexes():
    fake = _FakeHttp(exists=False)
    asyncio.run(_client(fake).ensure_collection("cx_test", 1536))
    assert fake.puts[0][0] == "/collections/cx_test"
    assert sorted(_index_fields(fake)) == ["available", "client_id", "sku", "type", "url"]
    bools = [j for _, j in fake.puts if j and j.get("field_name") == "available"]
    assert bools == [{"field_name": "available", "field_schema": "bool"}]


def test_all_present_is_noop():
    fake = _FakeHttp(exists=True, schema=dict(_q._PAYLOAD_INDEXES))
    asyncio.run(_client(fake).ensure_collection("cx_test", 1536))
    assert fake.puts == []


def test_ensure_payload_indexes_idempotent_second_run():
    fake = _FakeHttp(exists=True, schema={})
    c = _client(fake)
    asyncio.run(c.ensure_payload_indexes("cx_test"))
    n1 = len(fake.puts)
    asyncio.run(c.ensure_payload_indexes("cx_test"))
    assert len(fake.puts) == n1 == 5
