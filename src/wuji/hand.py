"""Small URDF-derived kinematic tree; SDK order is F1..F5, J1..J4."""
import json
from importlib.resources import files
import numpy as np
from scipy.spatial.transform import Rotation

from .geometry import matrix, points_in, vector


class HandModel:
    def __init__(self, path=None):
        resource = files("wuji").joinpath("resources/wuji_hand1_right.json")
        self.data = json.loads(resource.read_text(encoding="utf-8") if path is None
                               else __import__("pathlib").Path(path).read_text(encoding="utf-8"))
        self.joints = self.data["joints"]
        self.active = [j for j in self.joints if j["type"] == "revolute"]
        self.names = [j["name"] for j in self.active]
        self.lower = np.array([j["lower"] for j in self.active])
        self.upper = np.array([j["upper"] for j in self.active])
        self.origins = {j["name"]: matrix(Rotation.from_euler("xyz", j["rpy"]).as_matrix(),
                                          j["xyz"]) for j in self.joints}
        self.open_q = np.clip(np.zeros(20), self.lower, self.upper)

    def check(self, q):
        q = vector(q, 20, "hand joints")
        if np.any(q < self.lower - 1e-6) or np.any(q > self.upper + 1e-6):
            raise ValueError("hand target exceeds model joint limits")
        return q

    def fk(self, q):
        values = dict(zip(self.names, q))
        poses = {self.data["root"]: np.eye(4)}
        for j in self.joints:
            motion = np.eye(4)
            if j["type"] == "revolute":
                motion[:3, :3] = Rotation.from_rotvec(np.array(j["axis"]) * values[j["name"]]).as_matrix()
            poses[j["child"]] = poses[j["parent"]] @ self.origins[j["name"]] @ motion
        return poses

    def geometry(self, q):
        poses = self.fk(q)
        tips, normals, samples, owners = [], [], [], []
        for finger in range(1, 6):
            t = poses[f"right_finger{finger}_tip_link"]
            pad = self.data["pads"][finger - 1]
            tips.append(points_in(t, np.array([pad["xyz"]]))[0])
            normals.append(t[:3, :3] @ np.array(pad["normal"]))
            chain = [poses[f"right_finger{finger}_link{k}"][:3, 3] for k in range(1, 5)]
            chain.append(t[:3, 3])
            for a, b in zip(chain[:-1], chain[1:]):
                for u in (0.2, 0.5, 0.8):
                    samples.append(a * (1 - u) + b * u)
                    owners.append(finger)
        # Palm proxy, defined in the root frame rather than a world-space box.
        for x in (-0.012, 0.012):
            for y in (-0.025, 0.025):
                for z in (0.02, 0.055, 0.08):
                    samples.append([x, y, z])
                    owners.append(0)
        return np.array(tips), np.array(normals), np.array(samples), np.array(owners)
