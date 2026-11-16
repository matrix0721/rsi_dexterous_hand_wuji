"""Focused offline integration checks; never connect hardware SDKs."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wujiimagine import Context
from wujiimagine.session import LiveSession


def expect_error(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("expected alignment error")


with tempfile.TemporaryDirectory(prefix="wuji-imagine-smoke-") as temp:
    with LiveSession(Path(temp) / "session") as live:
        ctx = Context(live)
        for item in ctx.skills()["skills"]:
            assert ctx.skill(item["name"])["text"]
        world = ctx.world()
        assert world["source"] == "synthetic_fixture"
        actions = [{"op": "lift", "height_m": .005}]
        p = ctx.imagine(actions, hypothesis={"relation": "stationary"})
        expect_error(lambda: ctx.execute([{"op": "lift", "height_m": .006}], prediction=p["id"]))
        assert live.sequence == 0
        receipt = ctx.execute(actions, prediction=p["id"])
        assert receipt["completed_actions"] == 1
        assert receipt["physical_success"] is None
        expect_error(lambda: ctx.execute(actions, prediction=p["id"]))
        comparison = ctx.compare(p["id"])
        assert comparison["tcp_error_m"] < 1e-9
        ctx.learn_dynamics(p["id"], identity_confirmed=True)
        learned = ctx.imagine(actions, hypothesis={"relation": "stationary"}, apply_residual=True)
        assert "residual_model" in learned
        ctx.execute(actions)
        expect_error(lambda: ctx.compare(p["id"]))
        bundle = ctx.freeze(Path(__file__).resolve().parents[1] / "examples/controller.py")
        assert (Path(bundle["directory"]) / "src/wujiimagine/session.py").exists()
    saved = json.loads((Path(temp) / "session/report.json").read_text(encoding="utf-8"))
    assert saved["status"] == "closed" and saved["physical_success"] is None

print("PASS: skill catalog, measured loop, prediction alignment, local residual and runtime snapshot (mock only)")
