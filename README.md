# tickettracker — Atleta resale monitor

Doel: waarschuwing (via ntfy push) zodra er resale-startbewijzen
beschikbaar komen op
`https://atleta.cc/e/qPULqpd5Gtfm/resale`.

Vastgelegde keuzes:
- Notificatiekanaal: ntfy push, topic `7HL_2026_tickets`, server `https://ntfy.sh`
- Geen desktop-acties (geen browser openen, geen geluid)
- Poller draait op je laptop, niet in een cloud-/sandbox-omgeving

## Bekende blocker (bevestigd, twee keer)

Elke sandboxed/cloud Claude-omgeving die dit is geprobeerd (inclusief deze
sessie) krijgt een `403` op de proxy-CONNECT-tunnel zodra er verbinding
wordt gemaakt met `atleta.cc` — zowel met `curl` als met headless
Playwright/Chromium. Dit is een netwerkbeleid-blokkade op omgevingsniveau,
geen gedrag van Atleta. Daarom **moeten stap 1 en 2 hieronder lokaal op je
laptop draaien**, niet in een cloud-sessie.

## Stap 1 — XHR-call vastleggen (lokaal draaien)

```bash
cd research
pip install playwright requests
playwright install chromium
python3 capture_xhr.py
```

Er opent een Chromium-venster op de resale-pagina. Klik daar handmatig op
de refresh-/beschikbaarheid-knop (eventueel een paar keer), en druk daarna
in de terminal op Enter. Het script schrijft alle XHR/fetch-calls
(volledige URL, method, headers, request body, response body) naar
`research/capture.json`.

Ken je de exacte CSS-selector van de knop al? Dan kan het ook zonder
handmatig klikken:

```bash
python3 capture_xhr.py --auto-click "text=Refresh" --clicks 2
```

## Stap 2 — reproduceerbaarheid + rate-limiting testen (lokaal draaien)

```bash
python3 validate_endpoint.py capture.json
```

Dit script:
1. Herhaalt de vastgelegde call met `requests`, zonder sessiecookie/
   authorization-header, en laat zien of de response nog geldig is.
2. Vuurt dezelfde call 5x snel achter elkaar af en rapporteert
   statuscodes, timing en eventuele `Retry-After`/429/403.

Resultaat komt ook in `research/validation_report.json`.

## Vervolg

- **Werkt de call reproduceerbaar zonder cookie, geen agressieve rate
  limiting?** Deel het resultaat (of de inhoud van `capture.json` /
  `validation_report.json`) — dan bouw ik de Python-poller (stap 3a) af:
  interval als constante (start 60s), vergelijking met vorige poll,
  ntfy-notificaties (priority 5 bij beschikbaar, priority 3 bij niet meer
  beschikbaar, dagelijkse heartbeat priority 1), exponentiële backoff +
  ntfy-waarschuwing bij 429/403, en een duidelijke User-Agent.
- **Vereist de call een sessiecookie/CSRF-token, of blokkeert hij zonder
  browsercontext?** Open de pagina in je browser, inspecteer met DevTools
  het element dat de beschikbaarheid toont, en geef me de CSS-selector +
  exacte tekst — dan zet ik dat om in een changedetection.io-configuratie
  (stap 3b) in plaats van een custom poller.

Er wordt bewust nog geen poller gebouwd totdat stap 2 is bevestigd.
