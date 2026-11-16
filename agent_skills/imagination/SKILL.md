---
name: imagination
description: Save an independent hypothesis or MuJoCo contact preview before executing.
---

# Imagination

After `ctx.world()`, call `ctx.imagine(actions, hypothesis={...}, engine=...)`.
Preview actions are explicit `move_tcp`, `lift`, `set_hand`, `wait`. No device is
moved. The prediction stores its exact actions, starting robot measurement,
sequence, source world and engine. Use its id with
`ctx.execute(actions, prediction=p['id'])`, then `ctx.compare(p['id'])`.
Only a complete, matching execution supports comparison; changed actions, reused
predictions or intervening movement do not form aligned prediction evidence.

`kinematic` supports `relation=stationary|attached|translation`; translation takes
`object_delta_m`. Attached is an explicit rigid-motion hypothesis, not a grip claim.
`mujoco` uses a free box from visible AABB, a floor and five kinematic fingertip
spheres. `mass_kg`, `friction`, `parameter_spread`, `seed` are hypotheses; particles
show parameter disagreement. Rotation and hand targets interpolate over configured
speed. This excludes full hand/arm geometry, hidden surfaces and internal joints.
Collision forecasts cannot certify a robot path. The real robot follows RTDE,
not the simulator. Prefer short previews around a specific uncertainty.

Prediction is optional; unavailable geometry or an unsuitable proxy calls for
measured feedback, not a fabricated preview. No mandatory simulation pass precedes
real movement. Predicted motion never establishes physical success.
