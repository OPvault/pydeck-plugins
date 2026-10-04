# Finnhub

Live market prices on your Stream Deck — equities, crypto, and commodities,
served by [Finnhub](https://finnhub.io).

## Setup

1. Create a free account at [finnhub.io](https://finnhub.io/register) and copy
   the **API key** from your dashboard.
2. In PyDeck, open **Settings → Credentials → Finnhub** and paste the key into
   **API Key**.
3. Drag **Market Price** onto a button and type a symbol.

## The button

The face shows the ticker on top and the current price below it. Turn on
**Show Change** and a third line appears with the move over the selected
period, green when up and red when down.

Pressing the button fetches a fresh quote immediately. Left alone it refreshes
every 15 seconds, served from a short-lived cache so several buttons watching
the same symbol only cost one request.

## Symbols

Type any symbol Finnhub accepts — `AAPL`, `MSFT`, `BINANCE:BTCUSDT`,
`OANDA:XAU_USD`. These shorthands are resolved for you:

| You type | Resolves to | Shows as |
|:---|:---|:---|
| `BTC`, `bitcoin` | `BINANCE:BTCUSDT` | BTC |
| `ETH`, `ethereum` | `BINANCE:ETHUSDT` | ETH |
| `oil`, `brent`, `crude` | `OANDA:BCO_USD` | BRENT |
| `wti` | `OANDA:WTICO_USD` | WTI |
| `gold`, `xau` | `OANDA:XAU_USD` | GOLD |

Equities are read from Finnhub's quote endpoint. Crypto and forex-style
symbols use the candle series instead, because the quote endpoint is not
reliable for those feeds.

## Options

| Option | What it does |
|:---|:---|
| **Symbol** | The instrument to watch. Defaults to `AAPL`. |
| **Decimal Places** | 0–8 digits after the point. Raise it for low-priced assets. |
| **Show Change** | Adds the change line under the price. |
| **Change Period** | 1 hour, 1 day, or 1 week. Day change for equities comes straight from the quote; everything else is derived from candles. |
| **Show Currency Code** | Appends the currency, e.g. `212.45 USD`. |

## When something goes wrong

A button that has never had a price shows a short reason instead:

| Face | Meaning |
|:---|:---|
| `No API key` | Nothing saved under Settings → Credentials. |
| `Bad API key` | Finnhub rejected the key (HTTP 401/403). |
| `Rate limit` | Too many requests — the free tier allows 60 per minute. |
| `No data` | The symbol returned nothing. Check spelling and the exchange prefix. |
| `Offline` | The request could not reach Finnhub. |
| `Bad data`, `API error` | Finnhub answered with something unusable. |

Once a price has been drawn, a failed refresh leaves the last known value on
the button rather than blanking it, so a brief network drop is not disruptive.
The full error is written to the PyDeck console.

!!! note "Candle endpoints and the free tier"
    The change line and all crypto/commodity prices come from Finnhub's candle
    endpoints, which are restricted on some plans. If those return `No data`
    while equity quotes work, your key likely lacks candle access.
