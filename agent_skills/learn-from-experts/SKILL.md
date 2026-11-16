---
name: learn-from-experts
description: Adapt workstation demonstrations to current measured geometry.
---

# Learn from experts

`ctx.references()` reads an optional local `index.json` configured by
`--references`. No bundled successful demonstrations or fixed expert count is
assumed. A missing reference set does not block motion or require data collection.

Study approach direction, hand posture, contact frame and order of phases. Measure
their relation to the target in the recorded frames; adapt to current RGB-D and
the real hand model. Never copy DexJoCo's 22/44-dimensional actions or replay
absolute demonstration coordinates on hardware. Use twenty Wuji joint angles in
SDK order. Record useful intervals and measurement evidence with `ctx.remember`.
Demonstrations are references, not evidence that a new workstation task succeeded.
