---
name: rgbd-perception
description: Inspect calibrated live RGB-D and measured TCP/hand state.
---

# RGB-D perception

`ctx.observe()` records aligned RGB, depth in metres, intrinsics, base-camera
transform, timestamp and robot state. Open its NPZ with `allow_pickle=False`.
`ctx.pixel_to_world([u,v])` deprojects a pixel in the latest observation, using
stored distortion rays when present. It does not acquire another frame.

Camera extrinsics are fixed eye-to-hand. Eye-in-hand cameras require a factory
plugin updating extrinsics per capture. No camera hardware synchronization is
assumed. Inspect RGB and depth around the actual functional contact feature;
an object's visible center is not its nozzle, hinge or contact face. Reacquire a
lost target instead of relabeling another cluster. Synthetic and replay sources
are offline evidence. Reprocessing the same frame adds no observation.
