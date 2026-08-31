"""m96: VALASZ-ORSEG - tenant-szintu kapcsolat-redakcio a mar legeneralt valaszon.

Kivalto ugyfel-keres (Kontur Reklam, 2026-08): (1) a bot ne adja ki az
info@konturreklam.hu cimet, (2) telefonszamot csak akkor adjon, ha rakerdeztek.

MERES a valodi korpuszon (messages, 54 valodi konturreklam valasz):
  - 23 valaszban (43%) kiment az e-mail-cim
  - 24 valaszban (44%) kiment a telefonszam UGY, hogy nem kerdeztek ra
Az ok nem modell-szeszely: a system_prompt maga utasitotta ra ("kerd, hogy irjon az
info@... cimre", "Add meg a telefonszamot is"), es a KB 7 dokumentumaban 16 helyen
szerepel az e-mail, 11 helyen a telefonszam. A prompt-kor (d31a) ezt 0/7-re vitte le,
DE a prompt valoszinusegi -- garanciat csak kod-szintu utoellenorzes ad. Ugyanaz az
osztaly, mint a m77 (onismetles) es a m87 (nem-latin szo): ott is bebizonyosodott,
hogy a prompt-szabaly nem eleg.

TENANT-KAPU: a szabalyok a `tenants.answer_policy` JSONB-bol jonnek. Ha egy tenantnak
nincs answer_policy-ja (ma 15-bol 14 ilyen), a modul ERINTETLENUL adja vissza a
valaszt -- nulla kockazat a tobbi boltra.

Stdlib-only es fajlbol betoltheto (importlib.spec_from_file_location), mert a suite
mas tesztjei fake ``app.services`` csomagot hagynak a sys.modules-ben (kf/13, m80b,
m87, m89 tanulsaga).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

__all__ = [
    "deaccent",
    "user_history_text",
    "phone_requested",
    "phone_pattern",
    "redact_emails",
    "gate_phones",
    "apply_policy",
]

# Mondathatar: irasjel + whitespace. Soronkent bontunk, hogy a listaelemek
# (- ...) es a bekezdesek ne ragadjanak ossze.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_ORPHAN_PUNCT = re.compile(r"\s+([,.;:!?])")
_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINL = re.compile(r"\n{3,}")
# m96/1: a kivagott szam helyen maradt bevezeto tagmondat ("..., hivd az irodat:")
# -- csak sor VEGEN, es csak olyan soron, amelyben tenyleg volt talalat.
_TRUNCATED_TAIL = re.compile(r"[,;]?\s*[^,;.!?]*:\s*[.!?]?\s*$")

# A latogato telefon-szandeka. Ekezet nelkul illesztunk (lasd deaccent).
# TUDATOSAN szuk: a "hiv" ontonek FP-je lenne a "hivatalos" / "hivatkozas",
# ezert csak a valodi igei alakok szerepelnek.
_PHONE_INTENT = re.compile(
    r"\b(telefon|mobil|elerhetos|elerhetoseg|felhiv|hivj|hivn|hivh|hivas|hivlak"
    r"|szamotok|szamod|hivhato)",
    re.I,
)

# Fail-safe a mondat-dobasra. A rata NEM azt vedi, hogy sok szoveg maradjon --
# egy telefonos mondat eldobasa akkor is helyes, ha a valasz felet teszi ki --,
# hanem hogy ne maradjon foszlany. m96/1 eles lelet: 0.5-tel a tipikus ketmondatos
# valasz (0,40 arany) a durvabb szam-kivagas agra esett, es csonkot hagyott.
_MIN_KEEP_RATIO = 0.25
_MIN_KEEP_CHARS = 20

# m96/2: vegso menedek, ha a takaritas utan semmi nem maradna es a tenant
# nem adott meg empty_fallback-et. Sose az eredeti valasz -- az szivarogtatna.
_EMPTY_SAFE = "Ebben a k\u00e9rd\u00e9sben az aj\u00e1nlatk\u00e9r\u0151 oldalunkon tudunk seg\u00edteni."


def deaccent(s: Any) -> str:
    """Ekezet-mentesitett kisbetus valtozat a szandek-detektorhoz."""
    txt = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in txt if not unicodedata.combining(c)).lower()


def user_history_text(history: Any) -> str:
    """CSAK a latogato uzenetei a historybol.

    Fontos: a bot sajat korabbi valaszat NEM szabad beleszamitani a
    telefon-szandekba -- ha egyszer kiirta, hogy "hivj minket", attol meg a
    latogato nem kert telefonszamot, es a kapu orokre kinyilna.
    """
    out = []
    for h in history or []:
        role = getattr(h, "role", None)
        content = getattr(h, "content", None)
        if role is None and isinstance(h, dict):
            role = h.get("role")
            content = h.get("content")
        if str(role or "").lower() == "user" and content:
            out.append(str(content))
    return " ".join(out)


def phone_requested(*texts: Any) -> bool:
    """Kerte-e a latogato a telefonos elerhetoseget (uzenet + sajat elozmenyei)."""
    joined = " ".join(deaccent(t) for t in texts if t)
    return bool(_PHONE_INTENT.search(joined))


def phone_pattern(number: Any) -> re.Pattern | None:
    """Rugalmas regex EGY telefonszamra.

    A szam utolso 9 szamjegyet ("707700396") illeszti tetszoleges elvalasztoval,
    opcionalis +36 / 06 elotaggal es a magyar toldalekkal ("-os szamon").
    Igy elkapja a "+36 70 770 0396", "06 70 770 0396", "70/770-0396" alakokat is.
    """
    digits = re.sub(r"\D", "", str(number or ""))
    if len(digits) < 9:
        return None
    core = digits[-9:]
    sep = r"[\s\-/().]*"
    body = sep.join(re.escape(d) for d in core)
    return re.compile(r"(?:\+?\s*36|\b06)?" + sep + body + r"(?:-?[oöa-z]{1,3})?", re.I)


def _drop_sentences(text: str, rx: re.Pattern) -> str:
    """A mintat tartalmazo MONDATOK eldobasa, sorszerkezet megtartasaval."""
    out = []
    for line in text.split("\n"):
        if not line.strip() or not rx.search(line):
            out.append(line)
            continue
        parts = _SENT_SPLIT.split(line)
        keep = [p for p in parts if not rx.search(p)]
        new_line = " ".join(x.strip() for x in keep if x.strip()).strip()
        # a kiurult listaelem/sor eltunik (nem hagyunk arva "-" jelet)
        if new_line:
            out.append(new_line)
    return "\n".join(out)


def _scrub_only(text: str, rx: re.Pattern) -> str:
    """Vegso fail-safe: csak magat a szamot vagjuk ki, a mondat marad.

    m96/1: a puszta kivagas csonkot hagyott ("hivd az irodat:."), ezert a
    szam helyen maradt bevezeto tagmondatot is eldobjuk. SORONKENT dolgozunk
    es csak az ERINTETT sorokat nyuljuk -- kulonben egy legitim listafelvezeto
    kettospont ("A meretek a kovetkezok:") is aldozatul esne.
    """
    out = []
    for line in text.split("\n"):
        if not rx.search(line):
            out.append(line)
            continue
        new = rx.sub("", line)
        # a szam helyen maradt csonk: "..., hivd az irodat: ." / "vagy hivhatsz:"
        new = _TRUNCATED_TAIL.sub("", new).rstrip()
        new = _ORPHAN_PUNCT.sub(r"\1", new)
        new = _MULTISPACE.sub(" ", new).strip()
        if new and new[-1] not in ".!?:":
            new += "."
        if new:
            out.append(new)
    return "\n".join(out)


def _tidy(text: str) -> str:
    return _MULTINL.sub("\n\n", text).strip()


def redact_emails(reply: str, emails, replacement: str = "") -> tuple[str, int]:
    """A tiltott e-mail-cimek csereje. Determinisztikus, nem valoszinusegi."""
    txt = str(reply or "")
    n = 0
    for addr in emails or []:
        addr = str(addr or "").strip()
        if not addr:
            continue
        rx = re.compile(re.escape(addr), re.I)
        found = len(rx.findall(txt))
        if found:
            n += found
            txt = rx.sub(replacement, txt)
    return txt, n


def gate_phones(reply: str, numbers, asked: bool) -> tuple[str, int]:
    """Telefonszam-kapu: ha NEM kertek, a szamot tartalmazo mondat eldobasa.

    Ket lepcso, mert a mondat-dobas tul sokat vihet: ha az eredmeny az
    eredeti felenel rovidebb lenne, csak magat a szamot vagjuk ki.
    """
    txt = str(reply or "")
    if asked:
        return txt, 0
    hits = 0
    for num in numbers or []:
        rx = phone_pattern(num)
        if rx is None:
            continue
        found = len(rx.findall(txt))
        if not found:
            continue
        hits += found
        dropped = _drop_sentences(txt, rx)
        if (len(dropped.strip()) >= _MIN_KEEP_CHARS
                and len(dropped.strip()) >= len(txt.strip()) * _MIN_KEEP_RATIO
                and not rx.search(dropped)):
            txt = dropped
        else:
            txt = _scrub_only(txt, rx)
    return txt, hits


def apply_policy(reply: str, policy: Any, user_text: Any = "",
                 history: Any = None) -> tuple[str, dict]:
    """A teljes orseg egy hivasban.

    `history` a nyers /chat history-lista (pydantic vagy dict elemek) -- csak a
    latogato sajat uzeneteit vesszuk figyelembe.

    Vissza: (uj_valasz, {"email": n, "phone": n, "asked": bool}).
    Ha nincs policy vagy hibas, az EREDETI valaszt adja vissza (fail-safe).
    """
    info = {"email": 0, "phone": 0, "asked": False}
    if not isinstance(policy, dict) or not policy:
        return str(reply or ""), info
    try:
        txt = str(reply or "")
        emails = policy.get("redact_emails") or []
        repl = str(policy.get("email_replacement") or "")
        if emails:
            txt, n = redact_emails(txt, emails, repl)
            info["email"] = n
        phones = policy.get("gate_phones") or []
        if phones:
            hist = history if isinstance(history, str) else user_history_text(history)
            asked = phone_requested(user_text, hist)
            info["asked"] = asked
            txt, n = gate_phones(txt, phones, asked)
            info["phone"] = n
        txt = _tidy(txt)
        if not txt.strip():
            # m96/2: ures eredmeny -> NEM adhatjuk vissza az eredetit, mert az
            # pont a redaktalt adatot engedne ki (eles pytest-lelet: a teljes
            # egeszeben telefonos valasznal a szam visszakerult). Sorrend:
            # tenant-fallback -> nyers, szam nelkuli valtozat -> semleges konstans.
            fb = str(policy.get("empty_fallback") or "").strip()
            if fb:
                return fb, info
            bare = str(reply or "")
            for num in (policy.get("gate_phones") or []):
                rx0 = phone_pattern(num)
                if rx0 is not None:
                    bare = rx0.sub("", bare)
            for addr in (policy.get("redact_emails") or []):
                if addr:
                    bare = re.sub(re.escape(str(addr)), repl, bare, flags=re.I)
            bare = _ORPHAN_PUNCT.sub(r"\1", bare)
            bare = _MULTISPACE.sub(" ", bare).strip()
            return (bare or _EMPTY_SAFE), info
        return txt, info
    except Exception:                # noqa: BLE001 - az orseg hibaja sose torje a valaszt
        return str(reply or ""), info
