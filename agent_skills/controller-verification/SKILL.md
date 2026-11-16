---
name: controller-verification
description: Freeze explicit controller code and assess measurements without mandatory hardware replay.
---

# Controller verification

`ctx.freeze('/absolute/controller.py', dependencies=[...])` saves controller code,
declared sibling files, workflow skills and hashes with source session/model/config
identity. Include every local controller dependency. It is a snapshot, not proof of
success or a sandbox for untrusted code. Inspect the bundle before reuse.

Execute a controller with `run --controller file.py`; use `--session session.json`
to reuse a live owner, or explicitly select a new backend/config. Hardware is never
automatically rehearsed or randomized. Any independent physical validation is a
separate workstation experiment within the user's authorization. Do not add
mandatory repeated tests, success certificates or simulation gates.

Distinguish command completion, measured node checks, visual lift and independently
observed task success. Reports keep `physical_success=null` unless independently
evaluated elsewhere. Mock observations remain synthetic evidence.
