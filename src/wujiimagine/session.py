"""Single live hardware owner with an append-only observation/action journal."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import time
import uuid

import numpy as np
from scipy.spatial.transform import Rotation

from .camera import RealSenseCamera, ReplayCamera, SyntheticCamera
from .config import load_config
from .geometry import points_in, pose_matrix, vector
from .hand import HandModel
from .perception import perceive
from .native import MockRobot, RealRobot, checked_pose
from .execution import Session as RobotSession, write_json
from .verification import check_condition
from .preview import rollout
from .skills import catalog, ROOT as SKILLS_ROOT
from .common import PROJECT, asset_files


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class LiveSession:
    def __init__(self, output, backend="mock", config=None, frames=None, camera_factory=None,
                 references=None, hand_model=None):
        if backend not in ("mock", "real"):
            raise ValueError("backend must be mock or real")
        if backend == "real" and frames:
            raise ValueError("real motion requires live RGB-D; replay is for offline sessions")
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        if any(self.output.iterdir()):
            raise ValueError("use a new output directory to preserve previous evidence")
        self.config = load_config(config)
        self.hand = HandModel(hand_model)
        self.backend = backend
        self.robot = self.camera = None
        self.closed = False
        self.fault = None
        self.sequence = self.observation_index = self.world_version = 0
        self.frame = self.observation = self.current_world = None
        self.predictions, self.executions = {}, {}
        self.reference_root = Path(references).resolve() if references else None
        self.residual = None
        self.stage = None
        self.identity = uuid.uuid4().hex
        try:
            # LiveSession is the explicit motion owner. doctor/skills/probe/capture
            # and offline plan never construct this object for real hardware.
            self.robot = RealRobot(self.config, self.hand) if backend == "real" else MockRobot(self.config, self.hand)
            if camera_factory:
                module, name = camera_factory.split(":", 1)
                self.camera = getattr(importlib.import_module(module), name)(self.config)
            elif frames:
                self.camera = ReplayCamera(frames)
            else:
                self.camera = RealSenseCamera(self.config["camera"]) if backend == "real" else SyntheticCamera(self.robot)
            self.runtime = RobotSession(self.robot, self.camera, self.hand, self.config, self.output / "robot")
            write_json(self.output / "session_config.json", {
                "backend": backend, "session_id": self.identity,
                "camera": {k: v for k, v in self.config["camera"].items() if k != "serial"},
                "motion": self.config["motion"], "planning": self.config["planning"],
                "model_sha256": digest(self.hand.data), "config_sha256": digest(self.config)})
            self.report()
        except BaseException:
            self.close()
            raise

    def event(self, event, **data):
        with (self.output / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": time.time(), "event": event, **data},
                               ensure_ascii=False, allow_nan=False) + "\n")

    def report(self):
        result = {"session_id": self.identity, "backend": self.backend,
                  "status": "closed" if self.closed else ("faulted" if self.fault else "active"),
                  "sequence": self.sequence, "observations": self.observation_index,
                  "predictions": len(self.predictions), "executions": len(self.executions),
                  "fault": self.fault, "physical_success": None,
                  "verification": getattr(getattr(self, "runtime", None), "verification", None)}
        write_json(self.output / "report.json", result)
        return result

    def status(self):
        return {**self.report(), "robot": self.robot.state(), "stage": self.stage,
                "world_version": self.world_version, "output": str(self.output),
                "action_format": "JSON op; TCP xyz metres + rotvec radians; hand F1..F5/J1..J4, 20 radians"}

    def skills(self, name=None):
        result = catalog(name)
        self.event("skill_read", name=name)
        return result

    def observe(self):
        self.frame = self.camera.capture()
        if self.backend == "real" and (self.frame.source == "synthetic_fixture" or "replay" in self.frame.source):
            raise ValueError("real session received a synthetic/replay frame")
        self.observation_index += 1
        key = f"o{self.observation_index:06d}"
        path = self.output / "observations" / f"{key}.npz"
        self.frame.save(path)
        result = {"id": key, "frame": str(path), "timestamp": self.frame.timestamp,
                  "sequence": self.sequence, "source": self.frame.source,
                  "robot": self.robot.state(), "depth_shape": list(self.frame.depth_m.shape),
                  "K": self.frame.K.tolist(), "T_base_camera": self.frame.T_base_camera.tolist()}
        self.observation = result
        write_json(path.with_suffix(".json"), result)
        self.event("observe", **result)
        return result

    def pixel_to_world(self, pixel):
        if self.frame is None:
            self.observe()
        u, v = map(int, pixel)
        frame = self.frame
        h, w = frame.depth_m.shape
        if not (0 <= u < w and 0 <= v < h):
            raise ValueError("pixel outside RGB-D image")
        z = frame.depth_m[v, u]
        if not np.isfinite(z) or z <= 0:
            raise ValueError("pixel has no valid depth")
        k = frame.K
        ray = (frame.rays[v, u] if frame.rays is not None else
               np.array([(u-k[0, 2])/k[0, 0], (v-k[1, 2])/k[1, 1], 1.]))
        return {"point_m": points_in(frame.T_base_camera, np.array([ray*z]))[0].tolist(),
                "observation": self.observation["id"], "timestamp": frame.timestamp}

    def world(self, roi=None, target_hint=None, fresh=True):
        if fresh or self.frame is None:
            self.observe()
        config = copy.deepcopy(self.config)
        if roi is not None:
            config["camera"]["roi_pixels"] = roi
        obj = perceive(self.frame, config, target_hint)
        self.runtime.observation = obj
        self.world_version += 1
        center = obj.T_base_object[:3, 3]
        result = {"version": self.world_version, "observation": self.observation["id"],
                  "sequence": self.sequence, "timestamp": obj.timestamp,
                  "center_m": center.tolist(), "aabb_extent_m": np.ptp(obj.points, axis=0).tolist(),
                  **obj.summary(), "roi": config["camera"]["roi_pixels"],
                  "identity_scope": "ROI/nearest-cluster association; inspect identity after occlusion",
                  "scope": "visible surface; PCA is not complete shape or mechanism evidence"}
        self.current_world = result
        self.world_object = obj
        directory = self.output / "worlds"
        directory.mkdir(exist_ok=True)
        np.savez_compressed(directory / f"w{self.world_version:06d}.npz", points=obj.points, normals=obj.normals)
        write_json(directory / f"w{self.world_version:06d}.json", result)
        self.event("world", **result)
        return result

    def world_state(self):
        return {"world": self.current_world, "current_sequence": self.sequence,
                "historical": self.current_world is not None and self.current_world["sequence"] != self.sequence}

    def plan_grasp(self, planning=None, fresh=True):
        from .grasp_planning import plan_grasps
        from .grasp_preview import save_preview
        if fresh or self.current_world is None:
            self.world()
        config = copy.deepcopy(self.config)
        config["planning"].update(planning or {})
        result = plan_grasps(self.world_object, self.hand, config)
        result["world_version"] = self.world_version
        result["observation"] = self.current_world["observation"]
        key = "g" + uuid.uuid4().hex[:12]
        write_json(self.output / "plans" / f"{key}.json", result)
        save_preview(self.output / "plans" / f"{key}.html", self.world_object, result, self.hand)
        self.event("plan_grasp", plan=key, candidates=len(result["candidates"]))
        return {"id": key, **result, "preview": str(self.output / "plans" / f"{key}.html")}

    def validate_actions(self, actions):
        if not isinstance(actions, list) or not actions:
            raise ValueError("actions must be a nonempty list of JSON operations")
        actions = copy.deepcopy(actions)
        pose = list(self.robot.state()["tcp_pose"])
        for a in actions:
            op = a.get("op")
            if op == "move_tcp":
                pose = checked_pose(a["pose"], self.config).tolist()
                a["pose"] = pose.copy()
            elif op == "lift":
                a["height_m"] = float(a.get("height_m", self.config["verification"]["lift_m"]))
                pose[2] += a["height_m"]
                checked_pose(pose, self.config)
            elif op == "set_hand":
                a["q"] = self.hand.check(a["q"]).tolist()
            elif op == "wait":
                a["seconds"] = float(a["seconds"])
                if not np.isfinite(a["seconds"]) or a["seconds"] < 0:
                    raise ValueError("wait seconds must be finite and nonnegative")
            elif op in ("observe", "plan_grasp", "open_hand", "move_pregrasp", "move_grasp",
                        "close_grasp", "grasp", "verify_lift"):
                pass
            else:
                raise ValueError(f"unsupported action: {op}")
        return actions

    def imagine(self, actions, hypothesis=None, engine="kinematic", particles=4, apply_residual=False):
        actions = self.validate_actions(actions)
        if any(a["op"] not in ("move_tcp", "lift", "set_hand", "wait") for a in actions):
            raise ValueError("preview explicit move_tcp/lift/set_hand/wait targets; plan symbolic grasps first")
        if self.current_world is None:
            self.world()
        elif self.current_world["sequence"] != self.sequence:
            raise ValueError("preview needs a world observed after the latest motion; call world()")
        key = "p" + uuid.uuid4().hex[:12]
        state = self.robot.state()
        result = rollout(actions, state, self.current_world, self.config, self.hand,
                         hypothesis or {}, engine, particles)
        if apply_residual:
            model = self.residual
            if (model is None or model["action_sha256"] != digest(actions)
                    or model["engine"] != engine or model["hypothesis"] != (hypothesis or {})):
                raise ValueError("local residual needs the same action program, engine and hypothesis")
            result["uncorrected_center_m"] = result["object_center_m"]
            result["object_center_m"] = (np.asarray(result["object_center_m"])+model["residual_m"]).tolist()
            result["residual_model"] = copy.deepcopy(model)
        result.update(id=key, sequence=self.sequence, session_id=self.identity,
                      world_version=self.world_version, before_world=copy.deepcopy(self.current_world),
                      actions=actions, action_sha256=digest(actions), start_robot=state,
                      created_at=time.time(), consumed=False)
        self.predictions[key] = result
        write_json(self.output / "predictions" / f"{key}.json", result)
        self.event("imagine", prediction=key, engine=engine)
        return copy.deepcopy(result)

    def execute(self, actions, prediction=None, observe=True):
        if self.closed or self.fault:
            raise RuntimeError("session is closed/faulted; inspect the report and recover the workstation before a new session")
        actions = self.validate_actions(actions)
        p = None
        if prediction:
            p = self.predictions[prediction]
            if p["consumed"] or p["sequence"] != self.sequence or digest(actions) != p["action_sha256"]:
                raise ValueError("prediction is consumed, from a different start, or for different actions")
            actual = self.robot.state()
            start = p["start_robot"]
            pos_error = np.linalg.norm(np.array(actual["tcp_pose"][:3])-start["tcp_pose"][:3])
            rot_error = (Rotation.from_rotvec(actual["tcp_pose"][3:]).inv() * Rotation.from_rotvec(start["tcp_pose"][3:])).magnitude()
            if pos_error > .01 or rot_error > .08 or np.max(np.abs(np.array(actual["hand_q"])-start["hand_q"])) > .08:
                raise ValueError("robot moved since prediction; obtain a fresh prediction or execute with measured feedback")
            p["consumed"] = True
            write_json(self.output / "predictions" / f"{prediction}.json", p)
        key = "e" + uuid.uuid4().hex[:12]
        record = {"id": key, "prediction": prediction, "start_sequence": self.sequence,
                  "actions": actions, "completed_actions": 0, "backend": self.backend,
                  "before_robot": self.robot.state(), "steps": [], "physical_success": None}
        try:
            for index, action in enumerate(actions):
                # Invalidate every old start state even if a command partially fails.
                self.sequence += 1
                self.event("action_start", execution=key, index=index, action=action, sequence=self.sequence)
                self.runtime.execute(action)
                state = self.robot.state()
                record["completed_actions"] += 1
                record["steps"].append({"action": action, "robot": state, "timestamp": time.time()})
                self.event("action_end", execution=key, index=index, robot=state)
            record["status"] = "completed"
        except BaseException as exc:
            self.robot.stop()
            self.fault = f"{type(exc).__name__}: {exc}"
            record.update(status="failed", error=self.fault,
                          next_action="Inspect actual robot/camera state; no automatic motion replay.")
        record["end_sequence"] = self.sequence
        record["finished_at"] = time.time()
        try:
            record["after_robot"] = self.robot.state()
        except Exception as exc:
            record["after_robot"] = None
            record["robot_read_error"] = f"{type(exc).__name__}: {exc}"
            self.fault = record["robot_read_error"]
        if observe:
            try:
                record["observation"] = self.observe()
            except Exception as exc:
                # A camera error must not make an executed chunk look unexecuted.
                record["observation_error"] = f"{type(exc).__name__}: {exc}"
        self.executions[key] = record
        write_json(self.output / "executions" / f"{key}.json", record)
        self.event("execute", execution=key, status=record["status"], completed_actions=record["completed_actions"])
        self.report()
        return copy.deepcopy(record)

    def compare(self, prediction, fresh=True):
        p = self.predictions[prediction]
        records = [e for e in self.executions.values() if e["prediction"] == prediction]
        if not records or records[-1]["status"] != "completed":
            raise ValueError("comparison needs the completed matching execution")
        execution = records[-1]
        if execution["after_robot"] is None:
            raise ValueError("no measured post-execution robot state")
        if execution["end_sequence"] != self.sequence:
            raise ValueError("later motion prevents aligned comparison")
        if fresh:
            before = p["before_world"]
            world = self.world(roi=before.get("roi"), target_hint=p["object_center_m"])
        else:
            world = self.current_world
        if world is None or world["sequence"] != self.sequence or world["timestamp"] <= p["created_at"]:
            raise ValueError("need a fresh post-execution world")
        residual = np.asarray(world["center_m"])-p["object_center_m"]
        desired, actual = p["robot_endpoint"]["tcp_pose"], execution["after_robot"]["tcp_pose"]
        result = {"prediction": prediction, "execution": execution["id"],
                  "before_observation": p["before_world"]["observation"],
                  "after_observation": world["observation"], "residual_m": residual.tolist(),
                  "position_error_m": float(np.linalg.norm(residual)),
                  "tcp_error_m": float(np.linalg.norm(np.array(actual[:3])-desired[:3])),
                  "tcp_rotation_error_rad": float((Rotation.from_rotvec(actual[3:]).inv()*Rotation.from_rotvec(desired[3:])).magnitude()),
                  "scope": "visible cluster center under ROI/nearest association; inspect identity and occlusion"}
        write_json(self.output / "comparisons" / f"{prediction}.json", result)
        self.event("compare", **result)
        return result

    def learn_dynamics(self, prediction, identity_confirmed=False):
        if not identity_confirmed:
            raise ValueError("inspect before/after target identity, then supply identity_confirmed=True")
        result = self.compare(prediction, fresh=False)
        if result["tcp_error_m"] > .03 or result["tcp_rotation_error_rad"] > .15:
            return {"status": "skipped", "reason": "robot tracking mismatch", "comparison": result}
        p = self.predictions[prediction]
        self.residual = {"kind": "local_translation_residual", "residual_m": result["residual_m"],
                         "training_prediction": prediction, "action_sha256": p["action_sha256"],
                         "engine": p["engine"], "hypothesis": p["hypothesis"],
                         "scope": "one local transition; not identified friction/mass or independently validated dynamics"}
        write_json(self.output / "dynamics.json", self.residual)
        self.event("learn_dynamics", **self.residual)
        return copy.deepcopy(self.residual)

    def remember(self, text, evidence=None, status="observed"):
        if status not in ("observed", "hypothesized", "confirmed", "refuted"):
            raise ValueError("unknown evidence status")
        item = {"text": text, "evidence": evidence or [], "status": status, "sequence": self.sequence}
        self.event("memory", **item)
        return item

    def references(self):
        if self.reference_root is None:
            return {"experts": [], "scope": "No workstation demonstrations configured; expert study is optional."}
        manifest = self.reference_root / "index.json"
        return {"root": str(self.reference_root), **json.loads(manifest.read_text(encoding="utf-8"))}

    def operation(self, action, spec=None, evidence=None):
        if action == "begin":
            self.stage = {"spec": spec or {}, "start_sequence": self.sequence, "checks": []}
        elif action == "check":
            if self.stage is None:
                raise ValueError("no active stage")
            self.stage["checks"].append({"sequence": self.sequence, "evidence": evidence})
        elif action in ("complete", "abandon"):
            self.event("stage_end", action=action, stage=self.stage, evidence=evidence)
            self.stage = None
        elif action == "replan":
            self.event("replan", spec=spec, evidence=evidence)
        else:
            raise ValueError("operation action must be begin/check/complete/abandon/replan")
        self.event("operation", action=action, stage=self.stage)
        return {"stage": copy.deepcopy(self.stage)}

    def check(self, condition):
        result = check_condition(self.runtime, condition)
        self.event("condition", condition=condition, result=result)
        return result

    def freeze(self, controller, dependencies=None):
        """Snapshot trusted controller code and declared local dependencies; never replay hardware."""
        sources = [Path(controller).resolve()] + [Path(p).resolve() for p in dependencies or []]
        if len({p.name for p in sources}) != len(sources):
            raise ValueError("bundle files need distinct basenames")
        entries = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        runtime_root = Path(__file__).parent
        runtime_hashes = {str(p.relative_to(runtime_root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in runtime_root.rglob("*") if p.is_file()
                          and "__pycache__" not in p.parts and "_assets" not in p.parts and p.suffix != ".pyc"}
        assets = list(asset_files())
        asset_hashes = {p.relative_to(PROJECT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in assets}
        key = digest({"controller": entries, "runtime": runtime_hashes,
                      "assets": asset_hashes,
                      "config": digest(self.config), "model": digest(self.hand.data)})[:20]
        target = self.output / "controllers" / key
        target.mkdir(parents=True, exist_ok=True)
        for p in sources:
            shutil.copyfile(p, target / p.name)
        for p in assets:
            destination = target / p.relative_to(PROJECT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, destination)
        shutil.copytree(Path(__file__).parent, target / "src" / "wujiimagine",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "_assets"), dirs_exist_ok=True)
        (target / "run_frozen.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))\n"
            "from wujiimagine.cli import main\nraise SystemExit(main())\n", encoding="utf-8")
        entries = {str(p.relative_to(target)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in target.rglob("*") if p.is_file() and p.name != "manifest.json"}
        manifest = {"id": key, "controller": sources[0].name, "files": entries,
                    "backend": self.backend, "source_session": self.identity,
                    "config_sha256": digest(self.config), "model_sha256": digest(self.hand.data),
                    "physical_success": None, "scope": "controller and runtime snapshot; no automatic hardware rehearsal"}
        write_json(target / "manifest.json", manifest)
        return {**manifest, "directory": str(target)}

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.robot is not None:
                self.robot.stop()
                self.robot.close()
        finally:
            try:
                if self.camera is not None:
                    self.camera.close()
            finally:
                if hasattr(self, "runtime"):
                    self.report()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
