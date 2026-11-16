---
name: agent-runtime
description: Connect to one persistent Wuji hardware session with Python or local HTTP.
---

# Agent runtime

Use `from wujiimagine import Context; ctx = Context(session_json)` or set
`WUJIIMAGINE_SESSION`. A controller exports `main(ctx)`; Python functions, imports,
loops and feedback are allowed. `ctx.status()` gives backend, measured robot state,
sequence, fault and output paths. `ctx.skills()` lists capabilities and
`ctx.skill(name)` reads instructions. Skill loading never moves hardware.

One serve process owns the robot and serializes RPC calls. Reuse its descriptor;
do not create a second hardware owner. A network timeout is not evidence that a
motion did not happen: inspect the saved journal/current robot before recovery.
No automated motion retry. Paths refer to the workstation hosting the service.
The session token is local access information and must not be published.

This is a project workflow registry, distinct from installed Codex SKILL.md files
and from the JSON robot skill tree provided through `run_imagine.py recipe`.
