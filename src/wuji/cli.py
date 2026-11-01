import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path

from .camera import Frame, RealSenseCamera, ReplayCamera, SyntheticCamera
from .config import load_config
from .hand import HandModel
from .perception import perceive
from .planner import plan_grasps
from .preview import save_preview
from .robot import MockRobot, RealRobot, read_hardware
from .runtime import write_json
from .skills import SkillStore, skill_tree
from .repair import run_experiment, saved_repair
from .verification import audit_report

DEFAULT_TASK = {"name": "pick_lift", "prompt": "Grasp the visible target and observe a short lift.",
                "steps": [{"op": "call", "skill": "task.pick_lift"}]}


def selected_recipe(args):
    if args.skill:
        return {"name": args.skill, "steps": [{"op": "call", "skill": args.skill,
                                               "args": json.loads(args.params)}]}
    return DEFAULT_TASK if not args.task else json.loads(Path(args.task).read_text(encoding="utf-8"))


def make_camera(args, config, robot=None):
    if args.camera_factory:
        module, name = args.camera_factory.split(":")
        return getattr(importlib.import_module(module), name)(config)
    if args.frames:
        return ReplayCamera(args.frames)
    if args.backend == "real":
        return RealSenseCamera(config["camera"])
    return SyntheticCamera(robot)


