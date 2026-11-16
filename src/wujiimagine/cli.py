import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

from .context import Context
from .skills import catalog


def output_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "recipe":
        from .recipe_cli import main as recipe_main
        return recipe_main(argv[1:])
    parser = argparse.ArgumentParser(description="Wuji Imagine v1.1: live RGB-D, previews and measured feedback")
    parser.add_argument("command", choices=["doctor", "skills", "demo", "serve", "call", "run",
                                           "probe", "capture", "plan", "compile", "develop", "repair", "verify"])
    parser.add_argument("--backend", choices=["mock", "real"], default="mock")
    parser.add_argument("--config")
    parser.add_argument("--output")
    parser.add_argument("--frames", nargs="+")
    parser.add_argument("--camera-factory")
    parser.add_argument("--hand-model")
    parser.add_argument("--references", help="local expert directory containing index.json")
    parser.add_argument("--controller", help="trusted Python controller.py exporting main(ctx)")
    parser.add_argument("--session", help="existing session.json; reuses its hardware owner")
    parser.add_argument("--tool")
    parser.add_argument("--params", default="{}")
    parser.add_argument("--params-file", help="JSON tool arguments; avoids shell quoting issues")
    parser.add_argument("--name", help="workflow skill name")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--task", help="robot JSON recipe for compile/run")
    parser.add_argument("--report")
    parser.add_argument("--skills-dir", default="library/skills")
    parser.add_argument("--engine", choices=["kinematic", "mujoco"], default="kinematic")
    args = parser.parse_args(argv)
    output = args.output or ("output/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ"))
    try:
        if args.command == "skills":
            output_json(catalog(args.name))
            return 0
        if args.command == "doctor":
            output_json({"python": sys.version.split()[0], "backend_default": "mock",
                         "dependencies": {m: importlib.util.find_spec(m) is not None for m in
                                          ("numpy", "scipy", "mujoco", "rtde_control", "rtde_receive", "wujihandpy", "pyrealsense2")},
                         "workflow_skills": len(catalog()["skills"]), "hardware_connected": False})
            return 0
        if args.command == "call":
            if not args.tool:
                raise ValueError("call requires --tool")
            params = json.loads(Path(args.params_file).read_text(encoding="utf-8") if args.params_file else args.params)
            output_json(Context(args.session).call(args.tool, **params))
            return 0
        if args.command in ("probe", "capture", "plan", "compile", "develop", "repair", "verify") or (args.command == "run" and args.task):
            if args.session:
                raise ValueError("--session reuses a live owner through call or run --controller; use recipe for offline recipe commands")
            from .recipe_cli import main as robot_main
            command = args.command
            forwarded = [command, "--backend", args.backend, "--output", output, "--skills-dir", args.skills_dir]
            for key in ("config", "camera_factory", "hand_model", "task", "report"):
                if getattr(args, key):
                    forwarded += ["--"+key.replace("_", "-"), getattr(args, key)]
            if args.frames:
                forwarded += ["--frames", *args.frames]
            return robot_main(forwarded)
        if args.command == "demo" and args.backend != "mock":
            raise ValueError("demo is offline; use serve/run --backend real for hardware")
        if args.command == "run" and not args.controller:
            raise ValueError("run requires --controller controller.py or --task recipe.json")
        if args.command == "run" and args.session:
            return run_controller(args.controller, Context(args.session))
        from .session import LiveSession
        with LiveSession(output, args.backend, args.config, args.frames, args.camera_factory,
                         args.references, args.hand_model) as session:
            if args.command == "serve":
                from .server import serve
                serve(session, args.port)
                return 0
            ctx = Context(session)
            if args.command == "run":
                return run_controller(args.controller, ctx)
            # A short vertical free-space move: exercises prediction alignment and
            # measured comparison, without claiming synthetic grasp success.
            world = ctx.world()
            actions = [{"op": "lift", "height_m": .01}]
            prediction = ctx.imagine(actions, engine=args.engine, hypothesis={"relation": "stationary"})
            execution = ctx.execute(actions, prediction=prediction["id"])
            if execution["status"] != "completed":
                output_json(execution)
                return 1
            comparison = ctx.compare(prediction["id"])
            ctx.remember("Offline preview and feedback smoke run", evidence=[prediction["id"], execution["id"]])
            output_json({"backend": "mock", "source": world["source"], "engine": args.engine,
                         "comparison": comparison, "physical_success": None, "output": str(session.output)})
            return 0
    except KeyboardInterrupt:
        print("Interrupted; live session stopped.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def run_controller(path, ctx):
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("wuji_user_controller", path)
    if spec is None or spec.loader is None:
        raise ValueError("controller must be a Python module")
    module = importlib.util.module_from_spec(spec)
    # Sibling imports are supported for user-declared controller dependencies.
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
        result = module.main(ctx)
        if result is not None:
            output_json(result)
        return 1 if isinstance(result, dict) and result.get("status") == "failed" else 0
    finally:
        sys.path.pop(0)
