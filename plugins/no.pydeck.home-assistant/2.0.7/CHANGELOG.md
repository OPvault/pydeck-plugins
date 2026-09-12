## 2.0.7 — 2026-09-12

### Fixed

- Nothing worked at all behind Cloudflare, or behind any proxy with a default
  bot rule: the entity list spun forever, and every key failed. `HaClient` sent
  no `User-Agent`, so urllib supplied its own — `Python-urllib/3.x` — which
  Cloudflare answers with 403 before the request ever reaches Home Assistant.
  The token was never the problem, which is why the same setup worked for
  anyone whose instance is reachable directly. The client now identifies itself
  as `pydeck/2.0`, the way the icon fetch beside it always did.

### Added

- A **Room** dropdown above Domain on both faces, listing every area in Home
  Assistant. Picking one narrows the entity list to that room, and it combines
  with Domain — *Light* in *Robin Kontor* is one entity, not fourteen.
  Rooms with nothing assigned to them are listed too: a dropdown that disagrees
  with Home Assistant's own list sends you looking for a room that is not there.
- Areas are read with a rendered template (`areas()`, `area_name()`,
  `area_entities()`), because the REST API exposes no registry and `/api/states`
  carries no area at all. `area_entities` resolves both ways an entity reaches a
  room — assigned directly, or through its device. The result is cached for a
  minute, so changing the filter costs nothing; nothing in Home Assistant is
  written.
- The Room filter needs a core that understands an `api_select` with more than
  one filter. On an older one the manifest's single-filter spelling is still
  read, so the Domain filter keeps working and the Room dropdown simply does not
  narrow anything.
