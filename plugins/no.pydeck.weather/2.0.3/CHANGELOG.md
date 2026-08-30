## 2.0.3 — 2026-08-30

### Fixed

- Every request failed on Windows with `certificate verify failed: unable to get
  local issuer certificate`, while the same URL loaded fine in a browser. Python's
  `ssl` module is OpenSSL, which can only see the roots CryptoAPI happens to have
  cached — unlike schannel it cannot trigger Windows' on-demand root download — and
  `api.met.no` chains to *HARICA TLS RSA Root CA 2021*, an anchor a fresh Windows
  install has not fetched. A certificate failure is now retried against certifi and
  against the Windows trust store rebuilt with its expired anchors filtered out; the
  context that works is remembered, so the search is paid for once per session. Any
  other network or HTTP error propagates untouched.
- A failed fetch no longer renders as a plausible reading. Parsing an empty response
  returned `0.0`, which on the weather face is indistinguishable from real winter
  weather — which is exactly how the certificate failure above went unnoticed. It now
  raises, and both faces show `--` until a poll has actually succeeded. A transient
  failure after a good poll still keeps the last good reading rather than blanking.
- Three empty rows on the forecast face read as "nothing scheduled" rather than "the
  fetch failed", so a key that has never polled successfully shows a dash in the first
  row instead.
