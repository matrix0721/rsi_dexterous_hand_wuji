"""Mock execution and UR RTDE + WujihandPy adapters. No connection at import."""
import time
import numpy as np
from scipy.spatial.transform import Rotation

from .geometry import vector


class MockRobot:
    is_real = False

    def __init__(self, config, hand):
        self.config, self.hand = config, hand
        self.pose = np.array([0.4, 0, 0.3, np.pi, 0, 0])
        self.q = hand.open_q.copy()
        self.object_lift = 0.0
        self.grasping = False

    def state(self):
        return {"tcp_pose": self.pose.tolist(), "hand_q": self.q.tolist(),
                "tcp_force": [0.] * 6, "source": "mock"}

    def move_tcp(self, pose):
        pose = checked_pose(pose, self.config)
        if self.grasping:
            self.object_lift += pose[2] - self.pose[2]
        self.pose = pose

    def set_hand(self, q):
        self.q = self.hand.check(q).copy()
        if np.linalg.norm(self.q - self.hand.open_q) < 0.1:
            self.grasping = False
        return {"stopped_on_effort": False, "reached": True, "source": "mock"}

    def stop(self):
        pass

    def close(self):
        pass


def checked_pose(pose, config):
    pose = vector(pose, 6, "TCP target")
    lo, hi = np.asarray(config["motion"]["workspace_m"])
    if not ((pose[:3] >= lo) & (pose[:3] <= hi)).all():
        raise ValueError("TCP target outside configured workspace; edit workspace for your cell")
    return pose


def read_hardware(config):
    """Read receive channels only: does not construct an RTDE control interface."""
    import rtde_receive
    import wujihandpy
    h = config["hardware"]
    if not h["robot_ip"] or not h["hand_serial"]:
        raise ValueError("set robot_ip and hand_serial in a local config")
    receiver = rtde_receive.RTDEReceiveInterface(h["robot_ip"])
    try:
        hand = wujihandpy.Hand(serial_number=h["hand_serial"])
        return {"tcp_pose": receiver.getActualTCPPose(),
                "arm_q": receiver.getActualQ(), "tcp_force": receiver.getActualTCPForce(),
                "safety_status_bits": receiver.getSafetyStatusBits(),
                "hand_q": np.asarray(hand.read_joint_actual_position()).tolist(),
                "hand_errors": np.asarray(hand.read_joint_error_code()).tolist(),
                "handedness": int(hand.get_handedness()), "source": "hardware_read_only"}
    finally:
        receiver.disconnect()


