---
name: contact-planning
description: Plan observed-surface grasps or explicit short contact proposals.
---

# Contact planning

Use `ctx.plan_grasp()` for the built-in contact-guided grasp search. It returns
candidate TCP, pregrasp and hand targets plus diagnostic geometry and HTML preview.
For pushes and tool operations, construct short explicit `move_tcp` and `set_hand`
proposals in a measured functional frame, optionally preview with `ctx.imagine`.
There is no general symbolic contact-role compiler in this hardware baseline.

Keep approach, contact establishment, lift verification, transport and placement
as separately observable phases when useful. A favorable objective score is not
grip evidence. Diagnose which surface moved before increasing motion amplitude.
