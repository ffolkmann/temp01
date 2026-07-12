# Go-live chat smoke-test

A CX chatbot **minden funkcióját** végigméri egy tenanton élesítés előtt, és
ügyfélnek átadható XLSX riportot készít (a bot tényleges válaszaival + üres
`Megfelelő?` és `Megjegyzés` oszlopokkal a visszajelzéshez).

## Futtatás

```bash
bash /docker/chatbot-prod/tools/run_smoketest.sh <client_id>
```

Példa:

```bash
bash /docker/chatbot-prod/tools/run_smoketest.sh notebookstore
```

Az eredmény a webrootra kerül, letölthető linkkel:

```
https://codexpress.cloud/chatbot/reports/chat-teszt-<client_id>-<datum>.xlsx
```

## Mit tesztel

A Műszaki dokumentáció v2 funkció-leltára alapján, tenant-tudatosan (a nem
alkalmazható szekciók kimaradnak a config szerint):

- **Alapviselkedés:** köszönés, képességek, hatókörön kívüli kérdés, idegen nyelv
- **Terméktanács (RAG):** cél+keret, első vásárlás, homályos kérés → visszakérdezés,
  kontextusos follow-up, nem létező termék (nem talál ki)
- **Ár/készlet**
- **Rendelés-státusz** — *automatikus ellenőrzés*: platformfüggő űrlap
  (webdoc = szám+irsz, egyéb = szám+e-mail)
- **Házirend/tudás:** szállítás, fizetés, elállás, garancia, panasz (KB/elallas_url szerint)
- **Anti-hallucináció (m33/m34):** sugalló kérdés, márka-általánosítás, kitalált összeg
- **Kupon**
- **Bolti kereső fallback** (ha `search_fallback` be van kapcsolva)
- **Élő átadás (m28/m30/m32)** — *automatikus ellenőrzés*: kifejezett kérés +
  „igen" a felajánlásra
- **Biztonság:** jogi tanács, versenytárs, prompt-injection

## Auto-ellenőrzés vs kézi értékelés

- **OK / NEZD MEG** — a strukturálisan ellenőrizhető eseteknél (rendelés-űrlap,
  handoff, terméklink megléte) a runner maga dönt.
- **— kézi** — a tartalmi minőséget (jó-e a válasz) az ember bírálja el. Ezért van
  a riportban a bot teljes válasza + az „Elvárt viselkedés" oszlop.

## A visszajelzési kör

1. Futtasd a tesztet → XLSX.
2. Add oda az ügyfélnek (letöltés a linkről).
3. Az ügyfél kitölti a két sárga oszlopot (`Megfelelő? I/N` + `Megjegyzés / javítandó válasz`),
   és visszaküldi.
4. A visszajelzés alapján finomítjuk: tudásbázis-doksi (`/ingest`), rendszerprompt,
   vagy kód.

## Megjegyzés

A `/chatbot/reports/` könyvtár publikus (nincs auth), a fájlnév dátum+idő bélyeges.
Ha érzékeny, töröld a fájlt a megosztás után, vagy tedd auth mögé.
