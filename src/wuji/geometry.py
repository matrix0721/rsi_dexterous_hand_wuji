"""All transforms use T_destination_source, metres, radians and column vectors."""
import numpy as np
from scipy.spatial.transform import Rotation


def vector(value, size, name="vector"):
    a = np.asarray(value, dtype=float)
    if a.shape != (size,) or not np.isfinite(a).all():
        raise ValueError(f"{name}: expected {size} finite values")
    return a


def transform(value):
    a = np.asarray(value, dtype=float)
    if (a.shape != (4, 4) or not np.isfinite(a).all()
            or not np.allclose(a[3], [0, 0, 0, 1])
            or not np.allclose(a[:3, :3].T @ a[:3, :3], np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(a[:3, :3]), 1, atol=1e-5)):
        raise ValueError("expected rigid 4x4 transform")
    return a


def matrix(rotation=None, translation=None):
    t = np.eye(4)
    if rotation is not None:
        t[:3, :3] = rotation
    if translation is not None:
        t[:3, 3] = translation
    return t


def pose_matrix(pose):
    pose = vector(pose, 6, "TCP pose")
    return matrix(Rotation.from_rotvec(pose[3:]).as_matrix(), pose[:3])


def matrix_pose(t):
    t = transform(t)
    return np.r_[t[:3, 3], Rotation.from_matrix(t[:3, :3]).as_rotvec()]


def points_in(t, points):
    return np.asarray(points) @ t[:3, :3].T + t[:3, 3]
