# v1-wuji

An independent UR5e + Wuji Hand experiment project in the `v1-wuji` directory.
It carries forward the observation → pose → skill → feedback workflow from the
three `v1.3-*-image` projects, with a small hardware runtime and no simulator dependency.

**Status:** runnable offline pipeline and implemented hardware adapters. No physical
robot was connected or validated during development. The bundled kinematics are
for **Wuji Hand 1, right hand, 20 joints**; another hand revision needs its own model
and SDK mapping. [中文说明](README_ZH.md) · [Hardware setup](docs/HARDWARE_ZH.md).

```bash
python -m pip install -e .
python run_wuji.py demo --output outputs/demo
python run_wuji.py plan --output outputs/plan
```

Open `outputs/plan/grasp_preview.html` to rotate and inspect the point cloud and
hand candidates. Both commands above use a clearly labelled synthetic fixture;
they do not connect to a robot. The source entry point also works with just NumPy
and SciPy installed. The installed equivalent is `wuji demo`.

Real hardware is selected explicitly:

```bash
python -m pip install -e ".[robot,camera]"
# Copy configs/robot.example.json to configs/robot.local.json and calibrate it.
python run_wuji.py probe --backend real --config configs/robot.local.json
python run_wuji.py capture --backend real --config configs/robot.local.json --output captures/target
python run_wuji.py plan --frames captures/target/frame.npz --config configs/robot.local.json
python run_wuji.py run --backend real --config configs/robot.local.json --task examples/pick_lift.json
```

`probe` reads state only. `capture` and `plan` never create a motion controller.
`run --backend real` sends motion commands. Read the hardware guide before enabling
`hardware.calibrated` in your local config. This is an experimental cell controller;
its geometric proxies and host-side feedback are not a certified safety system.

The **contact-guided pose search** builds a cached surface index from RGB-D,
samples wrist orientations, and jointly refines the wrist and finger angles. It
ranks contact distance, pad normals, opposing contacts, table clearance and rough
collision costs. It runs on CPU without learned weights or proprietary kernels.
The implementation is original; research references and the MIT hand-model notice
are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Experiments write aligned RGB-D frames, observation summaries, candidates, an
interactive preview, `trace.jsonl`, and `report.json`. A visual lift is recorded as
an observed motion event. `physical_success` stays `null`; synthetic output is
never counted as real-world grasp success. Recipes use ordinary JSON, and custom
cameras use a trusted Python factory. There is no mandatory AST sandbox, asset
hash gate, simulator rollout or repeated replay. Physical retries are opt-in.

Version 1.1 adds **task → skill → subskill → primitive** recipes, local failure
diagnosis and repair verification, and reusable subskills developed from completed
nodes, including successful prefixes of a failed task.

```bash
python run_wuji.py compile --task examples/hierarchical_pick_lift.json --output outputs/compiled
python run_wuji.py demo --task examples/repair_short_lift.json --repair-attempts 1 --develop-subskills --output outputs/repair_demo
python run_wuji.py verify --report outputs/repair_demo/report.json
```

The short-lift fixture repairs only the missing local lift and rechecks the original
goal; it does not repeat the grasp. Real ambiguous grips only get a fresh observation
under the built-in strategy. Default runs make one attempt and save repair proposals.
Completed symbolic subskills are saved in `library/skills`, with parameters and
backend-scoped evidence. New tasks can call them; this does not train model weights.
See [the skill and repair guide](docs/SKILLS_REPAIR_ZH.md) for development, reuse,
custom repair providers and per-attempt artifacts. Runtime output now lives under
`outputs/<run>/attempt_01/`, with a summary and skill tree in the run directory.

```bash
python -m unittest discover -s tests -v
```

This runs a small offline suite. Hardware commissioning is a separate workstation
activity. New project code is MIT licensed; the bundled Wuji kinematic data retain
their original MIT notice. Runtime outputs and local configurations are ignored
by Git. Upload this folder as its own repository; the parent projects are not needed.
