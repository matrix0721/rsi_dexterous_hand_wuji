"""A small offline suite: one complete experiment and critical failure paths."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import numpy as np

from wuji.camera import ReplayCamera, SyntheticCamera
from wuji.config import load_config
from wuji.hand import HandModel
from wuji.robot import MockRobot, RealRobot, read_hardware
from wuji.runtime import Session
from wuji.verification import CheckFailed


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.hand = HandModel()

    def test_offline_pipeline_and_portable_resources(self):
        self.config["planning"].update(seeds=3, iterations=30, top_k=2)
        robot = MockRobot(self.config, self.hand)
        with tempfile.TemporaryDirectory() as output:
            session = Session(robot, SyntheticCamera(robot), self.hand, self.config, output)
            report = session.run({"name": "integration", "steps": [
                {"op": "grasp"}, {"op": "lift"}, {"op": "verify_lift"}]})
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["verification"]["source"], "synthetic_fixture")
            self.assertIsNone(report["physical_success"])
            plan = json.loads((Path(output) / "grasp_plan.json").read_text())
            for candidate in plan["candidates"]:
                self.hand.check(candidate["q"])
                self.assertTrue(np.isfinite(candidate["score"]))
            self.assertTrue((Path(output) / "grasp_preview.html").is_file())
            camera = ReplayCamera([Path(output) / "perception/001.npz"])
            self.assertEqual(camera.capture().source, "synthetic_fixture")
            with self.assertRaisesRegex(RuntimeError, "exhausted"):
                camera.capture()

    def test_motion_failure_stops_and_records_partial_run(self):
        robot = MockRobot(self.config, self.hand)
        robot.move_tcp = Mock(side_effect=RuntimeError("link lost"))
        robot.stop = Mock()
        with tempfile.TemporaryDirectory() as output:
            session = Session(robot, SyntheticCamera(), self.hand, self.config, output)
            report = session.run({"name": "failure", "steps": [
                {"op": "move_tcp", "pose": [0.4, 0, 0.3, 0, 0, 0]}, {"op": "lift"}]})
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["completed_steps"], 0)
            self.assertIn("link lost", report["error"])
            robot.stop.assert_called_once()
            self.assertTrue((Path(output) / "report.json").is_file())

    def test_reused_frame_cannot_verify_lift(self):
        robot = MockRobot(self.config, self.hand)
        frame = SyntheticCamera().capture()
        with tempfile.TemporaryDirectory() as output:
            path = Path(output) / "frame.npz"
            frame.save(path)
            session = Session(robot, ReplayCamera([path]), self.hand, self.config, output)
            session.anchor = {"object_position": np.array([0.4, 0, 0.06]),
                              "tcp_position": np.array(robot.pose[:3]),
                              "observation_timestamp": frame.timestamp}
            with self.assertRaisesRegex(CheckFailed, "newer camera"):
                session.verify_lift()

    def test_camera_fit_recovers_rigid_transform(self):
        path = Path(__file__).resolve().parents[1] / "tools/fit_camera.py"
        spec = importlib.util.spec_from_file_location("fit_camera", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        a = np.array([[0, 0, 0.9], [0.1, 0, 0.9], [0, 0.1, 0.9], [0.1, 0.1, 0.85]])
        r = np.diag([1, -1, -1])
        b = a @ r.T + [0.4, 0, 1]
        result = module.fit(a, b)
        np.testing.assert_allclose(np.asarray(result["T_base_camera"])[:3, :3], r, atol=1e-10)
        self.assertLess(result["rms_m"], 1e-10)
        with self.assertRaisesRegex(ValueError, "collinear"):
            module.fit([[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 0, 0], [1, 0, 0], [2, 0, 0]])

    def test_force_limit_stops_before_sending_motion(self):
        robot = RealRobot.__new__(RealRobot)
        robot.config = self.config
        robot.r = SimpleNamespace(isConnected=lambda: True, getSafetyStatusBits=lambda: 1,
                                  getActualTCPForce=lambda: [50, 0, 0, 0, 0, 0])
        robot.device = SimpleNamespace(read_joint_error_code=lambda: np.zeros((5, 4)))
        robot.c = Mock()
        robot.controller = None
        with self.assertRaisesRegex(RuntimeError, "force threshold"):
            robot.move_tcp([0.4, 0, 0.3, 0, 0, 0])
        robot.c.stopL.assert_called_once()
        robot.c.moveL.assert_not_called()

    def test_probe_does_not_construct_control_or_enable_hand(self):
        receiver = SimpleNamespace(getActualTCPPose=lambda: [0.] * 6,
                                   getActualQ=lambda: [0.] * 6,
                                   getActualTCPForce=lambda: [0.] * 6,
                                   getSafetyStatusBits=lambda: 1, disconnect=Mock())
        # No write or enable methods exist on this read-only fake.
        device = SimpleNamespace(read_joint_actual_position=lambda: np.zeros((5, 4)),
                                  read_joint_error_code=lambda: np.zeros((5, 4), dtype=int),
                                  get_handedness=lambda: 0)
        control_module = SimpleNamespace(RTDEControlInterface=Mock())
        with patch.dict(sys.modules, {
                "rtde_receive": SimpleNamespace(RTDEReceiveInterface=lambda ip: receiver),
                "rtde_control": control_module,
                "wujihandpy": SimpleNamespace(Hand=lambda **kw: device)}):
            self.config["hardware"].update(robot_ip="test-host", hand_serial="test-hand")
            result = read_hardware(self.config)
        self.assertEqual(result["source"], "hardware_read_only")
        control_module.RTDEControlInterface.assert_not_called()
        receiver.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
