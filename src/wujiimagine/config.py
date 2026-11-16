import copy
import json
from pathlib import Path

DEFAULT = {
    "hardware": {"calibrated": False, "robot_ip": "", "hand_serial": "",
                 "tcp_flange_pose": [0, 0, 0, 0, 0, 0], "payload_kg": 0.5,
                 "payload_cog_m": [0, 0, 0.05]},
    "camera": {"serial": "", "width": 640, "height": 480, "fps": 30,
               "T_base_camera": [[1, 0, 0, 0], [0, -1, 0, 0],
                                 [0, 0, -1, 1], [0, 0, 0, 1]],
               "roi_pixels": None, "table_z_m": 0.0},
    "perception": {"voxel_m": 0.004, "cluster_radius_m": 0.018,
                   "min_points": 30, "table_margin_m": 0.008,
                   "crop_base_m": [[-0.8, -0.8, 0.008], [0.8, 0.8, 0.8]]},
    "planning": {"seeds": 8, "iterations": 45, "top_k": 4,
                 "contact_tolerance_m": 0.018, "pregrasp_m": 0.08,
                 "max_proxy_penetration_m": 0.004, "max_opposition_dot": None,
                 "seed": 7},
    "motion": {"speed_m_s": 0.04, "acceleration_m_s2": 0.10,
               "timeout_s": 40.0, "force_stop_n": 35.0,
               "workspace_m": [[-0.8, -0.8, 0.02], [0.8, 0.8, 0.9]],
               "hand_speed_rad_s": 0.35, "hand_timeout_s": 8.0,
               "effort_stop_ratio": 0.65},
    "verification": {"lift_m": 0.06, "min_observed_lift_m": 0.025,
                     "max_tcp_object_drift_m": 0.04},
}


def load_config(path=None):
    config = copy.deepcopy(DEFAULT)
    if path:
        def merge(dst, src):
            for key, value in src.items():
                if isinstance(value, dict) and isinstance(dst.get(key), dict):
                    merge(dst[key], value)
                else:
                    dst[key] = value
        merge(config, json.loads(Path(path).read_text(encoding="utf-8")))
    return config
