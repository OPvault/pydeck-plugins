## 0.2.1 — 2026-10-04

- Now requires PyDeck 2.0.0, which has the shared settings this version follows (Settings → Plugin settings → Shared by all plugins).
- cava now analyzes at the shared animation frame rate instead of a fixed 30 fps. The key could never show more frames than the deck draws, so the rest was CPU spent on frames nobody saw; a lower setting now saves it.
- Spelling is American English throughout.
