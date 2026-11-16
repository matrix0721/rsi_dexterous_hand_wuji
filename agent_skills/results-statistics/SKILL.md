---
name: results-statistics
description: Read sparse experiment receipts without conflating execution and physical success.
---

# Results statistics

Read each session's `report.json`, `executions/*.json`, `comparisons/*.json` and
`events.jsonl`. Count predictions, actual executed chunks, completed prefixes,
failed commands, observations and comparison residuals separately. Group mock,
replay and real sources separately. A completed chunk is not task success.

Report physical-success coverage: unknown values remain unknown and are excluded
from any success-rate denominator. Include sample counts and conditions. Model
rounds, tokens, prices and costs are unknown unless supplied by the external host;
do not infer API calls from controller launches or invent zero-cost measurements.
This skill is an analysis workflow, not a live pricing or automatic evaluator API.
