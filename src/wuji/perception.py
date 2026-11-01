"""Depth backprojection, workspace segmentation, PCA and observed-surface normals."""
from dataclasses import dataclass
import numpy as np
from scipy.spatial import cKDTree

from .geometry import matrix, points_in


@dataclass
class Observation:
    points: np.ndarray
    normals: np.ndarray
    T_base_object: np.ndarray
    extent_m: np.ndarray
    timestamp: float
    source: str
    quality: dict
    scene_points: np.ndarray

    def summary(self):
        return {"T_base_object": self.T_base_object.tolist(),
                "extent_m": self.extent_m.tolist(), "timestamp": self.timestamp,
                "source": self.source, "quality": self.quality,
                "point_count": len(self.points)}


def perceive(frame, config, target_hint=None):
    p = config["perception"]
    d, k = frame.depth_m, frame.K
    yy, xx = np.mgrid[:d.shape[0], :d.shape[1]]
    valid = np.isfinite(d) & (d > 0.05) & (d < 4)
    roi = config["camera"].get("roi_pixels")
    if roi:
        x0, y0, x1, y1 = roi
        valid &= (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
    if frame.rays is None:
        rays = np.stack([(xx - k[0, 2]) / k[0, 0],
                         (yy - k[1, 2]) / k[1, 1], np.ones_like(d)], axis=-1)
    else:
        rays = frame.rays
    points = points_in(frame.T_base_camera, rays[valid] * d[valid, None])
    lo, hi = np.asarray(p["crop_base_m"])
    keep = ((points >= lo) & (points <= hi)).all(axis=1)
    keep &= points[:, 2] > config["camera"]["table_z_m"] + p["table_margin_m"]
    points = points[keep]
    if len(points) < p["min_points"]:
        raise ValueError("target not visible: check depth, ROI and table/base calibration")
    _, ids = np.unique(np.floor(points / p["voxel_m"]), axis=0, return_index=True)
    points = points[np.sort(ids)]
    tree = cKDTree(points)
    neighbours = tree.query_ball_point(points, p["cluster_radius_m"])
    seen, clusters = set(), []
    for i in range(len(points)):
        if i in seen:
            continue
        seen.add(i)
        stack, component = [i], []
        while stack:
            j = stack.pop()
            component.append(j)
            for n in neighbours[j]:
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        if len(component) >= p["min_points"]:
            clusters.append(points[component])
    if not clusters:
        raise ValueError("no object cluster: use an ROI or adjust cluster radius")
    target = (max(clusters, key=len) if target_hint is None else
              min(clusters, key=lambda c: np.linalg.norm(c.mean(axis=0) - target_hint)))
    center = target.mean(axis=0)
    _, s, vt = np.linalg.svd(target - center, full_matrices=False)
    rotation = vt.T
    if np.linalg.det(rotation) < 0:
        rotation[:, -1] *= -1
    local = (target - center) @ rotation
    extent = np.ptp(local, axis=0)
    ntree = cKDTree(target)
    _, idx = ntree.query(target, k=min(16, len(target)))
    patches = target[idx]
    patches -= patches.mean(axis=1, keepdims=True)
    cov = np.einsum("nki,nkj->nij", patches, patches)
    _, basis = np.linalg.eigh(cov)
    normals = basis[:, :, 0]
    to_camera = frame.T_base_camera[:3, 3] - target
    normals[np.sum(normals * to_camera, axis=1) < 0] *= -1
    return Observation(target, normals, matrix(rotation, center), extent,
                       frame.timestamp, frame.source,
                       {"clusters": len(clusters), "surface_only": True,
                        "position_sigma_m": float(max(p["voxel_m"], s[-1] / np.sqrt(len(target)))),
                        "orientation_ambiguous": bool(s[0] / max(s[1], 1e-9) < 1.2)},
                       points)
