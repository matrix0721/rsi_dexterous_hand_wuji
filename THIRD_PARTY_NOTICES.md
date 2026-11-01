# Sources and notices

## Bundled kinematic data

`src/wuji/resources/wuji_hand1_right.json` is a compact numeric extraction of
`hand/body/urdf/right.urdf` from [Wuji Technology's robot descriptions](https://github.com/wuji-technology/wuji-description),
revision `829c9aa27cb12c3a49d5b8d63c9869dd8f656702`.
The joint origins, axes and limits retain their original MIT license:
[WUJI_MODEL_LICENSE.txt](src/wuji/resources/WUJI_MODEL_LICENSE.txt).
Contact pads and the collision proxy sampling are approximate project additions.
No meshes or CAD files are bundled.

## Runtime integrations

- [ur_rtde documentation](https://sdurobotics.gitlab.io/ur_rtde/) defines the arm API.
- [WujihandPy](https://github.com/wuji-technology/wujihandpy) provides the USB hand API.
- [RealSense SDK](https://github.com/realsenseai/librealsense) provides RGB-D capture.
- NumPy and SciPy provide numerical routines. Optional SDKs are installed separately
  and retain their own licenses; the project's MIT license does not relicense them.

The sibling `v1.3-dexjoco-image`, `v1.3-bench2dex-image`, and
`v1.3-handson-image` projects informed the observation/skill/evidence architecture.
Their source trees, benchmark assets, evaluation traces and grasp archives are not
redistributed as part of this standalone project.
