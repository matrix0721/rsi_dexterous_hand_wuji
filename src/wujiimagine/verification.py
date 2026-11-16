"""Named postconditions and report audits. Verification scope stays explicit."""
import json
from pathlib import Path
import time
import numpy as np
from scipy.spatial.transform import Rotation


class CheckFailed(RuntimeError):
    def __init__(self, code, message, evidence=None):
        super().__init__(message)
        self.code = code
        self.evidence = evidence or {}


def check_condition(session, spec):
    kind = spec["type"]
    detail = {}
    if kind == "object_visible":
        age = None if session.observation is None else time.time() - session.observation.timestamp
        ok = age is not None
        if ok and session.robot.is_real and "max_age_s" in spec:
            ok = 0 <= age <= spec["max_age_s"]
        detail = {"age_s": age, "source": getattr(session.observation, "source", None)}
    elif kind == "grasp_planned":
        ok = session.selected_grasp is not None
        detail = {"usable": bool(ok and session.selected_grasp["usable"])}
        if session.robot.is_real:
            ok = ok and detail["usable"]
    elif kind == "grasp_anchored":
        ok = session.anchor is not None
        detail = {"scope": "command and anchor exist; no contact stability claim"}
    elif kind in ("tcp_at_grasp", "tcp_at"):
        if kind == "tcp_at_grasp" and session.selected_grasp is None:
            ok = False
        else:
            target = np.array(session.selected_grasp["tcp_pose"] if kind == "tcp_at_grasp" else spec["pose"])
            actual = np.array(session.robot.state()["tcp_pose"])
            position_error = float(np.linalg.norm(target[:3] - actual[:3]))
            rotation_error = float((Rotation.from_rotvec(actual[3:]).inv() *
                                    Rotation.from_rotvec(target[3:])).magnitude())
            ok = (position_error <= spec.get("position_tolerance_m", 0.01) and
                  rotation_error <= spec.get("rotation_tolerance_rad", 0.08))
            detail = {"position_error_m": position_error, "rotation_error_rad": rotation_error}
    elif kind == "lift_observed":
        v = session.verification
        ok = v.get("status") == "visual_lift_observed"
        if spec.get("historical"):
            # Legacy flat pick/place recipes verify the lift before releasing.
            ok = ok and v.get("observation_timestamp", 0) > v.get("anchor_timestamp", 0)
        elif session.anchor is None:
            ok = False
        elif ok:
            ok = v.get("anchor_timestamp") == session.anchor["observation_timestamp"]
            # A later move or release invalidates a cached lift condition.
            current = np.array(session.robot.state()["tcp_pose"][:3])
            ok = ok and np.linalg.norm(current - np.array(v["tcp_position_m"])) < 0.01
        detail = dict(v)
    else:
        raise ValueError(f"unknown postcondition: {kind}")
    evidence = {"type": kind, "passed": bool(ok), "detail": detail}
    if not ok:
        raise CheckFailed("postcondition_failed", f"postcondition failed: {kind}", evidence)
    return evidence


def attempt_path(report_path):
    path = Path(report_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    return path.parent / report["attempts"][-1]["report"] if report.get("attempts") else path


def audit_report(report_path):
    """Recompute persisted lift measurements and required goal receipts; no motion."""
    path = attempt_path(report_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    recipe = json.loads((path.parent / "recipe.json").read_text(encoding="utf-8"))
    config = json.loads((path.parent / "config.json").read_text(encoding="utf-8"))
    goals = recipe.get("goal_checks", [])
    issues = []
    if report["status"] != "completed":
        issues.append("execution_not_completed")
    if report.get("completed_steps") != len(recipe["steps"]):
        issues.append("incomplete_step_receipts")
    if not goals:
        issues.append("no_task_goal_declared")
    receipts = report.get("goal_results", [])
    if (len(receipts) != len(goals) or
            not all(r.get("passed") and r.get("type") == g["type"] for r, g in zip(receipts, goals))):
        issues.append("goal_receipts_missing_or_failed")
    v = report.get("verification", {})
    if any(g["type"] == "lift_observed" for g in goals):
        try:
            delta = np.asarray(v["object_delta_m"], dtype=float)
            tcp = np.asarray(v["tcp_delta_m"], dtype=float)
            anchor_t = float(v["anchor_timestamp"])
            frame_t = float(v["observation_timestamp"])
            if (delta.shape != (3,) or tcp.shape != (3,) or not np.isfinite([*delta, *tcp, anchor_t, frame_t]).all()
                    or frame_t <= anchor_t
                    or delta[2] < config["verification"]["min_observed_lift_m"]
                    or np.linalg.norm(delta - tcp) > config["verification"]["max_tcp_object_drift_m"]):
                issues.append("lift_measurements_failed")
        except (KeyError, TypeError, ValueError):
            issues.append("lift_measurements_missing")
    return {"status": "verified" if not issues else "unverified", "issues": issues,
            "scope": "mock_observation" if report["backend"] == "mock" else "real_observation",
            "physical_success": None, "report": str(path),
            "note": "Audits persisted measurements; not an independent physical replay."}