def main(argv=None):
    parser = argparse.ArgumentParser(description="v1-wuji: UR5e + Wuji RGB-D experiments")
    parser.add_argument("command", choices=["demo", "capture", "plan", "run", "probe", "export",
                                             "skills", "compile", "develop", "repair", "verify"])
    parser.add_argument("--config", help="JSON config; use configs/robot.local.json for hardware")
    parser.add_argument("--backend", choices=["mock", "real"], default="mock")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--task", help="JSON recipe (flat or hierarchical)")
    selection.add_argument("--skill", help="catalog skill id to run or expand")
    parser.add_argument("--params", default="{}", help="JSON object of skill arguments")
    parser.add_argument("--skills-dir", default="library/skills", help="local reusable subskill catalog")
    parser.add_argument("--node", help="completed skill id or hierarchy node to develop")
    parser.add_argument("--new-skill", help="new catalog id for one selected node")
    parser.add_argument("--repair-attempts", type=int, default=0, help="additional local repair attempts; default proposal only")
    parser.add_argument("--repair-provider", help="trusted module:function(context) repair proposer")
    parser.add_argument("--develop-subskills", action="store_true", help="accumulate completed leaf subskills")
    parser.add_argument("--frames", nargs="+", help="ordered NPZ frames for offline replay")
    parser.add_argument("--camera-factory", help="trusted module:function(config) camera plugin")
    parser.add_argument("--hand-model", help="custom kinematic JSON; adapt SDK mapping for other hands")
    parser.add_argument("--output", help="output directory")
    parser.add_argument("--report", help="report.json for export, develop, repair or verification")
    parser.add_argument("--library", default="library/receipts.jsonl")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    output = Path(args.output or ("outputs/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")))
    robot = camera = None
    try:
        store = SkillStore(args.skills_dir)
        if args.command == "skills":
            print(json.dumps(store.catalog(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "compile":
            compiled = store.compile(selected_recipe(args))
            write_json(output / "recipe.json", compiled)
            write_json(output / "hierarchy.json", compiled["nodes"])
            (output / "skill_tree.md").write_text(skill_tree(compiled), encoding="utf-8")
            print(f"{len(compiled['nodes'])} skill nodes -> {len(compiled['steps'])} steps; {output / 'recipe.json'}")
            return 0
        if args.command in ("develop", "repair", "verify"):
            if not args.report:
                raise ValueError(f"{args.command} requires --report path/to/report.json")
            if args.command == "verify":
                result = audit_report(args.report)
                write_json(output / "verification.json", result)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "verified" else 1
            if args.command == "repair":
                result = saved_repair(args.report, output, store)
                print(json.dumps({"mode": result["mode"], "reason": result["reason"],
                                  "proposal": str(output / 'repair_proposal.json')}, ensure_ascii=False, indent=2))
                return 0
            report_path = Path(args.report)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            paths = ([report_path.parent / a["report"] for a in report["attempts"]]
                     if report.get("attempts") else [report_path])
            updates = []
            for path in paths:
                # A requested parent may complete only in a later repaired attempt.
                r = json.loads(path.read_text(encoding="utf-8"))
                compiled = json.loads((path.parent / "recipe.json").read_text(encoding="utf-8"))
                passed = {n["node_id"] for n in r.get("node_results", []) if not n.get("inherited")}
                if args.node and not any(n["id"] in passed and args.node in (n["id"], n["skill"])
                                         for n in compiled.get("nodes", [])):
                    continue
                updates.extend(store.develop(path.parent, args.node, args.new_skill))
            if args.node and not updates:
                raise ValueError("selected node has no completed evidence")
            write_json(output / "development.json", updates)
            print(json.dumps([{"id": item["id"], "path": item["path"]} for item in updates], ensure_ascii=False, indent=2))
            return 0
        if args.command == "probe":
            result = read_hardware(config) if args.backend == "real" else {"source": "mock", "connected": False}
            write_json(output / "probe.json", result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "export":
            if not args.report:
                raise ValueError("export requires --report path/to/report.json")
            result = json.loads(Path(args.report).read_text(encoding="utf-8"))
            receipt = {"task": result["task"], "backend": result["backend"],
                       "status": result["status"], "verification": result["verification"],
                       "physical_success": result["physical_success"],
                       "model_sha256": result["model_sha256"], "report": str(Path(args.report))}
            path = Path(args.library)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            print(f"Receipt appended to {path}")
            return 0
        if args.command == "demo" and args.backend != "mock":
            raise ValueError("demo uses --backend mock; use run for hardware")
        if args.backend == "real" and args.frames and args.command == "run":
            raise ValueError("real motion needs a live camera; use plan for recorded frames")
        recipe = None
        if args.command in ("run", "demo"):
            # Expand skills and catch cycle/parameter errors before connecting a motion driver.
            recipe = store.compile(selected_recipe(args))
            if args.repair_attempts < 0:
                raise ValueError("repair-attempts must be nonnegative")
        hand = HandModel(args.hand_model)
        # Capture/plan never construct a motion driver, even with --backend real.
        if args.command in ("run", "demo"):
            robot = RealRobot(config, hand) if args.backend == "real" else MockRobot(config, hand)
        camera = make_camera(args, config, robot)
        if args.command == "capture":
            frame = camera.capture()
            frame.save(output / "frame.npz")
            print(f"Saved {frame.source} frame: {output / 'frame.npz'}")
            return 0
        if args.command == "plan":
            frame = camera.capture()
            frame.save(output / "frame.npz")
            observation = perceive(frame, config)
            result = plan_grasps(observation, hand, config)
            write_json(output / "grasp_plan.json", result)
            save_preview(output / "grasp_preview.html", observation, result, hand)
            print(f"{len(result['candidates'])} candidates; {sum(c['usable'] for c in result['candidates'])} usable; {output / 'grasp_plan.json'}")
            return 0
        result = run_experiment(robot, camera, hand, config, recipe, output, store,
                                args.repair_attempts, args.repair_provider, args.develop_subskills)
        print(json.dumps({"task": result["task"], "backend": result["backend"],
                          "status": result["status"], "attempts": len(result["attempts"]),
                          "verification": result["verification"]["status"],
                          "repair_verified": result["repair_verified"],
                          "developed_subskills": len(result["development"]),
                          "physical_success": None}, ensure_ascii=False, indent=2))
        print(f"Artifacts: {output.resolve()}")
        return 0 if result["status"] == "completed" else 1
    except (Exception, KeyboardInterrupt) as exc:
        if robot is not None:
            robot.stop()
        print(f"{type(exc).__name__}: {exc}")
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        try:
            if robot is not None:
                robot.close()
        finally:
            if camera is not None:
                camera.close()


if __name__ == "__main__":
    raise SystemExit(main())
