---
name: tool-state-estimation
description: Compare the same visible tool feature relative to the measured palm.
---

# Tool state estimation

Select the same semantic feature in before/after RGB-D and deproject with
`ctx.pixel_to_world`. Compute `p_palm = inv(T_base_palm) @ [p_base,1]` using each
observation's TCP measurement. Compare local positions and record feature pixels,
timestamps and residual with `ctx.remember`.

This is a controller workflow, not an automatic feature tracker. Occlusion, wrong
association and depth error can look like slip; reacquire a visible feature.
Hand command-state gaps and effort readings are not calibrated fingertip forces.
Stable local geometry is evidence for that visible feature, not proof of an
unseen jaw mechanism or complete grasp stability.
