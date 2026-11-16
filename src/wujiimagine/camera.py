"""Eye-to-hand RGB-D input, replay files and a labelled synthetic fixture."""
from dataclasses import dataclass
from pathlib import Path
import time
import numpy as np

from .geometry import transform


@dataclass
class Frame:
    rgb: np.ndarray
    depth_m: np.ndarray
    K: np.ndarray
    T_base_camera: np.ndarray
    timestamp: float
    source: str
    rays: np.ndarray | None = None

    def __post_init__(self):
        self.depth_m = np.asarray(self.depth_m, dtype=float)
        self.K = np.asarray(self.K, dtype=float)
        self.T_base_camera = transform(self.T_base_camera)
        h, w = self.depth_m.shape
        if (self.rgb.shape != (h, w, 3) or self.K.shape != (3, 3)
                or not np.isfinite(self.K).all() or min(self.K[0, 0], self.K[1, 1]) <= 0):
            raise ValueError("unaligned RGB-D frame or invalid intrinsics")
        if self.rays is not None and (self.rays.shape != (h, w, 3) or not np.isfinite(self.rays).all()):
            raise ValueError("invalid camera deprojection rays")

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        extra = {} if self.rays is None else {"rays": self.rays}
        np.savez_compressed(path, rgb=self.rgb, depth_m=self.depth_m, K=self.K,
                            T_base_camera=self.T_base_camera,
                            timestamp=self.timestamp, source=self.source, **extra)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as d:
            return cls(d["rgb"], d["depth_m"], d["K"], d["T_base_camera"],
                       float(d["timestamp"]), str(d["source"]),
                       d["rays"] if "rays" in d else None)


class ReplayCamera:
    def __init__(self, paths):
        self.paths = iter(paths)

    def capture(self):
        try:
            return Frame.load(next(self.paths))
        except StopIteration as exc:
            raise RuntimeError("replay exhausted: provide a fresh frame for each observe") from exc

    def close(self):
        pass


class RealSenseCamera:
    def __init__(self, config):
        import pyrealsense2 as rs
        self.rs = rs
        self.pipeline = rs.pipeline()
        c = rs.config()
        if config["serial"]:
            c.enable_device(config["serial"])
        w, h, fps = (config[k] for k in ("width", "height", "fps"))
        c.enable_stream(rs.stream.depth, w, h, rs.format.z16, fps)
        c.enable_stream(rs.stream.color, w, h, rs.format.rgb8, fps)
        self.extrinsic = transform(config["T_base_camera"])
        profile = self.pipeline.start(c)
        self.scale = profile.get_device().first_depth_sensor().get_depth_scale()
        self.align = rs.align(rs.stream.color)
        self.rays = None
        for _ in range(5):
            self.pipeline.wait_for_frames(5000)

    def capture(self):
        # Drop queued frames so post-motion verification does not reuse a pre-motion image.
        while self.pipeline.poll_for_frames():
            pass
        for _ in range(5):
            frames = self.align.process(self.pipeline.wait_for_frames(5000))
            depth, color = frames.get_depth_frame(), frames.get_color_frame()
            if not depth or not color:
                continue
            i = color.profile.as_video_stream_profile().get_intrinsics()
            if self.rays is None and any(abs(x) > 1e-6 for x in i.coeffs):
                self.rays = np.array([self.rs.rs2_deproject_pixel_to_point(i, [u, v], 1.)
                                      for v in range(i.height) for u in range(i.width)]).reshape(i.height, i.width, 3)
            k = np.array([[i.fx, 0, i.ppx], [0, i.fy, i.ppy], [0, 0, 1]])
            return Frame(np.asanyarray(color.get_data()).copy(),
                         np.asanyarray(depth.get_data()).astype(float) * self.scale,
                         k, self.extrinsic, time.time(), "realsense_rgbd", self.rays)
        raise RuntimeError("camera did not provide a fresh aligned RGB-D frame")

    def close(self):
        self.pipeline.stop()


class SyntheticCamera:
    """A rendered ellipsoid for offline pipeline exercise; contains no physics."""
    def __init__(self, robot=None):
        self.robot = robot

    def capture(self):
        h, w = 160, 200
        yy, xx = np.mgrid[:h, :w]
        k = np.array([[240., 0, 100], [0, 240., 80], [0, 0, 1]])
        lift = 0 if self.robot is None else self.robot.object_lift
        r = ((xx - 100) / 17) ** 2 + ((yy - 80) / 22) ** 2
        depth = np.ones((h, w))
        mask = r < 1
        depth[mask] = 1 - lift - 0.04 - 0.04 * np.sqrt(1 - r[mask])
        rgb = np.full((h, w, 3), 120, dtype=np.uint8)
        rgb[mask] = [210, 70, 45]
        t = np.diag([1., -1., -1., 1.])
        t[:3, 3] = [0.4, 0, 1]
        return Frame(rgb, depth, k, t, time.time(), "synthetic_fixture")

    def close(self):
        pass
