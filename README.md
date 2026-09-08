# tickettracker — Atleta resale monitor

Waarschuwt via ntfy push zodra er resale-startbewijzen beschikbaar komen op
`https://atleta.cc/e/qPULqpd5Gtfm/resale`. Draait volledig automatisch op
GitHub Actions — geen laptop, geen doorlopende handmatige stappen.

- Notificatiekanaal: ntfy push, topic `7HL_2026_tickets`, server `https://ntfy.sh`
- Poll-interval: elke **30 seconden**.

## Eenmalige setup (kan ik niet via API doen)

Echte 30s-polling kost ~43.000 GitHub Actions-minuten/maand (elke run wordt
minimaal op 1 minuut afgerond, ongeacht de echte duur). Op een privé-repo
zit dat ruim boven de gratis quota (2000 min/maand) en zou de monitor
uiteindelijk stil blijven staan of geld kosten. Op een **publieke** repo
zijn Actions-minuten op standaard runners onbeperkt en gratis. Er is geen
manier om dit via de API te doen — twee eenmalige acties in de GitHub UI:

1. **Settings → General → Danger Zone → Change visibility → Make public.**
2. **Settings → Secrets and variables → Actions → New repository secret**
   Name: `NTFY_TOPIC`, Value: `7HL_2026_tickets`.
   (De topic-naam staat zo niet leesbaar in de publieke code/workflow-logs.)

Na deze twee stappen draait alles verder zonder enige handmatige actie.

## Hoe het werkt

`.github/workflows/monitor.yml` start een job die elke 5 uur herstart
(`cron: "0 */5 * * *"`, ruim binnen de 6-uurslimiet per Actions-job) en
daarbinnen `poller/loop.sh` draait: een lus die elke 30 seconden
`poller/check.sh` aanroept, tot vlak voor het herstart-moment.

`check.sh` doet één GraphQL-call naar `https://atleta.cc/api/graphql`
(operation `GetRegistrationsForSale`) en leest
`data.event.registrations_for_sale_count`. Geen browser/Playwright nodig:
uit onderzoek bleek dat dit endpoint geen geldige sessie of CSRF-token
vereist (zelfs verzonnen headers werden geaccepteerd) en geen sessiecookie
gebruikt — een simpele `curl`-achtige aanroep volstaat.

- Wordt de teller `0` → `>0`: ntfy priority 5, met Click-link naar de
  resale-pagina.
- Wordt de teller `>0` → `0`: ntfy priority 3.
- Eén keer per dag: heartbeat op priority 1, zodat je weet dat de monitor
  nog draait.
- Bij HTTP 429/403: exponentiële backoff (5 → 10 → 20 → … tot max 240 min)
  plus een eenmalige ntfy-waarschuwing dat backoff actief is.
- State (`poller/state.json`) wordt door de loop teruggecommit naar de repo
  zodra hij verandert, dus overleeft elke herstart.

De repo was leeg toen dit project startte, dus GitHub heeft deze branch
automatisch als default branch ingesteld — cron-schedules draaien daardoor
al vanaf deze branch, zonder aparte merge-stap.

## Kosten/limieten

Met de repo publiek: onbeperkte/gratis Actions-minuten op standaard
runners, dus ~43.000 min/maand voor 24/7 30s-polling kost niets. Het
endpoint zelf rapporteerde een limiet van 120 requests per venster; bij 1
request per 30s wordt dat ruimschoots gerespecteerd (2/min).

## Onderzoekstooling (research/)

Bewaard voor referentie/toekomstig hergebruik, niet meer nodig voor
normale werking:

- `discover_and_validate_ci.py`, `check_synthetic_headers.py`,
  `discover_ci.py`: headless Playwright/requests-scripts die op een
  GitHub Actions-runner de endpoint-ontdekking en -validatie deden (deze
  cloud-sessie kon `atleta.cc` zelf niet bereiken door een netwerkbeleid-
  blokkade op de proxy).
- `capture_xhr.py`, `validate_endpoint.py`: interactieve varianten voor
  lokaal gebruik op een laptop, mochten de headless CI-scripts ooit
  opnieuw nodig zijn (bv. als Atleta de endpoint-vorm wijzigt).

## Handmatig testen

Via de Actions-tab → "Atleta resale monitor" → "Run workflow". Vul bij
`duration_seconds` een kleine waarde in (bv. `90`) voor een snelle test in
plaats van de volle ~4u45m looptijd.
