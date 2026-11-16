---
name: data-collection
description: Collect calibrated observations and sparse measured action transitions.
---

# Data collection

Every session saves `observations/*.npz`, robot targets/states, worlds, previews,
executions, comparisons and events. Call `ctx.observe()` at meaningful points and
use short blocks if intermediate image transitions are needed. Recording is sparse
at calls/chunk ends; this is not synchronized high-rate video or a dense servo log.

Keep failure and recovery evidence; annotate reason and intervention with
`ctx.remember`. State the requested quota at controller level and stop once met.
Do not turn one successful execution into a completed dataset campaign. Automated
campaign scheduling, quotas, dense recording and physical scene reset are not
provided. No new agent roles or parallel robot owners are required.
