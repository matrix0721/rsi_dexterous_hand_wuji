"""Observed-world prediction followed by a short, explicit target sequence."""


def main(ctx):
    ctx.skill("imagination")
    ctx.world()
    actions = [{"op": "lift", "height_m": .005}]
    prediction = ctx.imagine(actions, hypothesis={"relation": "stationary"})
    execution = ctx.execute(actions, prediction=prediction["id"])
    if execution["status"] != "completed":
        return execution
    comparison = ctx.compare(prediction["id"])
    return {"status": "completed", "execution": execution["id"], "comparison": comparison,
            "physical_success": None}
