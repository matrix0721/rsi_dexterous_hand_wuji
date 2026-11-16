---
name: world-modeling
description: Reconstruct the visible target surface without inventing hidden geometry.
---

# World modeling

`ctx.world(roi=[x0,y0,x1,y1], target_hint=[x,y,z])` acquires a frame and builds a
voxel cluster, normals, PCA frame, visible center and AABB. ROI is optional; by
default the largest cluster is selected. A hint selects the closest cluster,
which is geometric association and does not establish semantic identity.
`fresh=False` reuses the latest frame. Inspect quality and surface-only scope.

`ctx.world_state()` reads the cache without capture. Its sequence shows whether
motion occurred since reconstruction. Reconstruct at initial localization,
target loss or a useful comparison; ordinary measured execution does not require
a full world update. The baseline has no automatic semantic detector, multi-part
mechanism inference, fused mesh or complete robot-shell mask. Use an ROI and
current pixels for thin functional features; unseen surfaces remain unknown.

Diagnose identity, occlusion, depth scale, camera calibration and TCP tracking
before changing a physical hypothesis. Do not shift the world to hide robot error.
