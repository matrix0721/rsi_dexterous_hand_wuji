"""Independent previews. Hypotheses and physics proxies are explicitly labelled."""
import copy
import numpy as np
from scipy.spatial.transform import Rotation

from .geometry import pose_matrix, points_in


def endpoint(actions, state, config):
    state = copy.deepcopy(state)
    for a in actions:
        op = a["op"]
        if op == "move_tcp":
            state["tcp_pose"] = list(a["pose"])
        elif op == "lift":
            state["tcp_pose"][2] += a.get("height_m", config["verification"]["lift_m"])
        elif op == "set_hand":
            state["hand_q"] = list(a["q"])
    return state


def rollout(actions, start, world, config, hand, hypothesis, engine="kinematic", particles=4):
    final = endpoint(actions, start, config)
    center = np.asarray(world["center_m"], dtype=float)
    if engine == "kinematic":
        relation = hypothesis.get("relation", "stationary")
        if relation == "attached":
            # Rigid object-to-palm hypothesis, including palm rotation.
            relative = np.linalg.inv(pose_matrix(start["tcp_pose"])) @ np.r_[center, 1]
            predicted = (pose_matrix(final["tcp_pose"]) @ relative)[:3]
        elif relation == "stationary":
            predicted = center.copy()
        elif relation == "translation":
            predicted = center + np.asarray(hypothesis["object_delta_m"], dtype=float)
            if predicted.shape != (3,) or not np.isfinite(predicted).all():
                raise ValueError("object_delta_m must contain three finite values")
        else:
            raise ValueError("relation must be stationary, attached or translation")
        return {"engine": engine, "object_center_m": predicted.tolist(), "robot_endpoint": final,
                "scope": "rigid-motion hypothesis; no contact dynamics or grip certification",
                "particles": [], "hypothesis": hypothesis}
    if engine != "mujoco":
        raise ValueError("engine must be kinematic or mujoco")
    if not 1 <= particles <= 64:
        raise ValueError("particles must be in [1,64]")
    return physics_rollout(actions, start, world, config, hand, hypothesis, particles, final)


def physics_rollout(actions, start, world, config, hand, hypothesis, particles, final):
    # MuJoCo never receives a real robot or camera. All contact surfaces are proxies.
    import mujoco
    rng = np.random.default_rng(hypothesis.get("seed", 7))
    center = np.asarray(world["center_m"])
    half = np.maximum(np.asarray(world["aabb_extent_m"]) / 2, .003)
    floor = float(config["camera"]["table_z_m"])
    mass = float(hypothesis.get("mass_kg", .08))
    friction = float(hypothesis.get("friction", .7))
    if not np.isfinite([mass, friction]).all() or mass <= 0 or friction <= 0:
        raise ValueError("positive finite mass_kg and friction required")
    uncertainty = float(hypothesis.get("parameter_spread", .25))
    if not np.isfinite(uncertainty) or not 0 <= uncertainty < 1:
        raise ValueError("parameter_spread must be in [0,1)")
    bodies = ''.join(f'<body name="tip{i}" mocap="true" pos="0 0 2">'
                     '<geom type="sphere" size="0.009"/></body>' for i in range(5))
    values = []
    for _ in range(particles):
        m, f = mass * rng.uniform(1-uncertainty, 1+uncertainty), friction * rng.uniform(1-uncertainty, 1+uncertainty)
        xml = f'''<mujoco><option timestep="0.004" gravity="0 0 -9.81"/>
        <default><geom friction="{f} 0.005 0.0001" condim="3"/></default>
        <worldbody><geom type="plane" size="2 2 .1" pos="0 0 {floor}"/>
        <body name="object" pos="{' '.join(map(str, center))}"><freejoint/>
        <geom type="box" size="{' '.join(map(str, half))}" mass="{m}"/></body>{bodies}
        </worldbody></mujoco>'''
        model = mujoco.MjModel.from_xml_string(xml)
        data = mujoco.MjData(model)
        state = copy.deepcopy(start)
        ticks = 0
        for action in actions:
            target = endpoint([action], state, config)
            pa, pb = pose_matrix(state["tcp_pose"]), pose_matrix(target["tcp_pose"])
            qa, qb = np.asarray(state["hand_q"]), np.asarray(target["hand_q"])
            speed = config["motion"]["speed_m_s"]
            duration = max(.1, np.linalg.norm(pb[:3, 3]-pa[:3, 3])/speed,
                           np.max(np.abs(qb-qa))/config["motion"]["hand_speed_rad_s"],
                           (Rotation.from_matrix(pa[:3, :3]).inv() * Rotation.from_matrix(pb[:3, :3])).magnitude()/.3)
            if action["op"] == "wait":
                duration = action["seconds"]
            duration = float(action.get("duration_s", duration))
            if not np.isfinite(duration) or duration <= 0:
                raise ValueError("physics duration_s must be positive and finite")
            n = max(1, int(np.ceil(duration/.004)))
            ra = Rotation.from_matrix(pa[:3, :3])
            delta_r = (ra.inv() * Rotation.from_matrix(pb[:3, :3])).as_rotvec()
            for j in range(n):
                t = (j+1)/n
                palm = np.eye(4)
                palm[:3, :3] = (ra * Rotation.from_rotvec(t * delta_r)).as_matrix()
                palm[:3, 3] = pa[:3, 3]*(1-t) + pb[:3, 3]*t
                tips = points_in(palm, hand.geometry(qa*(1-t)+qb*t)[0])
                data.mocap_pos[:] = tips
                mujoco.mj_step(model, data)
            ticks += n
            state = target
        values.append({"center_m": data.qpos[:3].tolist(), "mass_kg": float(m),
                       "friction": float(f), "steps": ticks,
                       "finite": bool(np.isfinite(data.qpos).all())})
    points = np.asarray([p["center_m"] for p in values])
    if not np.isfinite(points).all():
        raise RuntimeError("nonfinite physics rollout; change the proxy/hypothesis")
    return {"engine": "mujoco", "object_center_m": points.mean(axis=0).tolist(),
            "spread_m": points.std(axis=0).tolist(), "particles": values,
            "robot_endpoint": final, "hypothesis": hypothesis,
            "scope": "observed AABB + five kinematic fingertip spheres + floor; no arm/palm shell, hidden geometry or success oracle"}
