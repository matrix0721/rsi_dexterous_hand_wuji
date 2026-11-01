"""Parameterized task -> skill -> subskill expansion and evidence-based reuse."""
import copy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re

PRIMITIVES = {"observe", "grasp", "plan_grasp", "open_hand", "move_pregrasp",
              "move_grasp", "close_grasp", "lift", "verify_lift", "move_tcp",
              "set_hand", "place", "wait", "checkpoint"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", value):
        raise ValueError(f"invalid skill id: {value!r}")
    return value


def bind(value, args):
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if key not in args:
            raise ValueError(f"missing skill parameter: {key}")
        return copy.deepcopy(args[key])
    if isinstance(value, list):
        return [bind(v, args) for v in value]
    if isinstance(value, dict):
        return {k: bind(v, args) for k, v in value.items()}
    return copy.deepcopy(value)


def skill_tree(recipe, report=None):
    results = {r["node_id"]: r for r in (report or {}).get("node_results", [])}
    failed_path = (report or {}).get("failure", {}).get("skill_path", [])
    lines = ["# Skill hierarchy", "", "Node checks describe their local scope; physical success remains unclaimed.", ""]
    for node in recipe.get("nodes", []):
        receipt = results.get(node["id"])
        state = receipt["status"] if receipt else ("failed" if node["id"] in failed_path else "planned")
        inherited = " (earlier attempt)" if receipt and receipt.get("inherited") else ""
        indent = "  " * (node["id"].count("/") - 1)
        lines.append(f"{indent}- {node['skill']} [{node['level']}; {state}{inherited}]")
    return "\n".join(lines) + "\n"


class SkillStore:
    def __init__(self, root="library/skills"):
        self.root = Path(root)
        self.bundled = json.loads(files("wuji").joinpath("resources/skills.json").read_text(encoding="utf-8"))

    def get(self, skill_id):
        identifier(skill_id)
        path = self.root / (skill_id + ".json")
        if path.exists():
            result = json.loads(path.read_text(encoding="utf-8"))
        elif skill_id in self.bundled:
            result = copy.deepcopy(self.bundled[skill_id])
        else:
            raise ValueError(f"unknown skill: {skill_id}")
        if result.get("id") != skill_id:
            raise ValueError(f"skill id does not match file: {skill_id}")
        return result

    def catalog(self):
        ids = set(self.bundled)
        if self.root.exists():
            ids.update(p.stem for p in self.root.glob("*.json"))
        return [{"id": name, "level": d.get("level", "subskill"),
                 "version": d.get("version", 1), "description": d.get("description", ""),
                 "evidence_count": len(d.get("evidence", [])),
                 "state": d.get("state", "bundled_draft"),
                 "parameters": d.get("parameters", {})}
                for name in sorted(ids) for d in [self.get(name)]]

    def compile(self, recipe):
        if recipe.get("compiled"):
            result = copy.deepcopy(recipe)
            for step in result["steps"]:
                if step.get("op") not in PRIMITIVES:
                    raise ValueError(f"unknown primitive: {step.get('op')}")
            return result
        steps, nodes = [], []
        goals = copy.deepcopy(recipe.get("checks", []))

        def expand(items, parent, path, stack):
            for i, item in enumerate(items):
                if item.get("op") != "call":
                    if item.get("op") not in PRIMITIVES - {"checkpoint"}:
                        raise ValueError(f"unknown primitive: {item.get('op')}")
                    steps.append({**copy.deepcopy(item), "_path": path[:]})
                    continue
                skill_id = item["skill"]
                if skill_id in stack:
                    raise ValueError("cyclic skill calls: " + " -> ".join([*stack, skill_id]))
                definition = self.get(skill_id)
                args = copy.deepcopy(definition.get("parameters", {}))
                supplied = item.get("args", {})
                unknown = set(supplied) - set(args)
                if unknown:
                    raise ValueError(f"{skill_id}: unknown parameters {sorted(unknown)}")
                args.update(copy.deepcopy(supplied))
                node_id = f"{parent}/{i}:{skill_id}"
                node = {"id": node_id, "parent": parent, "skill": skill_id,
                        "level": definition.get("level", "subskill"),
                        "version": definition.get("version", 1), "args": args,
                        "start": len(steps), "definition": definition}
                nodes.append(node)
                checks = bind(definition.get("checks", []), args)
                if not stack and node["level"] == "task":
                    goals.extend(copy.deepcopy(checks))
                node_path = [*path, node_id]
                expand(bind(definition["steps"], args), node_id, node_path, [*stack, skill_id])
                steps.append({"op": "checkpoint", "node_id": node_id,
                              "checks": checks, "_path": node_path})
                node["end"] = len(steps)

        expand(recipe["steps"], "root", [], [])
        # Flat recipes keep their original lift goal even without a task wrapper.
        if not goals and any(s["op"] == "verify_lift" for s in steps):
            goals = [{"type": "lift_observed", "historical": True}]
        if recipe.get("checks"):
            steps.append({"op": "checkpoint", "node_id": "root", "checks": recipe["checks"], "_path": []})
        return {"name": recipe.get("name", "custom"), "prompt": recipe.get("prompt", ""),
                "compiled": True, "source_recipe": copy.deepcopy(recipe),
                "steps": steps, "nodes": nodes, "goal_checks": goals}

    def develop(self, attempt_dir, select=None, new_id=None):
        """Extract completed subskills, including useful prefixes of a failed task.

        These are symbolic recipes, not trained weights or recovered trajectories.
        Sensor checks and backend labels stay attached to each evidence record.
        """
        attempt_dir = Path(attempt_dir)
        report = json.loads((attempt_dir / "report.json").read_text(encoding="utf-8"))
        recipe = json.loads((attempt_dir / "recipe.json").read_text(encoding="utf-8"))
        config = json.loads((attempt_dir / "config.json").read_text(encoding="utf-8"))
        results = {n["node_id"]: n for n in report.get("node_results", []) if not n.get("inherited")}
        nodes = recipe.get("nodes", [])
        selected = [n for n in nodes if n["id"] in results and
                    (select in (n["id"], n["skill"]) if select else
                     not any(c["parent"] == n["id"] for c in nodes))]
        if select and not selected:
            raise ValueError("selected skill has no completed evidence in this attempt")
        if new_id and len(selected) != 1:
            raise ValueError("--new-skill requires exactly one selected node")
        updates = []
        self.root.mkdir(parents=True, exist_ok=True)
        for node in selected:
            # Capture actual repaired primitives, then parameterize fields that still
            # match the source arguments. Nested calls are flattened to stay portable.
            body = [{k: v for k, v in s.items() if not k.startswith("_")}
                    for s in recipe["steps"][node["start"]:node["end"]]
                    if s["op"] != "checkpoint"]
            normalized = []
            for step in body:
                if (normalized and step["op"] == "lift" and normalized[-1]["op"] == "lift"
                        and set(step) <= {"op", "height_m"} and set(normalized[-1]) <= {"op", "height_m"}):
                    normalized[-1]["height_m"] = (normalized[-1].get("height_m", config["verification"]["lift_m"]) +
                                                  step.get("height_m", config["verification"]["lift_m"]))
                else:
                    normalized.append(copy.deepcopy(step))
            body = normalized
            parameters = copy.deepcopy(node["args"])
            lifts = [s for s in body if s["op"] == "lift"]
            if "height_m" in parameters and len(lifts) == 1 and "height_m" in lifts[0]:
                parameters["height_m"] = lifts[0]["height_m"]
            for step in body:
                if step["op"] == "plan_grasp":
                    step.setdefault("planning", copy.deepcopy(config["planning"]))
                for key, value in list(step.items()):
                    if key in parameters and value == parameters[key]:
                        step[key] = "$" + key
            checks = copy.deepcopy(node["definition"].get("checks", []))
            content = {"parameters": parameters, "steps": body, "checks": checks}
            skill_id = identifier(new_id or f"learned.{node['skill']}.{digest(content)[:8]}")
            target = self.root / (skill_id + ".json")
            existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
            if existing and any(existing.get(k) != v for k, v in content.items()):
                raise ValueError(f"skill {skill_id} already has different content; choose a new id")
            evidence = {"report": str((attempt_dir / 'report.json').resolve()),
                        "node_id": node["id"], "backend": report["backend"],
                        "status": results[node["id"]]["status"],
                        "checks": results[node["id"]].get("checks", []),
                        "model_sha256": report["model_sha256"],
                        "physical_success": None}
            entry = existing or {"id": skill_id, "level": "subskill", "version": 1,
                                 "description": f"Developed from {node['skill']}", **content,
                                 "requires": node["definition"].get("requires", []),
                                 "origin": {"skill": node["skill"], "version": node["version"]},
                                 "evidence": []}
            if evidence not in entry["evidence"]:
                entry["evidence"].append(evidence)
            # A later mock run cannot erase real evidence, and vice versa.
            entry["state"] = sorted({f"{e['status']}_{e['backend']}" for e in entry["evidence"]})
            target.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            updates.append({"id": skill_id, "path": str(target), "evidence": evidence})
        return updates
