## 2.0.0 — 2026-08-22

### Changed

- Rewritten on the PDK 2.x layout under the RDNN id `no.pydeck.finnhub` — the last plugin in the catalog to leave the classic flat-`plugin.py` generation behind.
- One **Market Price** function replaces the old per-instrument split: type a symbol and it renders whatever Finnhub returns for it, whether that is a stock, a crypto pair or a commodity.
- Polls every 15 seconds, a rate that stays inside Finnhub's free-tier budget when several price buttons are on the deck at once.

### Added

- A decimals control, so a currency pair quoted to four places and a share price quoted to two can sit next to each other and both read correctly.

## 1.1.0 — 2026-04-12

### Added

- First release: live stock prices from the Finnhub API, on the classic flat `plugin.py` layout.
