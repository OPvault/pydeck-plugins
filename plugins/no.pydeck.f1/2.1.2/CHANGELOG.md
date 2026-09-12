## 2.1.2 — 2026-08-30

### Fixed

- Circuit maps and driver photos came up blank on Windows. Windows keeps an
  expired copy of ISRG Root X2 in its CA store, and `ssl.load_default_certs()`
  promotes every store entry to a trust anchor, so verifying `api.openf1.org`
  stopped at that expired anchor with `certificate has expired` instead of
  following the chain to the still-valid ISRG Root X1 — the same chain schannel
  and every Linux CA bundle walk without complaint. A request that fails
  verification is now retried against certifi and against the Windows store
  rebuilt without its expired anchors, and the context that works is cached for
  the rest of the session so the search is paid for once rather than on every
  poll. Anything that is not a certificate error still propagates untouched, so
  a genuine network failure surfaces as itself.
