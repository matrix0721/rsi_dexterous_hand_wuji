"""Focused integration checks for hierarchy, repair and reusable development."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wuji.camera import SyntheticCamera
from wuji.config import load_config
from wuji.hand import HandModel
from wuji.repair import propose_repair, run_experiment, validate_proposal
from wuji.robot import MockRobot
from wuji.skills import SkillStore
from wuji.verification import audit_report


class SkillRepairTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.config["planning"].update(seeds=2, iterations=25, top_k=2)
        self.hand = HandModel()

    def recipe(self, height=0.06):
        return {"name": "hierarchy", "steps": [
            {"op": "call", "skill": "task.pick_lift", "args": {"height_m": height}}]}

    def test_hierarchy_parameters_and_cycle_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SkillStore(tmp)
            compiled = store.compile(self.recipe(0.04))
            self.assertEqual({n["level"] for n in compiled["nodes"]}, {"task", "skill", "subskill"})
            self.assertEqual([s["height_m"] for s in compiled["steps"] if s["op"] == "lift"], [0.04])
            self.assertTrue(any(len(s["_path"]) == 3 for s in compiled["steps"]))
            path = Path(tmp) / "cycle.json"
            path.write_text(json.dumps({"id": "cycle", "steps": [{"op": "call", "skill": "cycle"}]}))
            with self.assertRaisesRegex(ValueError, "cyclic"):
                store.compile({"steps": [{"op": "call", "skill": "cycle"}]})

    def test_local_repair_harvest_and_reuse_without_regrasp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SkillStore(root / "skills")
            robot = MockRobot(self.config, self.hand)
            robot.move_tcp = Mock(wraps=robot.move_tcp)
            robot.set_hand = Mock(wraps=robot.set_hand)
            result = run_experiment(robot, SyntheticCamera(robot), self.hand, self.config,
                                    self.recipe(0.01), root / "run", store, repair_attempts=1, develop=True)
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["repair_verified"])
            self.assertEqual(len(result["attempts"]), 2)
            # Pregrasp, contact, short lift, corrective lift. No second grasp/approach.
            self.assertEqual(robot.move_tcp.call_count, 4)
            self.assertEqual(robot.set_hand.call_count, 2)
            self.assertEqual(len(result["development"]), 4)
            self.assertEqual(audit_report(root / "run/report.json")["status"], "verified")
            entries = {s["origin"]["skill"]: s for p in (root / "skills").glob("*.json")
                       for s in [json.loads(p.read_text())]}
            self.assertEqual(len([s for s in entries["pick.raise"]["steps"] if s["op"] == "lift"]), 1)
            self.assertGreater(entries["pick.raise"]["parameters"]["height_m"], 0.025)
            self.assertEqual(entries["pick.raise"]["state"], ["verified_mock"])
            # Newly developed files are actually callable, including repaired default parameters.
            reuse_recipe = {"name": "reuse", "steps": [
                {"op": "call", "skill": entries["grasp.prepare"]["id"]},
                {"op": "call", "skill": entries["grasp.approach"]["id"]},
                {"op": "call", "skill": entries["grasp.close"]["id"]},
                {"op": "call", "skill": entries["pick.raise"]["id"]},
                {"op": "place", "pose": [0.4, 0.2, 0.25, 3.141592653589793, 0, 0]}]}
            second = MockRobot(self.config, self.hand)
            reused = run_experiment(second, SyntheticCamera(second), self.hand, self.config,
                                    reuse_recipe, root / "reuse", store)
            self.assertEqual(reused["status"], "completed")
            self.assertIsNone(reused["physical_success"])

    def test_stale_observation_repair_retries_only_observation(self):
        robot = MockRobot(self.config, self.hand)
        robot.move_tcp = Mock(wraps=robot.move_tcp)

        class OneStaleFrame(SyntheticCamera):
            def __init__(self, robot):
                super().__init__(robot)
                self.count = 0
                self.first_timestamp = None

            def capture(self):
                frame = super().capture()
                self.count += 1
                if self.count == 1:
                    self.first_timestamp = frame.timestamp
                elif self.count == 2:
                    frame.timestamp = self.first_timestamp
                return frame

        with tempfile.TemporaryDirectory() as tmp:
            result = run_experiment(robot, OneStaleFrame(robot), self.hand, self.config,
                                    self.recipe(), tmp, SkillStore(Path(tmp) / "skills"), repair_attempts=1)
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["repair_verified"])
            self.assertEqual(robot.move_tcp.call_count, 3)
            self.assertEqual(len(result["attempts"]), 2)

    def test_repair_cannot_weaken_goal_or_retry_ambiguous_real_grip_with_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SkillStore(tmp)
            compiled = store.compile(self.recipe())
            index = next(i for i, s in enumerate(compiled["steps"]) if s["op"] == "verify_lift")
            failed = {"backend": "real", "status": "failed", "completed_steps": index,
                      "verification": {"object_delta_m": [0, 0, 0.01]},
                      "failure": {"code": "lift_not_observed", "index": index,
                                  "step": compiled["steps"][index]}}
            proposal = propose_repair(compiled, failed, self.config)
            self.assertEqual(proposal["mode"], "fresh_observation")
            self.assertEqual(proposal["recipe"], compiled)
            weakened = copy.deepcopy(proposal)
            weakened["recipe"]["goal_checks"] = []
            with self.assertRaisesRegex(ValueError, "goal"):
                validate_proposal(weakened, compiled, failed, self.config, store)
            changed_limits = copy.deepcopy(proposal)
            changed_limits["config_patch"] = {"verification": {"min_observed_lift_m": 0}}
            with self.assertRaisesRegex(ValueError, "verification"):
                validate_proposal(changed_limits, compiled, failed, self.config, store)


if __name__ == "__main__":
    unittest.main()
