"""Rigid eye-to-hand fit from corresponding 3D points (metres), no robot motion."""
import argparse
import json
from pathlib import Path
import numpy as np


def fit(camera_points, base_points):
    a, b = np.asarray(camera_points, dtype=float), np.asarray(base_points, dtype=float)
    if a.ndim != 2 or a.shape[1] != 3 or a.shape != b.shape or len(a) < 3 or not np.isfinite([a, b]).all():
        raise ValueError("need at least three finite corresponding Nx3 points")
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    if np.linalg.matrix_rank(a - ca, tol=1e-6) < 2:
        raise ValueError("calibration points must not be collinear")
    u, _, vt = np.linalg.svd((a - ca).T @ (b - cb))
    correction = np.diag([1, 1, np.linalg.det(vt.T @ u.T)])
    r = vt.T @ correction @ u.T
    t = cb - r @ ca
    errors = np.linalg.norm(a @ r.T + t - b, axis=1)
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = r, t
    return {"T_base_camera": transform.tolist(), "rms_m": float(np.sqrt(np.mean(errors ** 2))),
            "max_error_m": float(errors.max()), "points": len(a)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("points", help="JSON with camera_points_m and base_points_m")
    parser.add_argument("--output", default="outputs/camera_fit.json")
    args = parser.parse_args()
    data = json.loads(Path(args.points).read_text(encoding="utf-8"))
    result = fit(data["camera_points_m"], data["base_points_m"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
