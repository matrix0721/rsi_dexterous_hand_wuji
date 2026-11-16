"""Small editable skill catalog; reading instructions never moves a device."""
import json
from .common import PROJECT

ROOT = PROJECT / "agent_skills"


def catalog(name=None):
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    if name is None:
        return index
    item = next((s for s in index["skills"] if s["name"] == name), None)
    if item is None:
        raise ValueError(f"unknown workflow skill: {name}")
    return {**item, "text": (ROOT / item["path"]).read_text(encoding="utf-8")}
