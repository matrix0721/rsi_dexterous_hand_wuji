# Sources and licenses

The workflow catalog is adapted from this workspace's
`v1.1-dexjoco-imagine/agent_skills`: observation, modeling, imagination, measured
execution, repair and evidence-preserving reuse. No benchmark environments,
private state, recorded task solutions, model weights or success claims are bundled.

`src/wujiimagine` reuses the MIT-licensed `v1-wuji` implementation from
this workspace: hardware adapters, configuration, RGB-D, hand FK, contact-guided
search, previews, recipe hierarchy and repair. Resource lookups are moved to this
project's namespace. The original MIT LICENSE is included.

The numeric Hand 1 right model was extracted from Wuji Technology's
[robot descriptions](https://github.com/wuji-technology/wuji-description), revision
`829c9aa27cb12c3a49d5b8d63c9869dd8f656702`, `hand/body/urdf/right.urdf`.
Its MIT license is included at
`models/WUJI_MODEL_LICENSE.txt`.
Pads, skeleton samples and fingertip sphere proxies are approximate project additions.

Optional runtime SDKs (ur_rtde, WujihandPy, RealSense, MuJoCo) retain their own
licenses. No SDK or device firmware is redistributed. NumPy/SciPy provide the
baseline numerical routines. Hardware API behavior is inherited from the local
adapter; actual workstation/SDK compatibility must be established on that hardware.
