# -*- coding: utf-8 -*-
"""m115: lead-ertesito e-mail - ekezetes szoveg + formazott HTML (stdlib-only, tiszta fuggvenyek).

Ugyfel-visszajelzes (notebookstore, 2026-10-13): a regi level nyers szoveg volt ekezet
nelkul ("Uj erdeklodo", "Latogato"), a bot valaszaban benne maradtak a markdown-jelek
(**, [szoveg](url)), a beszelgetes egybefolyt. Itt a level ket alakja keszul:
- text: ekezetes, markdown-jelek nelkul, a fordulok kozott ures sor (plain fallback);
- html: kartyas elrendezes, latogato/bot buborekok, kattinthato linkek.
A markdown-konverzio szuk es biztonsagos: elobb HTML-escape, utana csak **felkover**,
[szoveg](http(s)://...) link es sortores/felsorolas.
"""

import html as _html
import re

_LINK_RE = re.compile(r"\[([^\]\n]{1,300})\]\(((?:https?://|mailto:|tel:)[^\s)]{1,2000})\)")  # m118: +tel/mailto
_BOLD_RE = re.compile(r"\*\*([^*\n]{1,500})\*\*")


def md_to_text(s: str) -> str:
    """Markdown-jelek nelkuli sima szoveg: [a](u) -> 'a (u)', **x** -> x."""
    s = str(s or "")
    s = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", s)
    s = _BOLD_RE.sub(lambda m: m.group(1), s)
    return s.strip()


def md_to_html(s: str) -> str:
    """Szuk markdown -> biztonsagos HTML (escape elobb, utana a megengedett jelolesek)."""
    s = _html.escape(str(s or "").strip(), quote=False)

    def _link(m):
        url = m.group(2).replace('"', "%22")
        return (f'<a href="{url}" style="color:#1a56db;text-decoration:underline">'
                f"{m.group(1)}</a>")

    s = _LINK_RE.sub(_link, s)
    s = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", s)
    out = []
    for line in s.split("\n"):
        st = line.strip()
        if st.startswith("- ") or st.startswith("* "):
            out.append("&bull;&nbsp;" + st[2:])
        else:
            out.append(line)
    return "<br>".join(out)


def build_lead_email(*, client_id, name, email, phone, message, source,
                     reply_to, turns, bot_name):
    """turns: [(kerdes, valasz), ...] idorendben. Vissza: (subject, text, html)."""
    bot = str(bot_name or "Bot")
    subject = f"Új érdeklődő – {client_id} chatbot"

    fields = [("Név", name), ("E-mail", email), ("Telefon", phone), ("Üzenet", message)]
    t = ["Új érdeklődő érkezett a chatbotból.", ""]
    t += [f"{k}: {v or '–'}" for k, v in fields]
    if source == "chat":
        t.append("Forrás: a látogató a chatbe írta be az elérhetőségét (nem a lead-űrlapon).")
    if reply_to:
        t += ["", f"Erre a levélre válaszolva közvetlenül az érdeklődőnek írsz ({reply_to})."]
    if turns:
        t += ["", "— TELJES BESZÉLGETÉS —", ""]
        for q, a in turns:
            if q:
                t += [f"Látogató: {md_to_text(q)}", ""]
            if a:
                t += [f"{bot}: {md_to_text(a)}", ""]
    text = "\n".join(t).rstrip() + "\n"

    e = lambda v: _html.escape(str(v or "–"), quote=False)  # noqa: E731
    rows = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#6b7280;white-space:nowrap">{k}</td>'
        f'<td style="padding:4px 0;color:#111827"><strong>{e(v)}</strong></td></tr>'
        for k, v in fields
    )
    notes = ""
    if source == "chat":
        notes += ('<p style="margin:12px 0 0;color:#6b7280;font-size:13px">Forrás: a látogató '
                  "a chatbe írta be az elérhetőségét (nem a lead-űrlapon).</p>")
    if reply_to:
        notes += ('<p style="margin:8px 0 0;color:#6b7280;font-size:13px">Erre a levélre '
                  f"válaszolva közvetlenül az érdeklődőnek írsz ({e(reply_to)}).</p>")
    bubbles = ""
    for q, a in turns or []:
        if q:
            bubbles += (
                '<div style="margin:0 0 10px;padding:10px 14px;background:#eef2ff;'
                'border-radius:12px;color:#111827">'
                '<div style="font-size:12px;color:#4f46e5;font-weight:bold;margin-bottom:4px">'
                f"Látogató</div>{md_to_html(q)}</div>")
        if a:
            bubbles += (
                '<div style="margin:0 0 16px;padding:10px 14px;background:#f3f4f6;'
                'border-radius:12px;color:#111827">'
                '<div style="font-size:12px;color:#374151;font-weight:bold;margin-bottom:4px">'
                f"{e(bot)}</div>{md_to_html(a)}</div>")
    convo = ""
    if bubbles:
        convo = ('<h3 style="margin:24px 0 12px;font-size:15px;color:#111827">'
                 f"Teljes beszélgetés</h3>{bubbles}")
    html_body = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;'
        'max-width:640px;color:#111827">'
        '<h2 style="margin:0 0 12px;font-size:18px">Új érdeklődő érkezett a chatbotból</h2>'
        f'<table style="border-collapse:collapse">{rows}</table>{notes}{convo}</div>'
    )
    return subject, text, html_body


