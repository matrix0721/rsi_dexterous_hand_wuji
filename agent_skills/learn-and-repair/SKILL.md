---
name: learn-and-repair
description: Compare aligned observations, retain a local residual and repair the next proposal.
---

# Learn and repair

`ctx.compare(prediction_id)` acquires a post-execution world and reports object
center and TCP tracking residuals. It uses the source ROI and nearest predicted
center: inspect identity and visibility yourself. Comparison refuses incomplete
executions and intervening later motion. Reusing a cached post-motion world is
possible with `fresh=False`.

Rule out camera scale, association, calibration, TCP error and tool slip before
learning. `ctx.learn_dynamics(id, identity_confirmed=True)` saves one local
translation residual after identity inspection; large TCP mismatch skips fitting.
This is a single-transition estimate, not friction/mass identification or a trained
neural dynamics model. Use a separate observation to check any revised proposal.
For the same explicit action program/engine/hypothesis, a subsequent
`ctx.imagine(..., apply_residual=True)` applies that saved session-local residual
and retains the uncorrected prediction. Check it on a new transition.

Use `ctx.remember` and `operation('replan', evidence=...)` to state a changed
hypothesis. Edit only the unresolved controller segment. The bundled JSON workflow
also provides `repair`, `verify`, `develop` through `run_imagine.py recipe`, preserving goal
checks and completed prefixes. Saved reports do not restore the live physical
scene. Default repair creates a proposal; no automatic hardware replay.
