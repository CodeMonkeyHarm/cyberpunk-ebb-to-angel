"""测试用合成网格：不依赖任何真实资产。"""
from __future__ import annotations

import math

import numpy as np

from automation.body_model import BodyModel


def cylinder(radius: float = 0.10, height: float = 1.0, segments: int = 96,
             z0: float = 0.0, shift=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0),
             with_landmarks: bool = True, rings: int = 24) -> BodyModel:
    """竖直圆柱（Z 轴），带 rings 层环，保证任意高度带内都有顶点。"""
    verts = []
    for r in range(rings + 1):
        z = z0 + height * r / rings
        for i in range(segments):
            a = 2 * math.pi * i / segments
            verts.append((radius * math.cos(a), radius * math.sin(a), z))
    tris = []
    for r in range(rings):
        base0, base1 = r * segments, (r + 1) * segments
        for i in range(segments):
            j = (i + 1) % segments
            tris.append((base0 + i, base0 + j, base1 + i))
            tris.append((base0 + j, base1 + j, base1 + i))
    v = np.asarray(verts, dtype=np.float64)
    v[:, 0] = v[:, 0] * scale[0] + shift[0]
    v[:, 1] = v[:, 1] * scale[1] + shift[1]
    v[:, 2] = v[:, 2] * scale[2] + shift[2]

    names, positions = [], []
    if with_landmarks:
        names = ["LeftFoot", "LeftLeg", "LeftUpLeg", "Hips", "Spine", "Spine3",
                 "LeftShoulder", "LeftForeArm", "LeftHand"]
        positions = np.asarray([
            (0.0, 0.0, z0 + height * 0.08),
            (0.0, 0.0, z0 + height * 0.38),
            (0.0, 0.0, z0 + height * 0.66),
            (0.0, 0.0, z0 + height * 0.66),
            (0.0, 0.0, z0 + height * 0.71),
            (0.0, 0.0, z0 + height * 0.89),
            (0.0, 0.0, z0 + height * 0.97),
            (5.0, 0.0, z0 + height * 0.84),   # 故意放到远处：无手臂
            (6.0, 0.0, z0 + height * 0.75),
        ], dtype=np.float64)

    t = np.asarray(tris, dtype=np.int64)
    normals = np.zeros_like(v)
    geo = {"chunks": [], "object_type": "CMesh", "geometry_hash": None,
           "declared_bbox": {"min": v.min(axis=0).tolist(), "max": v.max(axis=0).tolist()},
           "materials": ["test"], "appearances": [], "bone_names": names,
           "bone_positions": positions.tolist() if len(names) else [],
           "ibm_cp77": [], "quantization": {"scale": [1, 1, 1], "offset": [0, 0, 0]}}
    return BodyModel(
        body_id="TEST", profile={"source": {"mesh_json": "<synthetic>",
                                           "raw_mesh": "<synthetic>"},
                                 "display_name": "synthetic", "asset_version": "0",
                                 "status": "READY"},
        geo=geo, vertices=v, normals=normals, triangles=t,
        chunk_of_vertex=np.zeros(len(v), dtype=np.int32),
        bones={"names": names, "positions": positions if len(names) else np.zeros((0, 3)),
               "ibm": None},
        hierarchy=None, source_hashes={},
    )
