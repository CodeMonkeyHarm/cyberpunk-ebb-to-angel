"""统一身形数据结构：任一身形解码后都规范成同一套字段（BodyModel）。

设计目标：
- 上层（morphology / correspondence / diff）只依赖本模块的接口，不关心数据来自哪个身形；
- 所有字段可序列化成 `cp77.body.reference/v1` 记录，便于跨身形比对与归档；
- 数值一律用 numpy 数组保存（顶点 9 万级，纯 Python 列表做截面会很慢）。

坐标系：**统一使用 CP77 源坐标（Z-up，米制）**。
glTF 的 Y-up 只存在于导出文件里，分析阶段不转换，避免来回换算出错。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from . import body_profiles as P
from . import cp77_skin as S

SCHEMA = "cp77.body.reference/v1"
GENERATOR = "automation/body_model.py"

# 关键地标：CP77 骨骼名（实测 167 骨里存在）
LANDMARK_BONES = {
    "ankle": "LeftFoot",
    "knee": "LeftLeg",
    "hip": "LeftUpLeg",
    "pelvis": "Hips",
    "waist": "Spine",
    "chest": "Spine3",
    "shoulder": "LeftShoulder",
    "neck": "Neck",
    "elbow": "LeftForeArm",
    "wrist": "LeftHand",
}

REGION_ORDER = ("ankle", "calf", "knee", "thigh", "hip", "pelvis",
                "waist", "chest", "shoulder", "upper_arm")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_array(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


@dataclass
class BodyModel:
    body_id: str
    profile: dict[str, Any]
    geo: dict[str, Any]
    vertices: np.ndarray            # (N,3) CP77 空间，米
    normals: np.ndarray             # (N,3) 单位向量，缺失时为 0
    triangles: np.ndarray           # (M,3) 全局顶点索引
    chunk_of_vertex: np.ndarray     # (N,) 顶点所属 chunk
    bones: dict[str, Any] = field(default_factory=dict)
    hierarchy: dict[str, Any] | None = None
    source_hashes: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ 基础属性
    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.triangles.shape[0])

    @property
    def height(self) -> float:
        return float(self.vertices[:, 2].max() - self.vertices[:, 2].min())

    def dimensions(self) -> dict[str, Any]:
        v = self.vertices
        mn, mx = v.min(axis=0), v.max(axis=0)
        return {
            "bbox_min": [round(float(x), 6) for x in mn],
            "bbox_max": [round(float(x), 6) for x in mx],
            "size_xyz": [round(float(mx[i] - mn[i]), 6) for i in range(3)],
            "height_m": round(float(mx[2] - mn[2]), 6),
            "width_m": round(float(mx[0] - mn[0]), 6),
            "depth_m": round(float(mx[1] - mn[1]), 6),
            "centroid": [round(float(x), 6) for x in v.mean(axis=0)],
            "z_min": round(float(mn[2]), 6),
            "z_max": round(float(mx[2]), 6),
        }

    def landmarks(self) -> dict[str, dict[str, Any]]:
        """按骨骼位置取地标，并给出标准化高度（0=脚底，1=最高点）。"""
        names = self.bones.get("names", [])
        pos = self.bones.get("positions")
        if pos is None or not names:
            return {}
        idx = {n: i for i, n in enumerate(names)}
        z0, z1 = float(self.vertices[:, 2].min()), float(self.vertices[:, 2].max())
        h = max(z1 - z0, 1e-9)
        out: dict[str, Any] = {}
        for key, bone in LANDMARK_BONES.items():
            if bone not in idx:
                continue
            p = [float(x) for x in pos[idx[bone]]]
            out[key] = {
                "bone": bone,
                "position": [round(x, 6) for x in p],
                "z": round(p[2], 6),
                "height_norm": round((p[2] - z0) / h, 6),
            }
        out["_reference"] = {"z_min": round(z0, 6), "z_max": round(z1, 6),
                             "height_m": round(h, 6)}
        return out

    # ------------------------------------------------------------ 几何度量
    def measure_geometry(self) -> dict[str, Any]:
        v, t = self.vertices, self.triangles
        a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
        cross = np.cross(b - a, c - a)
        tri_area = 0.5 * np.linalg.norm(cross, axis=1)
        signed_vol = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
        # 边界边统计 → 判断是否闭合（开放网格的质量会失真）
        edges = np.vstack([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
        edges = np.sort(edges, axis=1)
        uniq, counts = np.unique(edges, axis=0, return_counts=True)
        boundary = int((counts == 1).sum())
        return {
            "surface_area_m2": round(float(tri_area.sum()), 6),
            "volume_signed_m3": round(float(signed_vol.sum()), 6),
            "volume_abs_m3": round(abs(float(signed_vol.sum())), 6),
            "edge_count_unique": int(uniq.shape[0]),
            "boundary_edges": boundary,
            "watertight": boundary == 0,
            "triangle_area_min_m2": round(float(tri_area.min()), 12),
            "triangle_area_max_m2": round(float(tri_area.max()), 8),
            "degenerate_triangles": int((tri_area < 1e-12).sum()),
        }

    def height_normalized(self) -> np.ndarray:
        z = self.vertices[:, 2]
        z0, z1 = float(z.min()), float(z.max())
        return (z - z0) / max(z1 - z0, 1e-9)

    def slice_band(self, z_lo: float, z_hi: float) -> np.ndarray:
        z = self.vertices[:, 2]
        return (z >= z_lo) & (z <= z_hi)

    # ------------------------------------------------------------ 权重摘要
    def weight_summary(self) -> dict[str, Any]:
        sums: list[float] = []
        infl: list[int] = []
        unweighted = 0
        for ch in self.geo["chunks"]:
            sums.extend(ch["weight_sums"])
            for j0, w0, j1, w1 in zip(ch["joints0"], ch["weights0"],
                                      ch["joints1"], ch["weights1"]):
                n = sum(1 for w in w0 if w > 0) + sum(1 for w in w1 if w > 0)
                infl.append(n)
                if n == 0:
                    unweighted += 1
        arr = np.asarray(sums, dtype=np.float64) if sums else np.zeros(1)
        return {
            "vertices": int(len(sums)),
            "unweighted_vertices": unweighted,
            "weight_sum_min": round(float(arr.min()), 6),
            "weight_sum_mean": round(float(arr.mean()), 6),
            "weight_sum_max": round(float(arr.max()), 6),
            "max_influences": int(max(infl)) if infl else 0,
            "influence_histogram": {str(k): int(v) for k, v in
                                    sorted(_hist(infl).items())},
        }

    # ------------------------------------------------------------ 统一记录
    def to_unified(self, *, outputs: dict[str, Any] | None = None,
                   checks: dict[str, Any] | None = None) -> dict[str, Any]:
        prof = self.profile
        names = self.bones.get("names", [])
        parents = (self.hierarchy or {}).get("parents")
        return {
            "schema": SCHEMA,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "generator": f"{GENERATOR} (body_model v{VERSION})",
            "body_id": self.body_id,
            "display_name": prof.get("display_name"),
            "asset_version": prof.get("asset_version"),
            "status": prof.get("status"),
            "source": {
                "mesh_json": prof["source"].get("mesh_json"),
                "mesh_json_sha256": self.source_hashes.get("mesh_json"),
                "raw_mesh": prof["source"].get("raw_mesh"),
                "raw_mesh_sha256": self.source_hashes.get("raw_mesh"),
                "packs": prof["source"].get("packs"),
                "provenance": prof["source"].get("provenance"),
            },
            "model": {
                "object_type": self.geo.get("object_type"),
                "geometry_hash": self.geo.get("geometry_hash"),
                "materials": self.geo.get("materials"),
                "appearances": len(self.geo.get("appearances") or []),
                "chunks": len(self.geo["chunks"]),
                "vertices": self.vertex_count,
                "triangles": self.triangle_count,
                "dimensions": self.dimensions(),
                "geometry": self.measure_geometry(),
                "landmarks": self.landmarks(),
            },
            "skeleton": {
                "bone_count": len(names),
                "bone_names_sha256": sha256_array(np.asarray([hash(n) for n in names],
                                                             dtype=np.int64)),
                "hierarchy_type": (self.hierarchy or {}).get("type", "none"),
                "hierarchy_roots": (self.hierarchy or {}).get("provenance", {}).get("roots"),
                "hierarchy_max_depth": (self.hierarchy or {}).get("provenance", {}).get("max_depth"),
                "parent_map_sha256": (sha256_array(np.asarray(
                    [hash((k, parents[k])) for k in sorted(parents)], dtype=np.int64))
                    if parents else None),
            },
            "bind": {
                "ibm_count": int(np.asarray(self.bones.get("ibm")).shape[0]),
                "ibm_sha256": (sha256_array(np.asarray(self.bones["ibm"], dtype=np.float64))
                               if self.bones.get("ibm") is not None else None),
                "ibm_is_inverse_bind": (checks or {}).get("ibm_is_inverse_bind"),
                "ibm_det_range": ([(checks or {}).get("ibm_det_min"),
                                   (checks or {}).get("ibm_det_max")] if checks else None),
            },
            "weights": self.weight_summary(),
            "coordinate_system": {
                "space": "CP77 / REDengine",
                "up_axis": "Z",
                "handedness": "left",
                "unit": "meter",
                "gltf_mapping": "v_gltf = (x, z, -y)",
            },
            "units": {"length": "meter", "area": "square_meter", "volume": "cubic_meter"},
            "versions": {"schema": SCHEMA, "body_model": VERSION,
                         "builder": (checks or {}).get("builder")},
            "hashes": {"vertices": sha256_array(self.vertices),
                       "triangles": sha256_array(self.triangles),
                       "normals": sha256_array(self.normals)},
            "outputs": outputs or {},
            "quality_checks": (checks or {}).get("summary"),
        }


VERSION = "1.0.0"


def _hist(values: list[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


# ------------------------------------------------------------------ 载入
def load(prof: dict[str, Any], *, rig_json: Path | None = None,
         with_hierarchy: bool = True) -> BodyModel:
    """从档案解码出身形对象。数据源缺失会直接抛错（不允许占位）。"""
    src = P.require_source(prof)
    mesh_json = src["mesh_json"]
    geo = S.decode(mesh_json)

    positions, normals, tris, chunk_ids = [], [], [], []
    offset = 0
    for ch in geo["chunks"]:
        n = ch["vertex_count"]
        positions.append(np.asarray(ch["positions"], dtype=np.float64))
        nm = ch["normals"]
        normals.append(np.asarray(nm, dtype=np.float64) if nm else np.zeros((n, 3)))
        idx = np.asarray(ch["indices"], dtype=np.int64)
        # 绕序：CP77 与 glTF 相反（法线点积 -1，已实测）→ 交换第 2/3 顶点
        if idx.size % 3 == 0:
            idx = idx.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1)
        tris.append(idx + offset)
        chunk_ids.append(np.full(n, ch["index"], dtype=np.int32))
        offset += n

    vertices = np.vstack(positions) if positions else np.zeros((0, 3))
    normals_a = np.vstack(normals) if normals else np.zeros((0, 3))
    triangles = (np.concatenate(tris).reshape(-1, 3) if tris
                 else np.zeros((0, 3), dtype=np.int64))

    lengths = np.linalg.norm(normals_a, axis=1, keepdims=True)
    normals_a = np.divide(normals_a, lengths, out=np.zeros_like(normals_a),
                          where=lengths > 0)

    bones = {
        "names": list(geo["bone_names"]),
        "positions": np.asarray(geo["bone_positions"], dtype=np.float64),
        "ibm": np.asarray(geo["ibm_cp77"], dtype=np.float64),
    }

    hierarchy = None
    if with_hierarchy:
        rj = rig_json or P.resolve((prof.get("rig") or {}).get("rig_json"))
        if rj and Path(rj).is_file():
            from . import rig_hierarchy as RIG
            rig = RIG.load_rig(Path(rj))
            proj = RIG.project_to_mesh(rig, geo["bone_names"])
            hierarchy = {"type": "tree", "parents": proj["parents"],
                         "provenance": proj["provenance"]}

    model = BodyModel(
        body_id=prof["body_id"],
        profile=prof,
        geo=geo,
        vertices=vertices,
        normals=normals_a,
        triangles=triangles,
        chunk_of_vertex=np.concatenate(chunk_ids) if chunk_ids else np.zeros(0, dtype=np.int32),
        bones=bones,
        hierarchy=hierarchy,
        source_hashes={"mesh_json": sha256_file(mesh_json),
                       "raw_mesh": sha256_file(src["raw_mesh"])},
    )
    model.extra["source_paths"] = {k: str(v) for k, v in src.items() if k != "packs"}
    return model
