"""m87: a DEPLOYOLT kod igazolasa az eles konteneRBEN (csak olvas, nem hiv LLM-et).

  docker exec -i chatbot-api-prod python - < tools/m87_verify.py
"""
from app.services.langguard import foreign_tokens, strip_foreign

CASES = [
    ("valodi eles hiba (ukran)",
     "Fontos: ez a \u043d\u0430\u0439\u043a\u0440\u0430\u0449\u0435 \u00e1r a most el\u00e9rhet\u0151 adataim alapj\u00e1n, de nem biztos,"),
    ("valodi eles hiba (orosz)",
     "A \u043d\u0430\u0439\u0434\u0435\u043d\u043e adataim alapj\u00e1n a legolcs\u00f3bb rakt\u00e1ron l\u00e9v\u0151 MSI notebook..."),
    ("hibrid token",
     "Ez a \u043d\u0430\u0439mostani \u00e1r a legjobb."),
    ("LEGITIM: egy cirill karakter a termeknevben",
     "MAGUS MES10 10\u0445/22 mm szemlencse sk\u00e1l\u00e1val"),
    ("LEGITIM: tiszta magyar valasz",
     "A legolcs\u00f3bb g\u00e9p az Asus Vivobook Go 14 \u2014 109 900 Ft, Windows 11 Home. \u00d850 mm."),
]

for tag, txt in CASES:
    t = foreign_tokens(txt)
    print("%-7s %-44s | %s" % ("JELEZ" if t else "tiszta", tag,
                               (strip_foreign(txt) if t else txt)[:70]))
