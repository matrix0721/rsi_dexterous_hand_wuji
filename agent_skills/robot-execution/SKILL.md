---
name: robot-execution
description: Execute real targets with intermediate evidence and no automatic replay.
---

# Robot execution

`ctx.execute([{'op':'move_tcp','pose':[x,y,z,rx,ry,rz]}, ...])` uses metres and
rotation-vector radians in UR base coordinates. `set_hand` takes `q`: twenty
Wuji Hand 1 right joint radians, F1..F5/J1..J4. `lift` is base Z; `wait` takes
seconds. Symbolic grasp operations are listed by `run_imagine.py recipe` and in README.
Never pass simulated 16-joint hand commands or DexJoCo's flat vectors.

Use short blocks around uncertain contacts. Every command saves start/end state;
each block attempts a fresh camera capture. Inspect `completed_actions`, status,
steps, hand feedback in robot/trace.jsonl and observation paths. Capture errors
after motion are separate from execution errors: do not replay an executed block.
Faults stop the session; recovery requires inspecting actual workstation state.
No software reset, automatic reopening, return-home or automatic motion retry.

`ctx.operation('begin', spec=...)`, `check`, `complete`, `abandon`, `replan`
record optional stages; they are not extra authorization gates. Checks are user
evidence annotations; measured recipe conditions use `ctx.check(condition)`.
Neither a stage label nor closed fingers establish a successful grip. Observe
lift/relative stability before relying on a carried object.

Select real hardware once with `serve/run --backend real --config ...` and use
the workstation's measured calibration. Keep device/joint/force/time/workspace
checks at the driver boundary. Do not remove them to imitate simulation motion.
