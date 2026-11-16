"""Contact-guided pose search: cached surface queries + joint/wrist refinement.

This is an independent CPU baseline, with approximate geometry costs. It is not
a dynamics solver, a force-closure proof or an arm collision planner.
"""
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree, ConvexHull, QhullError
from scipy.spatial.transform import Rotation

from .geometry import matrix, matrix_pose, points_in


def plan_grasps(observation, hand, config):
    p = config["planning"]
    if p["seeds"] < 1 or p["iterations"] < 1 or p["top_k"] < 1:
        raise ValueError("planning seeds, iterations and top_k must be positive")
    cloud = observation.points
    center = cloud.mean(axis=0)
    tree = cKDTree(cloud)
    outside_target = tree.query(observation.scene_points)[0] > 0.008
    obstacles = observation.scene_points[outside_target]
    obstacle_tree = cKDTree(obstacles) if len(obstacles) else None
    rng = np.random.default_rng(p["seed"])
    try:
        hull = ConvexHull(cloud[::max(1, len(cloud) // 180)])
        planes = hull.equations
    except QhullError:
        planes = None
    active = np.array([0, 1, 2])  # thumb, index and middle; other joints remain free
    pairs = None
    floor_z = config["camera"]["table_z_m"]

    def decode(x):
        return matrix(Rotation.from_rotvec(x[3:6]).as_matrix(), x[:3]), x[6:]

    def evaluate(x, regularize=False):
        nonlocal pairs
        t, q = decode(x)
        tips, normals, bones, owners = hand.geometry(q)
        tips = points_in(t, tips)
        bones = points_in(t, bones)
        normals = normals @ t[:3, :3].T
        dist, ids = tree.query(tips[active])
        onorm = observation.normals[ids]
        # A fingertip pad and an object surface should face each other.
        contact = ((tips[active] - cloud[ids]) / 0.012).ravel()
        alignment = (normals[active] + onorm).ravel() * 0.3
        opposition = np.maximum(0, onorm[1:] @ onorm[0] + 0.25) * 2
        if planes is None:
            penetration = np.zeros(len(bones))
        else:
            signed = np.max(bones @ planes[:, :3].T + planes[:, 3], axis=1)
            penetration = np.maximum(0, 0.005 - signed) / 0.008
        if pairs is None:
            a, b = np.triu_indices(len(bones), k=1)
            valid = (owners[a] != owners[b]) & (owners[a] > 0) & (owners[b] > 0)
            pairs = (a[valid], b[valid])
        a, b = pairs
        self_cost = np.maximum(0, 0.010 - np.linalg.norm(bones[a] - bones[b], axis=1)) / 0.008
        table = np.maximum(0, floor_z + 0.006 - bones[:, 2]) / 0.01
        obstacle = (np.maximum(0, 0.008 - obstacle_tree.query(bones)[0]) / 0.008
                    if obstacle_tree is not None else np.zeros(len(bones)))
        spread = np.maximum(0, 0.025 - np.linalg.norm(tips[0] - tips[1:3], axis=1)) / 0.025
        residual = np.r_[contact, alignment, opposition, penetration * 0.6,
                         self_cost * 0.3, table, obstacle, spread]
        if regularize:
            residual = np.r_[residual, 0.025 * (q - hand.open_q)]
        return residual, dist

    base_q = hand.open_q.copy()
    base_q[[0, 2, 3]] = [0.65, 0.4, 0.4]
    for f in range(1, 5):
        base_q[f * 4 + np.array([0, 2, 3])] = [0.55, 0.55, 0.55]
    base_q = np.clip(base_q, hand.lower, hand.upper)
    tips0 = hand.geometry(base_q)[0][active].mean(axis=0)
    workspace_lo, workspace_hi = np.asarray(config["motion"]["workspace_m"])
    lower = np.r_[workspace_lo, [-2 * np.pi] * 3, hand.lower]
    upper = np.r_[workspace_hi, [2 * np.pi] * 3, hand.upper]
    proposals = []
    for i in range(p["seeds"]):
        # Orient local +Z mostly down; yaw seeds give different opposition directions.
        r = Rotation.from_euler("z", 2 * np.pi * i / p["seeds"]).as_matrix() @ Rotation.from_euler("x", np.pi).as_matrix()
        q = np.clip(base_q + rng.normal(0, 0.08, 20), hand.lower, hand.upper)
        x0 = np.r_[center - r @ tips0, Rotation.from_matrix(r).as_rotvec(), q]
        x0 = np.clip(x0, lower + 1e-7, upper - 1e-7)
        result = least_squares(lambda x: evaluate(x, True)[0], x0,
                               bounds=(lower, upper), max_nfev=p["iterations"],
                               ftol=0.02, xtol=0.002, gtol=0.02,
                               diff_step=1e-4)
        residual, distance = evaluate(result.x)
        t, q = decode(result.x)
        tips, _, bones, _ = hand.geometry(q)
        tips, bones = points_in(t, tips), points_in(t, bones)
        ids = tree.query(tips[active])[1]
        ns = observation.normals[ids]
        opposition_dot = float(np.max(ns[1:] @ ns[0]))
        penetration_m = (0.0 if planes is None else
                         float(max(0, -np.max(bones @ planes[:, :3].T + planes[:, 3], axis=1).min())))
        table_clearance = float(bones[:, 2].min() - floor_z)
        obstacle_clearance = (None if obstacle_tree is None else float(obstacle_tree.query(bones)[0].min()))
        a, b = pairs
        self_clearance = float(np.linalg.norm(bones[a] - bones[b], axis=1).min())
        pre = t.copy()
        pre[:3, 3] -= t[:3, 2] * p["pregrasp_m"]
        in_workspace = ((pre[:3, 3] >= workspace_lo) & (pre[:3, 3] <= workspace_hi)).all()
        proposals.append({"T_base_palm": t.tolist(), "tcp_pose": matrix_pose(t).tolist(),
                          "pregrasp_pose": matrix_pose(pre).tolist(), "q": q.tolist(),
                          "score": float(np.mean(residual ** 2)),
                          "max_contact_distance_m": float(distance.max()),
                          "usable": bool(distance.max() <= p["contact_tolerance_m"] and in_workspace
                                         and penetration_m <= p["max_proxy_penetration_m"]
                                         and (p["max_opposition_dot"] is None
                                              or opposition_dot <= p["max_opposition_dot"])
                                         and table_clearance >= 0.005 and self_clearance >= 0.006
                                         and (obstacle_clearance is None or obstacle_clearance >= 0.006)),
                          "geometry_metrics": {"max_opposition_dot": opposition_dot,
                                               "proxy_penetration_m": penetration_m,
                                               "table_clearance_m": table_clearance,
                                               "self_clearance_m": self_clearance,
                                               "obstacle_clearance_m": obstacle_clearance},
                          "seed_index": i, "evaluations": result.nfev,
                          "geometry": "observed surface + convex hull and bone proxies"})
    proposals.sort(key=lambda c: (not c["usable"], c["score"]))
    return {"algorithm": "contact_guided_pose_search", "observation": observation.summary(),
            "joint_order": hand.names, "model": hand.data["model"],
            "candidates": proposals[:p["top_k"]],
            "limitations": ["partial surface; convex hull is approximate",
                            "arm path and reachability checked only by the real controller",
                            "contact score is not physical grasp success"]}
