## 1.0.0 — 2026-08-30

### Added

- First release. Three games of chance, one function each: **Dice** rolls a
  single six-sided die, **Roulette** spins a wheel and lands the ball on a
  number, and **Coin Flip** turns a coin over onto heads or tails. Every
  result is drawn fresh from `random` at the moment of the press.
- The animation is driven by the press rather than by state. PDK re-renders an
  animated button off the clock at ~15 fps while handler state only moves on a
  press or a poll no faster than every half second, which is far too coarse to
  animate from — so a handler writes its own timestamp into the animation's
  delay slot, turning progress into "time since the press", and writes the
  result into the final keyframe. Each face therefore starts moving on the
  press, runs once, and freezes on the result.
- The die tumbles through five faces before settling on the one it rolled; the
  roulette ball runs against the wheel and the winning number pops up on the
  hub in red, black, or green for a zero; the coin is drawn as four discs of
  falling height lit one at a time, which is how it turns end over end without
  a third dimension to turn in.
- Roulette can be set to a European wheel (0–36) or an American one (0, 00–36),
  which is the only thing either game has to configure.
- Presses report their result to the event log through `log_format` — `rolled
  5`, `landed on 17 black` — and deliberately not as a press `message`, which
  the editor would turn into a toast on every single press.
