# tickettracker — Atleta resale monitor

Waarschuwt via ntfy push zodra er resale-startbewijzen beschikbaar komen op
`https://atleta.cc/e/qPULqpd5Gtfm/resale`. Draait volledig automatisch op
GitHub Actions — geen laptop, geen handmatige stappen nodig.

- Notificatiekanaal: ntfy push, topic `7HL_2026_tickets`, server `https://ntfy.sh`
- Poll-interval: elke 5 minuten (`.github/workflows/monitor.yml`, cron
  `*/5 * * * *`) — de praktische ondergrens van GitHub Actions' scheduler;
  minder frequent kan niet betrouwbaar.

## Hoe het werkt

`poller/check.sh` doet één GraphQL-call naar `https://atleta.cc/api/graphql`
(operation `GetRegistrationsForSale`) en leest
`data.event.registrations_for_sale_count`. Geen browser/Playwright nodig:
uit onderzoek bleek dat dit endpoint helemaal geen geldige sessie of
CSRF-token vereist (zelfs verzonnen headers werden geaccepteerd) en geen
sessiecookie gebruikt — dus een simpele `curl`-achtige aanroep volstaat.

- Wordt de teller `0` → `>0`: ntfy priority 5, met Click-link naar de
  resale-pagina.
- Wordt de teller `>0` → `0`: ntfy priority 3.
- Eén keer per dag: heartbeat op priority 1, zodat je weet dat de monitor
  nog draait.
- Bij HTTP 429/403: exponentiële backoff (5 → 10 → 20 → … tot max 240 min)
  plus een eenmalige ntfy-waarschuwing dat backoff actief is.
- State (`poller/state.json`: laatste bekende beschikbaarheid, backoff,
  laatste heartbeat-datum) wordt door de workflow zelf teruggecommit naar
  de repo, dus overleeft elke run (GitHub Actions runners zijn stateless).

De repo was leeg toen dit project startte, dus GitHub heeft deze branch
automatisch als default branch ingesteld — de cron-schedule staat daardoor
al live, zonder aparte merge-stap.

## Kosten/limieten

Repo is privé. Elke run kost ~5-10s (geen Playwright/browser meer nodig),
dus bij 5 min interval (~288 runs/dag) blijft het ruim binnen de gratis
GitHub Actions-maandquota. Het endpoint zelf rapporteerde een limiet van
120 requests per venster — bij 1 request per 5 minuten wordt dat nooit
benaderd.

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

```
gh workflow run monitor.yml   # of via de Actions-tab / workflow_dispatch
```

Dit voert direct één poll-cyclus uit, los van de cron-schedule.
