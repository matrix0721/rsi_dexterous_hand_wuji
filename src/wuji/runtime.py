"""Small recipe executor with fresh observations, traces and explicit outcomes."""
import hashlib
import copy
import json
from pathlib import Path
import time
import traceback
import numpy as np

from .perception import perceive
from .planner import plan_grasps
from .preview import save_preview
from .skills import SkillStore
from .verification import CheckFailed, check_condition


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class Session:
    def __init__(self, robot, camera, hand, config, output):
        self.robot, self.camera, self.hand, self.config = robot, camera, hand, config
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.observation = None
        self.capture_index = 0
        self.anchor = None
        self.selected_grasp = None
        self.grasp_observation = None
        self.verification = {"status": "not_evaluated"}
        self.node_results = []

    def log(self, event, **data):
        with (self.output / "trace.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), "event": event, **data},
                                    ensure_ascii=False, allow_nan=False) + "\n")

    def observe(self, target_hint=None):
        frame = self.camera.capture()
        self.capture_index += 1
        path = self.output / "perception" / f"{self.capture_index:03d}"
        frame.save(path.with_suffix(".npz"))
        obs = perceive(frame, self.config, target_hint)
        self.observation = obs
        write_json(path.with_suffix(".json"), obs.summary())
        self.log("observe", observation=obs.summary(), robot=self.robot.state())
        return obs

    def plan_grasp(self, candidate_index=0, planning=None):
        obs = self.observe()
        planning_config = copy.deepcopy(self.config)
        planning_config["planning"].update(planning or {})
        proposal = plan_grasps(obs, self.hand, planning_config)
        write_json(self.output / "grasp_plan.json", proposal)
        save_preview(self.output / "grasp_preview.html", obs, proposal, self.hand)
        if not 0 <= candidate_index < len(proposal["candidates"]):
            raise CheckFailed("no_usable_grasp", "candidate index outside the current proposals")
        candidate = proposal["candidates"][candidate_index]
        if self.robot.is_real and not candidate["usable"]:
            raise CheckFailed("no_usable_grasp", "no usable contact pose selected; inspect grasp_plan.json or improve the view")
        self.selected_grasp, self.grasp_observation = candidate, obs

    def open_hand(self):
        self.robot.set_hand(self.hand.open_q)
        self.anchor = None
        self.verification = {"status": "not_evaluated"}

    def planned_move(self, key):
        if self.selected_grasp is None:
            raise ValueError("plan_grasp must precede a planned grasp move")
        self.robot.move_tcp(self.selected_grasp[key])

    def close_grasp(self):
        if self.selected_grasp is None or self.grasp_observation is None:
            raise ValueError("plan_grasp must precede close_grasp")
        candidate, obs = self.selected_grasp, self.grasp_observation
        feedback = self.robot.set_hand(candidate["q"])
        if not self.robot.is_real:
            self.robot.grasping = True
        state = self.robot.state()
        self.anchor = {"object_position": obs.T_base_object[:3, 3].copy(),
                       "tcp_position": np.array(state["tcp_pose"][:3]),
                       "observation_timestamp": obs.timestamp,
                       "grasp_time": time.time(), "candidate": candidate}
        self.log("grasp", candidate=candidate, feedback=feedback, robot=state)

    def grasp(self, candidate_index=0):
        self.plan_grasp(candidate_index)
        self.open_hand()
        self.planned_move("pregrasp_pose")
        self.planned_move("tcp_pose")
        self.close_grasp()

    def inherit(self, previous):
        """Keep in-memory grasp state for a local repair; never infer it from an old file."""
        for key in ("anchor", "observation", "selected_grasp", "grasp_observation", "verification"):
            setattr(self, key, getattr(previous, key))

    def lift(self, height_m=None):
        pose = np.array(self.robot.state()["tcp_pose"])
        pose[2] += self.config["verification"]["lift_m"] if height_m is None else float(height_m)
        self.robot.move_tcp(pose)

    def verify_lift(self):
        if self.anchor is None:
            raise ValueError("verify_lift requires a grasp anchor")
        state = self.robot.state()
        delta_tcp = np.array(state["tcp_pose"][:3]) - self.anchor["tcp_position"]
        expected = self.anchor["object_position"] + delta_tcp
        obs = self.observe(target_hint=expected)
        if obs.timestamp <= self.anchor["observation_timestamp"]:
            raise CheckFailed("stale_frame", "lift verification requires a newer camera frame")
        delta_object = obs.T_base_object[:3, 3] - self.anchor["object_position"]
        drift = float(np.linalg.norm(delta_object - delta_tcp))
        ok = (delta_object[2] >= self.config["verification"]["min_observed_lift_m"]
              and drift <= self.config["verification"]["max_tcp_object_drift_m"])
        self.verification = {"status": "visual_lift_observed" if ok else "lift_not_observed",
                             "object_delta_m": delta_object.tolist(),
                             "tcp_delta_m": delta_tcp.tolist(), "tcp_object_drift_m": drift,
                             "tcp_position_m": state["tcp_pose"][:3],
                             "observation_timestamp": obs.timestamp,
                             "anchor_timestamp": self.anchor["observation_timestamp"],
                             "source": obs.source,
                             "scope": "observed object motion only; no semantic task-success claim"}
        self.log("verify_lift", **self.verification)
        if not ok:
            raise CheckFailed("lift_not_observed", "lift not observed; inspect perception before another attempt", self.verification)

    def execute(self, step):
        op = step["op"]
        if op == "observe":
            self.observe()
        elif op == "grasp":
            self.grasp(int(step.get("candidate", 0)))
        elif op == "plan_grasp":
            self.plan_grasp(int(step.get("candidate", 0)), step.get("planning"))
        elif op == "open_hand":
            self.open_hand()
        elif op == "move_pregrasp":
            self.planned_move("pregrasp_pose")
        elif op == "move_grasp":
            self.planned_move("tcp_pose")
        elif op == "close_grasp":
            self.close_grasp()
        elif op == "checkpoint":
            evidence = [check_condition(self, check) for check in step.get("checks", [])]
            receipt = {"node_id": step["node_id"],
                       "status": "verified" if evidence else "executed", "checks": evidence,
                       "timestamp": time.time()}
            self.node_results.append(receipt)
            self.log("skill_complete", **receipt)
        elif op == "lift":
            self.lift(step.get("height_m"))
        elif op == "verify_lift":
            self.verify_lift()
        elif op == "move_tcp":
            self.robot.move_tcp(step["pose"])
        elif op == "set_hand":
            self.log("hand_feedback", feedback=self.robot.set_hand(step["q"]))
        elif op == "place":
            # Explicit absolute placement pose; no implicit descent inferred from an uncertain view.
            self.robot.move_tcp(step["pose"])
            self.robot.set_hand(self.hand.open_q)
            self.anchor = None
        elif op == "wait":
            duration = float(step["seconds"])
            if not np.isfinite(duration) or duration < 0:
                raise ValueError("wait seconds must be finite and nonnegative")
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                if self.robot.is_real:
                    self.robot._monitor_arm()
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        else:
            raise ValueError(f"unknown operation {op}")

    def run(self, recipe, start_at=0, inherited_report=None):
        recipe = SkillStore().compile(recipe)
        if not 0 <= start_at <= len(recipe["steps"]):
            raise ValueError("resume index outside recipe")
        passed_prefix = {n["id"] for n in recipe.get("nodes", []) if n["end"] <= start_at}
        self.node_results = [dict(n, inherited=True) for n in (inherited_report or {}).get("node_results", [])
                             if n["node_id"] in passed_prefix]
        write_json(self.output / "recipe.json", recipe)
        write_json(self.output / "hierarchy.json", recipe.get("nodes", []))
        # Hardware addresses and serials stay in the ignored local configuration.
        public_config = {k: v for k, v in self.config.items() if k != "hardware"}
        public_config["camera"] = {k: v for k, v in self.config["camera"].items() if k != "serial"}
        public_config["hardware"] = {k: v for k, v in self.config["hardware"].items()
                                     if k not in ("robot_ip", "hand_serial")}
        write_json(self.output / "config.json", public_config)
        report = {"task": recipe.get("name", "custom"),
                  "backend": "real" if self.robot.is_real else "mock",
                  "physical_success": None, "completed_steps": start_at, "resumed_prefix_steps": start_at,
                  "model": self.hand.data["model"],
                  "calibration_sha256": hashlib.sha256(json.dumps(public_config, sort_keys=True).encode()).hexdigest(),
                  "model_sha256": hashlib.sha256(json.dumps(self.hand.data, sort_keys=True).encode()).hexdigest()}
        index, step = start_at, {"op": "goal_checks"}
        try:
            for index in range(start_at, len(recipe["steps"])):
                step = recipe["steps"][index]
                self.log("step_start", index=index, step=step)
                self.execute(step)
                report["completed_steps"] = index + 1
                self.log("step_end", index=index, robot=self.robot.state())
            index, step = len(recipe["steps"]), {"op": "goal_checks"}
            report["goal_results"] = [check_condition(self, check) for check in recipe.get("goal_checks", [])]
            report["status"] = "completed"
        except (Exception, KeyboardInterrupt) as exc:
            self.robot.stop()
            report.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                          error=f"{type(exc).__name__}: {exc}",
                          failure={"code": getattr(exc, "code", "execution_error"),
                                   "index": index, "step": step,
                                   "skill_path": step.get("_path", []),
                                   "evidence": getattr(exc, "evidence", {})},
                          next_action="Inspect the last trace and camera frame; change the pose/view or recipe before retrying.")
            (self.output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            report["node_results"] = self.node_results
            report["verification"] = self.verification
            report["finished_at"] = time.time()
            write_json(self.output / "report.json", report)
        return report
