"""Local diagnosis -> minimal repair -> execution -> original-goal verification."""
import copy
import importlib
import json
from pathlib import Path

from .runtime import Session, write_json
from .skills import SkillStore, digest, skill_tree
from .verification import attempt_path, audit_report


def diagnose(report):
    failure = report.get("failure", {})
    code = failure.get("code", "execution_error")
    text = report.get("error", "").lower()
    if report.get("status") == "interrupted":
        code = "interrupted"
    elif code == "execution_error":
        if any(s in text for s in ("not visible", "no object cluster", "no object")):
            code = "perception_missing"
        elif any(s in text for s in ("connection", "link lost", "force threshold", "stop/fault", "joint errors")):
            code = "device_or_contact_stop"
        elif "timeout" in text or "timed out" in text:
            code = "motion_timeout"
    return {"code": code, "failed_index": failure.get("index", report.get("completed_steps", 0)),
            "failed_operation": failure.get("step", {}).get("op"),
            "skill_path": failure.get("skill_path", []), "error": report.get("error"),
            "evidence": failure.get("evidence", {}),
            "completed_nodes": [n["node_id"] for n in report.get("node_results", [])]}


def _insert_step(recipe, index, step):
    recipe["steps"].insert(index, step)
    for node in recipe.get("nodes", []):
        if node["start"] > index:
            node["start"] += 1
        if node["end"] > index:
            node["end"] += 1


def propose_repair(recipe, report, config, attempt=1):
    diagnosis = diagnose(report)
    index = diagnosis["failed_index"]
    proposal = {"diagnosis": diagnosis, "reason": "No supported local repair; inspect the failed subskill.",
                "recipe": copy.deepcopy(recipe), "config_patch": {}, "resume_from": index,
                "mode": "manual", "automatic": False}
    code, op = diagnosis["code"], diagnosis["failed_operation"]
    if code in ("stale_frame", "perception_missing") and op in ("observe", "plan_grasp", "verify_lift", "grasp"):
        proposal.update(mode="fresh_observation", automatic=True,
                        reason="Capture a new frame at the failed primitive; keep completed actions and goal thresholds.")
    elif code == "no_usable_grasp" and op in ("plan_grasp", "grasp"):
        proposal.update(mode="local_replan", automatic=True,
                        reason="Increase contact-search seeds and change the random seed before any grasp motion.")
        proposal["config_patch"] = {"planning": {"seeds": config["planning"]["seeds"] + 4,
                                                    "seed": config["planning"]["seed"] + attempt}}
        proposal["recipe"]["steps"][index]["candidate"] = 0
        if "planning" in proposal["recipe"]["steps"][index]:
            proposal["recipe"]["steps"][index]["planning"].update(proposal["config_patch"]["planning"])
    elif code == "lift_not_observed" and op == "verify_lift":
        delta = report.get("verification", {}).get("object_delta_m", [0, 0, 0])
        deficit = config["verification"]["min_observed_lift_m"] - delta[2]
        if report["backend"] == "mock" and deficit > 0:
            # A mock fixture has no dropped load. Correct only the missing local lift,
            # rather than replaying the grasp. Real ambiguity never uses this rule.
            step = {"op": "lift", "height_m": float(deficit + 0.01),
                    "_path": recipe["steps"][index].get("_path", [])}
            _insert_step(proposal["recipe"], index, step)
            proposal.update(mode="local_motion", automatic=True,
                            reason="Mock lift was shorter than the unchanged goal; add only the missing lift and reobserve.")
        else:
            proposal.update(mode="fresh_observation", automatic=True,
                            reason="Reobserve once without moving or opening the hand; ambiguous real grip needs workstation recovery.")
    proposal["changed"] = (proposal["recipe"] != recipe or bool(proposal["config_patch"]))
    return proposal


def validate_proposal(proposal, recipe, report, config, store):
    """Check a repair against the original objective, not a relaxed success flag."""
    revised = store.compile(proposal["recipe"])
    if revised.get("goal_checks", []) != recipe.get("goal_checks", []):
        raise ValueError("repair cannot remove or change original task goal checks")
    patch = proposal.get("config_patch", {})
    if set(patch) - {"planning", "perception"}:
        raise ValueError("repair config changes are limited to planning/perception; original verification and motion limits stay fixed")
    index = proposal.get("resume_from", 0)
    completed = report["completed_steps"]
    if type(index) is not int or not 0 <= index <= min(completed, len(revised["steps"])):
        raise ValueError("repair may only resume from an actually completed prefix")
    if revised["steps"][:index] != recipe["steps"][:index]:
        raise ValueError("repair changed an already executed prefix; start a separate recovered experiment")
    # A cached goal cannot turn a repair that deleted its verification action into success.
    if any(g["type"] == "lift_observed" for g in recipe.get("goal_checks", [])):
        if not any(s["op"] == "verify_lift" for s in revised["steps"]):
            raise ValueError("repair removed the lift observation primitive")
    if revised == recipe and not patch and proposal.get("mode") != "fresh_observation":
        raise ValueError("repair did not change the plan, search parameters or observation")
    if report["status"] == "interrupted" or diagnose(report)["code"] in ("device_or_contact_stop", "motion_timeout"):
        raise ValueError("device/contact stop or interruption requires workstation recovery; no automatic motion replay")
    updated = copy.deepcopy(config)
    for section, values in patch.items():
        updated[section].update(values)
    return revised, updated


