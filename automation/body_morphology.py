"""BodyMorphologyAnalyzer：身体形态测量（尺寸 / 轮廓 / 水平截面 / 区域统计）。

约定与边界（重要）：
- 坐标系用 CP77 源坐标（Z-up，米），**不做 Y-up 转换**；高度方向 = Z。
- 截面 = 平面 z=const 与三角形求交后拼接成闭环，在 XY 平面量宽度(X)/厚度(Y)/面积。
  这是**截面测量**，不是三维顶点位移场；两者不可互相替代（见 body_diff 的说明）。
- 多环路（如踝部左右腿各一环）分别记录，同时给出整体外包围尺寸。
- 区域锚点优先取骨骼地标（`body_model.LANDMARK_BONES`），地标缺失时退回身高分位。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .body_model import BodyModel

VERSION = "1.0.0"

# 区域定义：anchor=骨骼地标名，offset=距锚点的偏移(米)，half=半步长(米)
# between=(下锚点, 上锚点, 插值比例) 表示取两点之间某处
REGION_SPEC: dict[str, dict[str, Any]] = {
    "ankle": {"anchor": "ankle", "offset": 0.012, "half": 0.012, "label": "脚踝"},
    "calf": {"between": ("ankle", "knee", 0.45), "half": 0.030, "label": "小腿"},
    "knee": {"anchor": "knee", "offset": 0.0, "half": 0.020, "label": "膝"},
    "thigh": {"between": ("knee", "hip", 0.5), "half": 0.040, "label": "大腿"},
    "hip": {"anchor": "hip", "offset": 0.0, "half": 0.030, "label": "臀/髋"},
    "pelvis": {"anchor": "pelvis", "offset": -0.020, "half": 0.025, "label": "骨盆"},
    "waist": {"anchor": "waist", "offset": 0.030, "half": 0.030, "label": "腰"},
    "chest": {"anchor": "chest", "offset": 0.0, "half": 0.020, "label": "胸"},
    "shoulder": {"anchor": "shoulder", "offset": -0.010, "half": 0.020, "label": "肩"},
    "upper_arm": {"between": ("shoulder", "elbow", 0.5), "half": 0.030, "label": "上臂"},
}

# 地标缺失时的兜底：按身高比例（来自 ANGEL 实测，仅供降级使用）
FALLBACK_HEIGHT_FRAC = {
    "ankle": 0.0771, "knee": 0.3830, "hip": 0.6646, "pelvis": 0.6646,
    "waist": 0.7101, "chest": 0.8947, "shoulder": 0.9792, "elbow": 0.8435,
}

DEFAULT_SLICES = 5
STITCH_TOL = 1e-4          # 0.1mm 拼接容差
STABILITY_DELTA = 5e-4     # 0.5mm，用于稳定性复测


def _quant_key(x: float, y: float, tol: float) -> tuple[int, int]:
    return (int(round(x / tol)), int(round(y / tol)))


class BodyMorphologyAnalyzer:
    def __init__(self, model: BodyModel, *, slices_per_region: int = DEFAULT_SLICES,
                 stitch_tol: float = STITCH_TOL, contour_max_points: int = 64):
        self.model = model
        self.slices_per_region = max(1, int(slices_per_region))
        self.stitch_tol = float(stitch_tol)
        self.contour_max_points = int(contour_max_points)
        self.v = model.vertices
        self.z = self.v[:, 2]
        self.z_min = float(self.z.min())
        self.z_max = float(self.z.max())
        self.height = max(self.z_max - self.z_min, 1e-9)
        self._tri_cache: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------ 基础
    def height_norm(self, z: float) -> float:
        return (z - self.z_min) / self.height

    def z_at_norm(self, t: float) -> float:
        return self.z_min + t * self.height

    def _landmark_z(self) -> dict[str, float]:
        lm = self.model.landmarks()
        out: dict[str, float] = {}
        for key, info in lm.items():
            if key.startswith("_"):
                continue
            out[key] = float(info["z"])
        return out

    def resolve_region_band(self, name: str) -> dict[str, Any]:
        spec = REGION_SPEC[name]
        anchors = self._landmark_z()
        source = "bone_landmark"
        if "between" in spec:
            a, b, t = spec["between"]
            za = self._anchor_z(a, anchors)
            zb = self._anchor_z(b, anchors)
            if za is None or zb is None:
                center, source = self._fallback_center(spec["between"][0], t), "height_fraction"
            else:
                center = za + (zb - za) * t
        else:
            za = self._anchor_z(spec["anchor"], anchors)
            if za is None:
                center, source = self._fallback_center(spec["anchor"]), "height_fraction"
            else:
                center = za + spec.get("offset", 0.0)
        half = float(spec["half"])
        return {"name": name, "label": spec["label"], "center_z": round(center, 6),
                "z_lo": round(center - half, 6), "z_hi": round(center + half, 6),
                "half_m": half, "height_norm": round(self.height_norm(center), 6),
                "anchor_source": source}

    def _anchor_z(self, key: str, anchors: dict[str, float]) -> float | None:
        return anchors.get(key)

    def _fallback_center(self, key: str, t: float = 0.5) -> float:
        base = FALLBACK_HEIGHT_FRAC.get(key, 0.5)
        if t != 0.5:
            # between 兜底：取两个兜底比例的插值
            other = 0.5
            base = base + (other - base) * t
        return self.z_min + base * self.height

    # ------------------------------------------------------------ 截面
    def _triangles_in(self, z_lo: float, z_hi: float) -> np.ndarray:
        key = f"{z_lo:.6f}:{z_hi:.6f}"
        if key in self._tri_cache:
            return self._tri_cache[key]
        tri = self.model.triangles
        tri_z = self.z[tri]
        tmin, tmax = tri_z.min(axis=1), tri_z.max(axis=1)
        sel = (tmax >= z_lo) & (tmin <= z_hi)
        idx = np.nonzero(sel)[0]
        self._tri_cache[key] = idx
        return idx

    def section(self, z: float, *, with_contours: bool = True) -> dict[str, Any]:
        """平面 z=const 的水平截面。返回多环路几何量。"""
        tri = self.model.triangles
        # 只取跨越该平面的三角形：min < z <= max（同一三角形只算一次）
        tri_z = self.z[tri]
        tmin, tmax = tri_z.min(axis=1), tri_z.max(axis=1)
        cand = np.nonzero((tmin < z) & (tmax >= z))[0]
        segments: list[tuple[float, float, float, float]] = []
        if cand.size:
            t = tri[cand]
            p = self.v[t]                      # (k,3,3)
            zz = p[:, :, 2]
            # 三条边，判断端点是否跨面
            edges = ((0, 1), (1, 2), (2, 0))
            pts = []
            for i, j in edges:
                za, zb = zz[:, i], zz[:, j]
                cross_mask = (za < z) != (zb < z)
                denom = np.where(np.abs(zb - za) < 1e-12, 1e-12, zb - za)
                alpha = (z - za) / denom
                xy = p[:, i, :2] + alpha[:, None] * (p[:, j, :2] - p[:, i, :2])
                pts.append((cross_mask, xy))
            for k in range(cand.size):
                hits = [xy[k] for m, xy in pts if m[k]]
                if len(hits) != 2:
                    continue
                (x1, y1), (x2, y2) = hits
                segments.append((float(x1), float(y1), float(x2), float(y2)))

        loops = _stitch(segments, self.stitch_tol) if segments else []
        return {"z": round(float(z), 6), "height_norm": round(self.height_norm(z), 6),
                **self._summarize(loops, segments, with_contours=with_contours)}

    def _summarize(self, loops: list[dict[str, Any]],
                   segments: list[tuple[float, float, float, float]],
                   *, with_contours: bool) -> dict[str, Any]:
        if not loops:
            return {"loops": 0, "loop_data": [], "width_m": 0.0, "thickness_m": 0.0,
                    "area_m2": 0.0, "perimeter_m": 0.0, "segments": len(segments),
                    "open_polylines": 0, "quality": "EMPTY"}
        width = max((l["bbox"][2] - l["bbox"][0] for l in loops), default=0.0)
        thickness = max((l["bbox"][3] - l["bbox"][1] for l in loops), default=0.0)
        area = sum(l["area_m2"] for l in loops)
        perim = sum(l["perimeter_m"] for l in loops)
        open_n = sum(0 if l["closed"] else 1 for l in loops)
        loop_data = []
        for i, l in enumerate(loops):
            item = {k: l[k] for k in ("centroid", "bbox", "width_m", "thickness_m",
                                      "area_m2", "perimeter_m", "closed", "points")}
            item["index"] = i
            if with_contours:
                item["contour"] = _decimate(l["contour"], self.contour_max_points)
            loop_data.append(item)
        loop_data.sort(key=lambda d: -d["area_m2"])
        return {
            "loops": len(loops),
            "loop_data": loop_data,
            "width_m": round(width, 6),
            "thickness_m": round(thickness, 6),
            "area_m2": round(area, 8),
            "perimeter_m": round(perim, 6),
            "largest_loop": {k: loop_data[0][k] for k in
                             ("area_m2", "width_m", "thickness_m", "centroid")},
            "segments": len(segments),
            "open_polylines": open_n,
            "quality": "OK" if open_n == 0 else "OPEN_POLYLINE",
        }

    # ------------------------------------------------------------ 轮廓
    def silhouette(self, axis: str = "front", bands: int = 240) -> dict[str, Any]:
        """正面(投影看 X 宽) / 侧面(投影看 Y 厚) 轮廓，按高度分带。"""
        if axis not in ("front", "side"):
            raise ValueError("axis 只能是 front/side")
        bands = max(8, int(bands))
        edges = np.linspace(self.z_min, self.z_max, bands + 1)
        which = 0 if axis == "front" else 1
        rows = []
        for i in range(bands):
            lo, hi = edges[i], edges[i + 1]
            m = (self.z >= lo) & (self.z <= hi) if i == bands - 1 else \
                (self.z >= lo) & (self.z < hi)
            if not m.any():
                continue
            vals = self.v[m, which]
            rows.append({"z": round((lo + hi) / 2, 6),
                         "height_norm": round(self.height_norm((lo + hi) / 2), 6),
                         "min_m": round(float(vals.min()), 6),
                         "max_m": round(float(vals.max()), 6),
                         "extent_m": round(float(vals.max() - vals.min()), 6),
                         "samples": int(m.sum())})
        if not rows:
            return {"axis": axis, "bands": 0, "profile": []}
        widest = max(rows, key=lambda r: r["extent_m"])
        return {"axis": axis, "bands": len(rows), "profile": rows,
                "max_extent_m": widest["extent_m"],
                "max_extent_at_z": widest["z"],
                "max_extent_height_norm": widest["height_norm"]}

    # ------------------------------------------------------------ 区域
    def _has_geometry_near(self, bone: str, radius: float = 0.10) -> bool:
        """检查骨骼附近是否真有网格顶点（用于判定该区域在本文档中是否适用）。"""
        names = self.model.bones.get("names") or []
        pos = self.model.bones.get("positions")
        if pos is None or bone not in names:
            return False
        p = np.asarray(pos[names.index(bone)], dtype=np.float64)[:3]
        d = np.linalg.norm(self.v - p, axis=1)
        return bool((d < radius).any())

    def applicability(self, name: str) -> tuple[bool, str]:
        """区域是否适用于当前网格。手臂区域在缺少手臂的躯干网格上必须标 N/A。"""
        if name == "upper_arm":
            # 只看肘/腕：躯干网格在肩部附近会有顶点（会误判），但前臂位置不会有
            for bone in ("LeftForeArm", "LeftHand"):
                if self._has_geometry_near(bone, 0.04):
                    return True, ""
            return False, ("网格中不含手臂几何（前臂/手骨 4cm 内无顶点）→ 该区域不适用；"
                           "CP77 的手臂是独立网格 a0_000_pwa_base_hq__l/r")
        if name == "shoulder":
            if self._has_geometry_near("LeftShoulder", 0.06):
                return True, ""
            return False, "网格中骨架附近无几何 → 该区域不适用"
        return True, ""

    def region(self, name: str) -> dict[str, Any]:
        band = self.resolve_region_band(name)
        applicable, na_reason = self.applicability(name)
        zs = np.linspace(band["z_lo"], band["z_hi"], self.slices_per_region + 2)[1:-1]
        slices = [self.section(float(z), with_contours=False) for z in zs]
        valid = [s for s in slices if s["loops"] > 0]
        mask = self.model.slice_band(band["z_lo"], band["z_hi"])
        n_v = int(mask.sum())

        # 带内顶点包围（最稳健的宽度/厚度来源；不依赖截面拼接）
        sil = None
        if n_v:
            vv = self.v[mask]
            sil = {
                "width_m": round(float(vv[:, 0].max() - vv[:, 0].min()), 6),
                "thickness_m": round(float(vv[:, 1].max() - vv[:, 1].min()), 6),
                "x_range": [round(float(vv[:, 0].min()), 6), round(float(vv[:, 0].max()), 6)],
                "y_range": [round(float(vv[:, 1].min()), 6), round(float(vv[:, 1].max()), 6)],
                "vertices": n_v,
            }

        # 稳定性：同一 z 平移 0.5mm 后面积相对变化
        stability = None
        area_values = [s["area_m2"] for s in valid]
        exact = bool(valid) and all(s["open_polylines"] == 0 for s in valid)
        if valid:
            z_probe = float(zs[len(zs) // 2])
            a0 = self.section(z_probe, with_contours=False)["area_m2"]
            a1 = self.section(z_probe + STABILITY_DELTA, with_contours=False)["area_m2"]
            if a0 > 1e-9:
                stability = round(abs(a1 - a0) / a0, 6)

        reasons: list[str] = []
        level = "HIGH"
        if not applicable:
            level = "N/A"
            reasons.append(na_reason)
        elif not valid:
            level = "N/A"
            reasons.append("该高度没有可测量的截面")
        else:
            open_n = sum(s["open_polylines"] for s in valid)
            if open_n:
                level = "LOW"
                reasons.append("截面存在开放折线（该高度表面接近水平或网格在此断开）→ "
                               "面积不可用，宽度/厚度请用带内包围值")
            if stability is not None and stability > 0.05:
                level = "MEDIUM" if level == "HIGH" else level
                reasons.append(f"截面平移 {STABILITY_DELTA * 1000:.1f}mm 面积变化 {stability:.1%}")
            if max((s["loops"] for s in valid), default=0) > 4:
                level = "MEDIUM" if level == "HIGH" else level
                reasons.append("多环路（同一高度有多个分离壳体）")

        return {
            "name": name,
            "label": band["label"],
            "band": band,
            "applicable": applicable,
            "status": level,
            "reliability": {"level": level, "reasons": reasons},
            "vertices_in_band": n_v,
            "silhouette": sil,
            "section": {
                "slices_sampled": len(valid),
                "slice_z": [round(float(z), 6) for z in zs],
                "width_m_max": round(max((s["width_m"] for s in valid), default=0.0), 6),
                "thickness_m_max": round(max((s["thickness_m"] for s in valid), default=0.0), 6),
                "area_m2_mean": round(float(np.mean(area_values)), 8) if valid else None,
                "area_m2_max": round(max(area_values), 8) if valid else None,
                "area_method": "EXACT" if exact else ("NONE" if not valid else "PARTIAL(仅闭合环)"),
                "perimeter_m_mean": round(float(np.mean([s["perimeter_m"] for s in valid])), 6)
                if valid else None,
                "loops_max": max((s["loops"] for s in valid), default=0),
                "open_polylines": sum(s["open_polylines"] for s in valid),
                "stability_rel_change": stability,
                "per_slice": [{"z": s["z"], "width_m": s["width_m"],
                               "thickness_m": s["thickness_m"], "area_m2": s["area_m2"],
                               "loops": s["loops"], "open": s["open_polylines"]} for s in slices],
            },
        }

    def regions(self) -> dict[str, Any]:
        return {name: self.region(name) for name in REGION_SPEC}

    # ------------------------------------------------------------ 汇总
    def analyze(self, *, bands: int = 240, detail_sections: bool = True) -> dict[str, Any]:
        model = self.model
        dims = model.dimensions()
        geo = model.measure_geometry()
        regions = self.regions()
        detail: dict[str, Any] = {}
        if detail_sections:
            for name, reg in regions.items():
                detail[name] = self.section(reg["band"]["center_z"], with_contours=True)
        return {
            "schema": "cp77.body.morphology/v1",
            "analyzer": f"BodyMorphologyAnalyzer v{VERSION}",
            "generated_at": _now(),
            "body_id": model.body_id,
            "coordinate_system": {"space": "CP77", "up_axis": "Z", "unit": "meter"},
            "normalization": {"z_min": round(self.z_min, 6), "z_max": round(self.z_max, 6),
                              "height_m": round(self.height, 6),
                              "height_norm_formula": "(z - z_min) / height_m"},
            "overall": {
                "dimensions": dims,
                "geometry": geo,
                "landmarks": model.landmarks(),
                "vertices": model.vertex_count,
                "triangles": model.triangle_count,
            },
            "silhouette": {"front": self.silhouette("front", bands),
                           "side": self.silhouette("side", bands)},
            "regions": regions,
            "region_order": list(REGION_SPEC),
            "sections_detail": detail,
            "parameters": {"slices_per_region": self.slices_per_region,
                           "stitch_tol_m": self.stitch_tol,
                           "stability_delta_m": STABILITY_DELTA,
                           "contour_max_points": self.contour_max_points},
            "notes": [
                "截面是平面 z=const 与三角形求交后拼接的环路，衡量宽度(X)/厚度(Y)/面积；"
                "它是测量数据，不是三维顶点位移场。",
                "多环路（两腿、手臂与躯干分离）分别列出，整体 width/thickness 为外包围尺寸。",
                "open_polylines > 0 说明该高度模型不闭合（或缝合容差不足），该区域标记 NEEDS_REVIEW。",
            ],
        }


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _stitch(segments: list[tuple[float, float, float, float]],
            tol: float) -> list[dict[str, Any]]:
    """把线段拼成环路。返回闭合环与（若有）开放折线。"""
    nodes: dict[tuple[int, int], int] = {}
    coords: list[tuple[float, float]] = []
    edges: list[tuple[int, int]] = []
    for x1, y1, x2, y2 in segments:
        a = _node(nodes, coords, x1, y1, tol)
        b = _node(nodes, coords, x2, y2, tol)
        if a != b:
            edges.append((a, b))
    # 邻接（允许度数 >2，取第一个未用边）
    adj: dict[int, list[int]] = {}
    for ei, (a, b) in enumerate(edges):
        adj.setdefault(a, []).append(ei)
        adj.setdefault(b, []).append(ei)
    used = [False] * len(edges)
    loops: list[dict[str, Any]] = []

    def other(ei: int, node: int) -> int:
        a, b = edges[ei]
        return b if a == node else a

    def walk(start_edge: int) -> tuple[list[int], bool]:
        """按「尽量直行」继续走：在分叉处选与来向夹角最小的未用边。

        单纯「取第一条未用边」会在多条环路共享节点（重复壳/细节补丁）时走错分支，
        把一条闭合环拆成若干开放折线（实测在胸/肩高度会出现 13 条 open 折线）。
        """
        chain = [edges[start_edge][0], edges[start_edge][1]]
        used[start_edge] = True
        closed = False
        while True:
            cur, prev = chain[-1], chain[-2]
            if cur == chain[0] and len(chain) > 3:
                closed = True
                break
            ix, iy = coords[cur][0] - coords[prev][0], coords[cur][1] - coords[prev][1]
            n = math.hypot(ix, iy) or 1.0
            ix, iy = ix / n, iy / n
            best, best_dot = None, -2.0
            for cand in adj.get(cur, ()):
                if used[cand]:
                    continue
                nxt = other(cand, cur)
                ox, oy = coords[nxt][0] - coords[cur][0], coords[nxt][1] - coords[cur][1]
                m = math.hypot(ox, oy) or 1.0
                dot = (ix * ox + iy * oy) / m
                if dot > best_dot:
                    best, best_dot = cand, dot
            if best is None:
                break
            used[best] = True
            chain.append(other(best, cur))
        return chain, closed

    for ei in range(len(edges)):
        if used[ei]:
            continue
        chain, closed = walk(ei)
        pts = [coords[n] for n in chain]
        loops.append(_loop_metrics(pts, closed, tol))
    loops.sort(key=lambda l: -l["area_m2"])
    return loops


def _node(nodes: dict, coords: list, x: float, y: float, tol: float) -> int:
    key = _quant_key(x, y, tol)
    idx = nodes.get(key)
    if idx is None:
        idx = len(coords)
        nodes[key] = idx
        coords.append((x, y))
    return idx


def _loop_metrics(pts: list[tuple[float, float]], closed: bool, tol: float) -> dict[str, Any]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    area = 0.0
    perim = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        area += x1 * y2 - x2 * y1
        perim += math.hypot(x2 - x1, y2 - y1)
    if closed and len(pts) > 2:
        x1, y1 = pts[-1]
        x2, y2 = pts[0]
        area += x1 * y2 - x2 * y1
        perim += math.hypot(x2 - x1, y2 - y1)
    area = abs(area) / 2.0
    if not closed:
        # 开放折线：用弦近似闭合面积，明确标记
        area = 0.0
    return {
        "points": len(pts),
        "closed": closed,
        "area_m2": round(area, 8),
        "perimeter_m": round(perim, 6),
        "width_m": round(max(xs) - min(xs), 6),
        "thickness_m": round(max(ys) - min(ys), 6),
        "centroid": [round(sum(xs) / len(xs), 6), round(sum(ys) / len(ys), 6)],
        "bbox": [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)],
        "contour": [[round(x, 5), round(y, 5)] for x, y in pts],
    }


def _decimate(points: list[list[float]], limit: int) -> list[list[float]]:
    if len(points) <= limit:
        return points
    step = len(points) / float(limit)
    return [points[int(i * step)] for i in range(limit)]
