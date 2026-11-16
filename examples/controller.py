"""Short free-space feedback example. Adjust the action for your workstation."""


def main(ctx):
    ctx.skill("robot-execution")
    before = ctx.observe()
    ctx.operation("begin", spec={"kind": "approach", "goal": "raise TCP by 5 mm in free space"})
    result = ctx.execute([{"op": "lift", "height_m": .005}])
    ctx.operation("check", evidence={"before": before["robot"], "after": result["after_robot"]})
    ctx.operation("complete" if result["status"] == "completed" else "abandon")
    return result
