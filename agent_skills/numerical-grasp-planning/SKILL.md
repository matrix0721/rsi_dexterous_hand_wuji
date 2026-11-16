---
name: numerical-grasp-planning
description: Search palm pose and twenty real Wuji joints against the visible surface.
---

# Numerical grasp planning

`ctx.plan_grasp(planning={...})` uses the bundled Hand 1 right-hand FK, normals,
opposition, table, nearby-point and sampled-skeleton costs. Default observations
are current; `fresh=False` reuses the cached visible surface when appropriate.
Read candidate `usable` and all geometry metrics in the saved plan and HTML view.
The approximation has no complete arm collision planner or friction-closure proof.

The recipe executor can run `plan_grasp`, `open_hand`, `move_pregrasp`,
`move_grasp`, `close_grasp`, `lift`, `verify_lift`. Alternatively issue a selected
candidate's explicit pregrasp/TCP/q targets through `ctx.execute`. Preserve closure
through transport, measure actual object lift and stability, and inspect current
views after failure. Numerical planning is optional for manually measured tasks;
no expert interval or solver certificate is required for ordinary execution.
