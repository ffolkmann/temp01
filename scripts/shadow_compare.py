"""Shadow parity — ugyanazt a kérdéslistát elküldi az ÉLES n8n-re ÉS a lokális /chat-re,
és egymás mellé írja a két választ + latencyt.

GUARDRAIL: az éles n8n chat-webhookja read-only művelet (retrieval + LLM); ez a
felhasználói kérdéssel egyenértékű hívás, nem módosít prod adatot.

Futtatás (host):
    python scripts/shadow_compare.py
    python scripts/shadow_compare.py kerdesek.txt        # soronként egy kérdés

Env:
    LOCAL_CHAT_URL   default http://localhost:8000/chat
    PROD_CHAT_URL    default https://n8n.codexpress.cloud/webhook/chat
    CLIENT_ID        default teslashop
"""

import os
import sys
import time
import uuid

import httpx

LOCAL_URL = os.getenv("LOCAL_CHAT_URL", "http://localhost:8000/chat")
PROD_URL = os.getenv("PROD_CHAT_URL", "https://n8n.codexpress.cloud/webhook/chat")
CLIENT_ID = os.getenv("CLIENT_ID", "teslashop")

DEFAULT_QUESTIONS = [
    "Milyen felnikupakokat ajánlasz a Model 3 Highlandhez?",
    "Van valami kedvezmény most?",
    "Mennyibe kerül a TESERY Aero DISC felnikupak?",
    "Milyen tartozékokat ajánlasz a Model Y-hoz?",
    "Adtok-e elállási lehetőséget?",
    "Szeretnék beszélni egy kollégával, hogyan tudok?",
]


def _load_questions() -> list[str]:
    if len(sys.argv) > 1:
        path = sys.argv[1]
        lines = [l.strip() for l in open(path, encoding="utf-8")]
        return [l for l in lines if l]
    return DEFAULT_QUESTIONS


def _body(message: str) -> dict:
    return {
        "client_id": CLIENT_ID,
        "session_id": f"shadow_{uuid.uuid4().hex[:8]}",
        "message": message,
        "history": [],
        "page_context": None,
    }


def _call(client: httpx.Client, url: str, message: str) -> tuple[str, float, str]:
    t0 = time.perf_counter()
    try:
        r = client.post(url, json=_body(message), timeout=120)
        dt = time.perf_counter() - t0
        try:
            data = r.json()
            reply = data.get("reply") if isinstance(data, dict) else str(data)
        except Exception:
            reply = r.text
        return (reply or "(üres reply)", dt, f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        dt = time.perf_counter() - t0
        return (f"(hiba: {e})", dt, "ERROR")


def _wrap(text: str, width: int = 70) -> list[str]:
    out: list[str] = []
    for para in (text or "").splitlines() or [""]:
        if not para:
            out.append("")
            continue
        line = ""
        for word in para.split(" "):
            if len(line) + len(word) + 1 > width:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
    return out


def main() -> None:
    questions = _load_questions()
    print(f"client_id={CLIENT_ID}")
    print(f"PROD  = {PROD_URL}")
    print(f"LOCAL = {LOCAL_URL}")
    with httpx.Client() as client:
        for i, q in enumerate(questions, 1):
            prod_reply, prod_dt, prod_status = _call(client, PROD_URL, q)
            local_reply, local_dt, local_status = _call(client, LOCAL_URL, q)

            print("\n" + "=" * 150)
            print(f"[{i}] {q}")
            print(f"    PROD  {prod_status}  {prod_dt*1000:7.0f} ms   |   LOCAL {local_status}  {local_dt*1000:7.0f} ms")
            print("-" * 150)
            pl = _wrap(prod_reply)
            ll = _wrap(local_reply)
            n = max(len(pl), len(ll))
            print(f"{'PROD (n8n)':<73} | LOCAL (/chat)")
            for j in range(n):
                left = pl[j] if j < len(pl) else ""
                right = ll[j] if j < len(ll) else ""
                print(f"{left:<73} | {right}")


if __name__ == "__main__":
    main()