class RealRobot:
    is_real = True

    def __init__(self, config, hand):
        h, motion = config["hardware"], config["motion"]
        if not h["calibrated"]:
            raise ValueError("complete docs/HARDWARE_ZH.md and set hardware.calibrated=true in your local config")
        if not h["robot_ip"] or not h["hand_serial"]:
            raise ValueError("robot_ip and hand_serial are required for real execution")
        if not (0 < motion["speed_m_s"] and 0 < motion["acceleration_m_s2"]
                and 0 < motion["hand_speed_rad_s"] and 0 < motion["timeout_s"]
                and 0 < motion["hand_timeout_s"] and 0 < motion["force_stop_n"]
                and 0 < motion["effort_stop_ratio"] <= 1):
            raise ValueError("motion speeds/timeouts/force must be positive; effort ratio must be in (0,1]")
        import rtde_control
        import rtde_receive
        import wujihandpy
        self.config, self.hand_model = config, hand
        self.sdk = wujihandpy
        self.c = self.r = self.device = self.controller = None
        self.context = None
        self.enabled = False
        self.closed = False
        try:
            self.r = rtde_receive.RTDEReceiveInterface(h["robot_ip"])
            self.device = wujihandpy.Hand(serial_number=h["hand_serial"])
            if int(self.device.get_handedness()) != 0:
                raise ValueError("bundled model is right Hand 1; supply a matching model/driver for another hand")
            self.lower = np.maximum(hand.lower, np.asarray(self.device.read_joint_lower_limit()).reshape(20))
            self.upper = np.minimum(hand.upper, np.asarray(self.device.read_joint_upper_limit()).reshape(20))
            self.effort_limit = np.asarray(self.device.read_joint_effort_limit()).reshape(20)
            if (not np.isfinite(self.effort_limit).all() or np.any(self.effort_limit <= 0)
                    or np.any(self.lower >= self.upper)):
                raise ValueError("invalid hardware effort or joint limits")
            self._health()
            self.c = rtde_control.RTDEControlInterface(h["robot_ip"])
            if not self.c.setTcp(vector(h["tcp_flange_pose"], 6).tolist()):
                raise RuntimeError("controller rejected palm TCP")
            if not self.c.setPayload(float(h["payload_kg"]), vector(h["payload_cog_m"], 3).tolist()):
                raise RuntimeError("controller rejected hand payload")
        except BaseException:
            self.close()
            raise

    def _health(self):
        if not self.r.isConnected():
            raise RuntimeError("UR receive connection lost")
        # Bits 2..10 include protective stop, recovery, safeguard, emergency and faults.
        if self.r.getSafetyStatusBits() & 0x7FC:
            raise RuntimeError("UR reports a stop/fault; resolve it on the pendant")
        errors = np.asarray(self.device.read_joint_error_code())
        if np.any(errors):
            raise RuntimeError(f"Wuji joint errors: {errors.tolist()}")

    def state(self):
        q = (self.device.read_joint_actual_position() if self.controller is None else
             self.controller.get_joint_actual_position())
        return {"tcp_pose": self.r.getActualTCPPose(), "arm_q": self.r.getActualQ(),
                "tcp_force": self.r.getActualTCPForce(),
                "hand_q": np.asarray(q).reshape(20).tolist(), "source": "hardware"}

    def _monitor_arm(self):
        self._health()
        force = np.asarray(self.r.getActualTCPForce())[:3]
        if not np.isfinite(force).all() or np.linalg.norm(force) > self.config["motion"]["force_stop_n"]:
            raise RuntimeError("TCP force threshold exceeded")

    def move_tcp(self, pose):
        pose = checked_pose(pose, self.config)
        m = self.config["motion"]
        try:
            self._monitor_arm()
            if not self.c.isPoseWithinSafetyLimits(pose.tolist()):
                raise ValueError("UR controller rejected target pose")
            if not self.c.getInverseKinematicsHasSolution(pose.tolist(), self.r.getActualQ()):
                raise ValueError("no UR inverse kinematic solution for target")
            if not self.c.moveL(pose.tolist(), m["speed_m_s"], m["acceleration_m_s2"], True):
                raise RuntimeError("UR moveL rejected")
            started = time.monotonic()
            while True:
                self._monitor_arm()
                if self.c.getAsyncOperationProgress() < 0:
                    break
                if time.monotonic() - started > m["timeout_s"]:
                    raise TimeoutError("UR motion timed out")
                time.sleep(0.02)
            actual = np.asarray(self.r.getActualTCPPose())
            angular_error = (Rotation.from_rotvec(actual[3:]).inv() *
                             Rotation.from_rotvec(pose[3:])).magnitude()
            if np.linalg.norm(actual[:3] - pose[:3]) > 0.01 or angular_error > 0.08:
                raise RuntimeError("UR move ended before reaching the requested TCP pose")
        except BaseException:
            self.stop()
            raise

    def set_hand(self, q):
        q = self.hand_model.check(q)
        if np.any(q < self.lower) or np.any(q > self.upper):
            raise ValueError("hand target exceeds device joint limits")
        m = self.config["motion"]
        try:
            self._monitor_arm()
            if self.controller is None:
                initial = np.asarray(self.device.read_joint_actual_position()).reshape(5, 4)
                # Seed the setpoint before enabling; entering the controller alone does not command a grasp.
                self.device.write_joint_target_position(initial)
                self.context = self.device.realtime_controller(
                    enable_upstream=True, filter=self.sdk.filter.LowPass(cutoff_freq=5.0))
                self.controller = self.context.__enter__()
                self.controller.set_joint_target_position(initial)
                self.device.write_joint_enabled(True)
                self.enabled = True
            started = previous = time.monotonic()
            commanded = np.asarray(self.controller.get_joint_actual_position()).reshape(20).copy()
            blocked = np.zeros(20, dtype=bool)
            while True:
                now = time.monotonic()
                self._monitor_arm()
                actual = np.asarray(self.controller.get_joint_actual_position()).reshape(20)
                effort = np.abs(np.asarray(self.controller.get_joint_actual_effort()).reshape(20))
                if not np.isfinite(actual).all() or not np.isfinite(effort).all():
                    raise RuntimeError("invalid hand feedback")
                newly_blocked = (~blocked) & (effort / self.effort_limit >= m["effort_stop_ratio"])
                commanded[newly_blocked] = actual[newly_blocked]
                blocked |= newly_blocked
                step = m["hand_speed_rad_s"] * min(now - previous, 0.05)
                commanded[~blocked] += np.clip(q[~blocked] - commanded[~blocked], -step, step)
                self.controller.set_joint_target_position(commanded.reshape(5, 4))
                done = (np.abs(actual - q) < 0.04) | blocked
                if done.all():
                    return {"stopped_on_effort": bool(blocked.any()),
                            "blocked_joints": np.flatnonzero(blocked).tolist(),
                            "reached": bool(np.all(np.abs(actual - q) < 0.04))}
                if now - started > m["hand_timeout_s"]:
                    raise TimeoutError("hand did not reach target before timeout")
                previous = now
                time.sleep(0.01)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        # Hold the hand rather than releasing a potentially supported payload.
        if self.c is not None:
            try:
                self.c.stopL(0.5)
            except Exception:
                pass
        if self.controller is not None:
            try:
                self.controller.set_joint_target_position(self.controller.get_joint_actual_position())
            except Exception:
                pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.context is not None and self.controller is not None:
            try:
                self.context.__exit__(None, None, None)
            except Exception:
                pass
        if self.c is not None:
            try:
                self.c.stopScript()
                self.c.disconnect()
            except Exception:
                pass
        if self.r is not None:
            self.r.disconnect()