# --- m118: elo segitsegkeres (handoff) ertesito -------------------------------------------

def _when_local(when):
    """UTC datetime -> budapesti helyi ido '2026. 10. 14. 13:04' alakban (hiba eseten UTC)."""
    try:
        from zoneinfo import ZoneInfo
        d = when.astimezone(ZoneInfo("Europe/Budapest"))
    except Exception:  # noqa: BLE001
        d = when
    try:
        return d.strftime("%Y. %m. %d. %H:%M")
    except Exception:  # noqa: BLE001
        return str(when or "")


def _bubbles_html(turns, bot):
    e = lambda v: _html.escape(str(v or ""), quote=False)  # noqa: E731
    out = ""
    for q, a in turns or []:
        if q:
            out += (
                '<div style="margin:0 0 10px;padding:10px 14px;background:#eef2ff;'
                'border-radius:12px;color:#111827">'
                '<div style="font-size:12px;color:#4f46e5;font-weight:bold;margin-bottom:4px">'
                f"Látogató</div>{md_to_html(q)}</div>")
        if a:
            out += (
                '<div style="margin:0 0 16px;padding:10px 14px;background:#f3f4f6;'
                'border-radius:12px;color:#111827">'
                '<div style="font-size:12px;color:#374151;font-weight:bold;margin-bottom:4px">'
                f"{e(bot)}</div>{md_to_html(a)}</div>")
    return out


def build_handoff_email(*, client_id, page, when, turns, bot_name, transcript=None):
    """m118: elo segitsegkeres ertesito. turns: [(kerdes, valasz), ...] idorendben (DB-naplo);
    ha ures, a `transcript` sima szoveg (widget-atirat) a tartalek. Vissza: (subject, text, html)."""
    bot = str(bot_name or "Bot")
    subject = f"Élő segítségkérés – {client_id} chatbot"
    when_s = _when_local(when)
    page = str(page or "").strip()

    t = ["Egy látogató élő segítséget / munkatársat kért a chatbotban.", "",
         f"Webshop: {client_id}", f"Oldal: {page or '–'}", f"Időpont: {when_s}"]
    if turns:
        t += ["", "— TELJES BESZÉLGETÉS —", ""]
        for q, a in turns:
            if q:
                t += [f"Látogató: {md_to_text(q)}", ""]
            if a:
                t += [f"{bot}: {md_to_text(a)}", ""]
    elif transcript:
        t += ["", "— TELJES BESZÉLGETÉS —", "", str(transcript).strip(), ""]
    t += ["", "Ha a látogató megadja az elérhetőségét, külön lead-értesítőt is küldünk."]
    text = "\n".join(t).rstrip() + "\n"

    e = lambda v: _html.escape(str(v or "–"), quote=False)  # noqa: E731
    if page.startswith(("http://", "https://")) and not any(c in page for c in ' "<>'):
        page_html = (f'<a href="{page}" style="color:#1a56db;text-decoration:underline">'
                     f"{e(page)}</a>")
    else:
        page_html = e(page)
    rows = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#6b7280;white-space:nowrap">{k}</td>'
        f'<td style="padding:4px 0;color:#111827"><strong>{v}</strong></td></tr>'
        for k, v in (("Webshop", e(client_id)), ("Oldal", page_html), ("Időpont", e(when_s)))
    )
    bubbles = _bubbles_html(turns, bot)
    if not bubbles and transcript:
        bubbles = ('<div style="margin:0 0 16px;padding:10px 14px;background:#f3f4f6;'
                   'border-radius:12px;color:#111827">'
                   + _html.escape(str(transcript).strip(), quote=False).replace("\n", "<br>")
                   + "</div>")
    convo = ""
    if bubbles:
        convo = ('<h3 style="margin:24px 0 12px;font-size:15px;color:#111827">'
                 f"Teljes beszélgetés</h3>{bubbles}")
    html_body = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;'
        'max-width:640px;color:#111827">'
        '<h2 style="margin:0 0 12px;font-size:18px">Élő segítségkérés a chatbotban</h2>'
        '<p style="margin:0 0 12px">Egy látogató élő segítséget / munkatársat kért. '
        "Érdemes mielőbb felvenni vele a kapcsolatot.</p>"
        f'<table style="border-collapse:collapse">{rows}</table>{convo}'
        '<p style="margin:16px 0 0;color:#6b7280;font-size:13px">Ha a látogató megadja az '
        "elérhetőségét, külön lead-értesítőt is küldünk.</p></div>"
    )
    return subject, text, html_body
