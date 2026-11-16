---
name: self-correction
description: Diagnose measured free-space tracking errors and validate a local correction.
---

# Self correction

Inspect saved target and actual TCP, timing, base frame and flange-to-palm offset
before editing an approach target. In authorized free space, a controller may use
small explicit moves and fresh measurements to estimate a local offset, then
validate on a separate nearby target. Record source observations and uncertainty.
There is no automatic calibration-probe tool or learned global correction here.

Do not run free-space probes during contact, compensate tool slip by moving world
geometry, or repeatedly increase a target after a device stop. The real driver
checks reachability and reports terminal tracking failures; inspect the workstation
before starting another motion session. A correction does not update calibration
or a physical-success claim automatically.