def saved_repair(report_path, output, store):
    path = attempt_path(report_path)
    recipe = json.loads((path.parent / "recipe.json").read_text(encoding="utf-8"))
    report = json.loads(path.read_text(encoding="utf-8"))
    if report["status"] == "completed":
        raise ValueError("the selected experiment completed; no failure needs repair")
    config = json.loads((path.parent / "config.json").read_text(encoding="utf-8"))
    proposal = propose_repair(recipe, report, config)
    proposal["execution_note"] = "Generated offline. Resume needs the live Session state; this command sends no motion."
    write_json(Path(output) / "repair_proposal.json", proposal)
    write_json(Path(output) / "diagnosis.json", proposal["diagnosis"])
    return proposal


def run_experiment(robot, camera, hand, config, recipe, output, store=None,
                   repair_attempts=0, repair_provider=None, develop=False):
    if repair_attempts < 0:
        raise ValueError("repair-attempts must be nonnegative")
    store = store or SkillStore()
    compiled = store.compile(recipe)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "source_recipe.json", recipe)
    attempts, updates, development_errors = [], [], []
    current_config, previous_session, previous_report = copy.deepcopy(config), None, None
    pending, resume = None, 0
    for number in range(1, repair_attempts + 2):
        attempt_dir = output / f"attempt_{number:02d}"
        # Planning/perception changes do not change the driver's fixed motion limits.
        session = Session(robot, camera, hand, current_config, attempt_dir)
        if previous_session is not None:
            session.inherit(previous_session)
        result = session.run(compiled, start_at=resume, inherited_report=previous_report)
        attempt_record = {"attempt": number, "report": f"attempt_{number:02d}/report.json",
                          "status": result["status"], "resumed_from": resume}
        attempts.append(attempt_record)
        if pending is not None:
            verification = {"status": "verified" if result["status"] == "completed" else "failed",
                            "goal_contract_preserved": True, "reason": pending["reason"],
                            "scope": "mock_observation" if not robot.is_real else "real_observation",
                            "physical_success": None,
                            "audit": audit_report(attempt_dir / "report.json")}
            if verification["audit"]["status"] != "verified":
                verification["status"] = "failed"
            write_json(attempt_dir / "repair_verification.json", verification)
            attempt_record["repair_verification"] = verification
        if develop:
            try:
                updates.extend(store.develop(attempt_dir))
            except Exception as exc:
                development_errors.append({"attempt": number, "error": f"{type(exc).__name__}: {exc}"})
        if result["status"] == "completed":
            break
        proposal = propose_repair(compiled, result, current_config, number)
        if repair_provider and result["status"] != "interrupted":
            try:
                module, function = repair_provider.split(":")
                provided = getattr(importlib.import_module(module), function)({
                    "recipe": copy.deepcopy(compiled), "report": copy.deepcopy(result),
                    "diagnosis": proposal["diagnosis"], "attempt": number,
                    "config": json.loads((attempt_dir / "config.json").read_text(encoding="utf-8")),
                    "observation": session.observation.summary() if session.observation else None,
                    "robot_state": robot.state()})
                if provided is not None:
                    proposal = {**proposal, **provided}
            except Exception as exc:
                proposal.update(mode="manual", automatic=False, reason=f"Repair provider failed: {type(exc).__name__}: {exc}")
        write_json(attempt_dir / "diagnosis.json", proposal["diagnosis"])
        write_json(attempt_dir / "repair_proposal.json", proposal)
        if number > repair_attempts or not proposal.get("automatic"):
            attempt_record["repair_status"] = "proposal_only" if proposal.get("automatic") else "manual_recovery"
            break
        try:
            revised, revised_config = validate_proposal(proposal, compiled, result, current_config, store)
        except (ValueError, KeyError) as exc:
            attempt_record.update(repair_status="rejected", repair_error=str(exc))
            break
        previous_session, previous_report = session, result
        compiled, current_config, resume = revised, revised_config, proposal["resume_from"]
        pending = proposal
        attempt_record["repair_status"] = "selected"
    summary = {**result, "attempts": attempts, "development": updates,
               "development_errors": development_errors,
               "goal_contract_sha256": digest(compiled.get("goal_checks", [])),
               "repair_verified": bool(attempts[-1].get("repair_verification", {}).get("status") == "verified")}
    write_json(output / "report.json", summary)
    (output / "skill_tree.md").write_text(skill_tree(compiled, result), encoding="utf-8")
    if develop:
        write_json(output / "development.json", updates)
    return summary
