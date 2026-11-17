"""两个身形之间的表面对应（surface correspondence）。

为什么需要它：EBB 与 ANGEL 是两套不同的网格，**不能假设**
顶点数相同 / 索引一致 / 拓扑相同 / 骨骼索引一致。任何"按索引相减"都是错的。

本模块提供两条对应关系，并分别记录可核查的量化指标：
1. `nearest_vertex`：网格哈希 → 最近顶点，给出距离与法线夹角（快，用于粗筛）。
2. `nearest_triangle`：最近三角形质心 → 精确的点-三角形距离与最近点（默认使用）。

每个源顶点都会得到 `distance_m` / `normal_angle_deg` / `confidence` / `status`，
不可靠的标 `NEEDS_REVIEW`，不静默丢弃。

注意：这里得到的是**表面几何对应**，不是绑定/拓扑意义上的顶点对应；
两者的区别写在 `topology_report` 与 `confidence.definition` 里。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .body_model import BodyModel

VERSION = "1.0.0"


# ------------------------------------------------------------------ 网格加速
class _Grid:
    """均匀网格哈希（1~2cm 单元），比逐对求距离快几个量级。"""

    def __init__(self, points: np.ndarray, cell: float):
        self.cell = float(cell)
        self.points = points
        if points.size == 0:
            self.keys = np.zeros(0, dtype=np.int64)
            self.order = np.zeros(0, dtype=np.int64)
            self.buckets: dict[int, np.ndarray] = {}
            return
        ijk = np.floor(points / self.cell).astype(np.int64)
        ijk -= ijk.min(axis=0)
        dims = ijk.max(axis=0) + 1
        keys = (ijk[:, 0] * dims[1] + ijk[:, 1]) * dims[2] + ijk[:, 2]
        self.keys = keys
        self.dims = dims
        self.order = np.argsort(keys, kind="stable")
        sorted_keys = keys[self.order]
        uniq, starts = np.unique(sorted_keys, return_index=True)
        ends = np.append(starts[1:], len(sorted_keys))
        self.buckets = {int(k): self.order[s:e] for k, s, e in zip(uniq, starts, ends)}

    def _key(self, ijk: np.ndarray) -> np.ndarray:
        return (ijk[:, 0] * self.dims[1] + ijk[:, 1]) * self.dims[2] + ijk[:, 2]

    def query_ball(self, q: np.ndarray, rings: int = 1) -> list[np.ndarray]:
        """返回每个查询点附近若干单元内的候选索引列表。"""
        if self.points.size == 0:
            return [np.zeros(0, dtype=np.int64)] * len(q)
        # 建表时把所有 ijk 减去了 ijk.min()，查询也要做同样平移
        origin = np.floor(self.points / self.cell).astype(np.int64).min(axis=0)
        base = np.floor(q / self.cell).astype(np.int64) - origin
        out: list[np.ndarray] = []
        for b in base:
            parts = []
            for dx in range(-rings, rings + 1):
                for dy in range(-rings, rings + 1):
                    for dz in range(-rings, rings + 1):
                        k = (int(b[0]) + dx, int(b[1]) + dy, int(b[2]) + dz)
                        arr = self.buckets.get(
                            (k[0] * self.dims[1] + k[1]) * self.dims[2] + k[2])
                        if arr is not None:
                            parts.append(arr)
            out.append(np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64))
        return out


# ------------------------------------------------------- 点-三角形最近点
def point_triangle_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray,
                            c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """向量化：返回 (distance (n,), closest_point (n,3))。Ericson 算法。"""
    ab = b - a
    ac = c - a
    ap = p - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    n = p.shape[0]
    closest = np.empty_like(p)
    done = np.zeros(n, dtype=bool)

    # 顶点区域
    def assign(mask, point):
        sel = mask & ~done
        if sel.any():
            closest[sel] = point[sel] if point.ndim == 2 else point
            done[sel] = True

    assign((d1 <= 0) & (d2 <= 0), a)
    assign((d3 >= 0) & (d4 <= d3), b)
    assign((d6 >= 0) & (d5 <= d6), c)

    with np.errstate(divide="ignore", invalid="ignore"):
        denom_ab = np.where(np.abs(d1 - d3) < 1e-20, 1e-20, d1 - d3)
        v_ab = d1 / denom_ab
        assign((vc <= 0) & (d1 >= 0) & (d3 <= 0), a + v_ab[:, None] * ab)
        denom_ac = np.where(np.abs(d2 - d6) < 1e-20, 1e-20, d2 - d6)
        w_ac = d2 / denom_ac
        assign((vb <= 0) & (d2 >= 0) & (d6 <= 0), a + w_ac[:, None] * ac)
        denom_bc = np.where(np.abs((d4 - d3) + (d5 - d6)) < 1e-20, 1e-20, (d4 - d3) + (d5 - d6))
        w_bc = (d4 - d3) / denom_bc
        assign((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), b + w_bc[:, None] * (c - b))

        # 面内
        denom = va + vb + vc
        denom = np.where(np.abs(denom) < 1e-20, 1e-20, denom)
        v = vb / denom
        w = vc / denom
        sel = ~done
        if sel.any():
            closest[sel] = a[sel] + ab[sel] * v[sel, None] + ac[sel] * w[sel, None]
            done[sel] = True

    dist = np.linalg.norm(p - closest, axis=1)
    return dist, closest


# ------------------------------------------------------------------ 主流程
def topology_report(src: BodyModel, dst: BodyModel) -> dict[str, Any]:
    """明确写出「不能假设拓扑相同」的实测结论。"""
    sv, dv = src.vertex_count, dst.vertex_count
    st, dt = src.triangle_count, dst.triangle_count
    same_count = sv == dv
    tri_same = False
    if same_count and st == dt and st > 0:
        a = np.sort(src.triangles, axis=1)
        b = np.sort(dst.triangles, axis=1)
        tri_same = bool(np.array_equal(a, b))
    same_bones = False
    shared = 0
    s_names = list(src.bones.get("names") or [])
    d_names = list(dst.bones.get("names") or [])
    if s_names and d_names:
        shared = len(set(s_names) & set(d_names))
        same_bones = (s_names == d_names)
    return {
        "vertex_count": {"source": sv, "target": dv, "equal": same_count},
        "triangle_count": {"source": st, "target": dt, "equal": st == dt},
        "triangle_indices_identical": tri_same,
        "bone_name_lists_identical": same_bones,
        "bone_names_shared": shared,
        "conclusion": ("拓扑一致，可按索引直接对应" if (same_count and tri_same)
                       else "拓扑不一致（或未验证一致）→ 必须做表面对应，禁止按索引相减"),
    }


def match(src: BodyModel, dst: BodyModel, *,
          cell_m: float = 0.015, rings: int = 1,
          dist_tol_m: float | None = None,
          angle_tol_deg: float = 45.0,
          refine: bool = True,
          regions: dict[str, Any] | None = None,
          max_examples: int = 20,
          with_arrays: bool = False) -> dict[str, Any]:
    """计算 src 每个顶点到 dst 表面的最近点，并给出置信度与状态。"""
    if src.vertex_count == 0 or dst.vertex_count == 0:
        raise ValueError("源或目标网格为空，无法建立对应关系")

    sv, sn = src.vertices, src.normals
    dv = dst.vertices
    dt = dst.triangles
    if dt.size == 0:
        raise ValueError("目标网格没有三角形，无法做表面匹配")

    # 起点：最近顶点
    grid_v = _Grid(dv, cell_m)
    cand = grid_v.query_ball(sv, rings=rings)
    nv_idx = np.zeros(src.vertex_count, dtype=np.int64)
    nv_dist = np.full(src.vertex_count, np.inf)
    for i, c in enumerate(cand):
        if c.size == 0:
            continue
        d = np.linalg.norm(dv[c] - sv[i], axis=1)
        j = int(np.argmin(d))
        nv_idx[i] = c[j]
        nv_dist[i] = d[j]

    # 无法在邻域内找到候选的（半径不足）单独标出
    unmatched = ~np.isfinite(nv_dist)

    # 精确：最近三角形的点-三角形距离
    tri_centroids = dv[dt].mean(axis=1)
    tri_normals = np.cross(dv[dt[:, 1]] - dv[dt[:, 0]], dv[dt[:, 2]] - dv[dt[:, 0]])
    tn_len = np.linalg.norm(tri_normals, axis=1)
    tri_normals = np.divide(tri_normals, tn_len[:, None],
                            out=np.zeros_like(tri_normals), where=tn_len[:, None] > 0)

    if refine:
        grid_t = _Grid(tri_centroids, cell_m * 2)
        cand_t = grid_t.query_ball(sv, rings=1)
        tri_idx = np.full(src.vertex_count, -1, dtype=np.int64)
        for i, c in enumerate(cand_t):
            if c.size == 0:
                continue
            d = np.linalg.norm(tri_centroids[c] - sv[i], axis=1)
            tri_idx[i] = int(c[int(np.argmin(d))])
        sel = tri_idx >= 0
        surf_dist = np.full(src.vertex_count, np.inf)
        closest = np.zeros_like(sv)
        # 分块向量化，避免一次吃满内存
        idxs = np.nonzero(sel)[0]
        chunk = 8192
        for s in range(0, idxs.size, chunk):
            part = idxs[s:s + chunk]
            tri = dt[tri_idx[part]]
            d, cp = point_triangle_distance(sv[part], dv[tri[:, 0]], dv[tri[:, 1]],
                                            dv[tri[:, 2]])
            surf_dist[part] = d
            closest[part] = cp
        missing = ~np.isfinite(surf_dist)
        if missing.any():
            surf_dist[missing] = nv_dist[missing]
            closest[missing] = dv[nv_idx[missing]]
        tri_for_n = tri_idx
    else:
        surf_dist = nv_dist.copy()
        closest = dv[nv_idx]
        tri_for_n = np.full(src.vertex_count, -1, dtype=np.int64)

    # 法线夹角：源法线 vs 目标最近三角形法线（无三角形则用顶点法线）
    dst_normals = dst.normals
    tn = np.zeros_like(sv)
    has_tri = tri_for_n >= 0
    if has_tri.any():
        tn[has_tri] = tri_normals[tri_for_n[has_tri]]
    no_tri = ~has_tri
    if no_tri.any():
        tn[no_tri] = dst_normals[nv_idx[no_tri]]
    sn_norm = np.linalg.norm(sn, axis=1)
    tn_norm = np.linalg.norm(tn, axis=1)
    cosang = np.einsum("ij,ij->i", sn, tn)
    valid_n = (sn_norm > 0.5) & (tn_norm > 0.5)
    cosang = np.where(valid_n, cosang / np.where(valid_n, sn_norm * tn_norm, 1.0), 0.0)
    cosang = np.clip(cosang, -1.0, 1.0)
    angle_deg = np.degrees(np.arccos(cosang))

    # 容差：默认按目标网格局部尺度（中位边长）自适应
    if dist_tol_m is None:
        edges = np.linalg.norm(dv[dt[:, 1]] - dv[dt[:, 0]], axis=1)
        med_edge = float(np.median(edges)) if edges.size else 0.01
        dist_tol_m = max(0.004, 2.0 * med_edge)
    conf = np.clip(1.0 - surf_dist / max(dist_tol_m, 1e-9), 0.0, 1.0)
    conf = conf * (0.5 + 0.5 * np.maximum(0.0, cosang))
    # 法线夹角只在「距离非平凡」时作为判据：距离≈0 说明落点就是同一处表面，
    # 此时夹角大通常来自共面重复壳（正反两层），不应据此判为不可靠。
    near_identical = surf_dist <= 1e-3
    ok = (surf_dist <= dist_tol_m) & ((angle_deg <= angle_tol_deg) | near_identical) & ~unmatched
    status = np.where(ok, "OK", "NEEDS_REVIEW")

    finite = surf_dist[np.isfinite(surf_dist)]
    q = (np.percentile(finite, [50, 90, 95, 99]) if finite.size else [0, 0, 0, 0])
    summary = {
        "vertices": int(src.vertex_count),
        "matched": int(np.isfinite(surf_dist).sum()),
        "coverage": round(float(np.isfinite(surf_dist).sum() / src.vertex_count), 6),
        "distance_tol_m": round(float(dist_tol_m), 6),
        "angle_tol_deg": angle_tol_deg,
        "distance_m": {"mean": round(float(finite.mean()), 6) if finite.size else None,
                       "median": round(float(q[0]), 6),
                       "p90": round(float(q[1]), 6), "p95": round(float(q[2]), 6),
                       "p99": round(float(q[3]), 6),
                       "max": round(float(finite.max()), 6) if finite.size else None},
        "angle_deg": {"mean": round(float(np.mean(angle_deg)), 4),
                      "p95": round(float(np.percentile(angle_deg, 95)), 4),
                      "max": round(float(np.max(angle_deg)), 4)},
        "confidence": {"mean": round(float(np.mean(conf)), 6),
                       "median": round(float(np.median(conf)), 6)},
        "status": {"OK": int(ok.sum()), "NEEDS_REVIEW": int((~ok).sum())},
        "unmatched_no_candidate": int(unmatched.sum()),
    }

    # 分区域统计
    region_stats: dict[str, Any] = {}
    if regions:
        for name, reg in regions.items():
            band = reg.get("band") or {}
            lo, hi = band.get("z_lo"), band.get("z_hi")
            if lo is None:
                continue
            m = (src.vertices[:, 2] >= lo) & (src.vertices[:, 2] <= hi)
            if not m.any():
                region_stats[name] = {"vertices": 0}
                continue
            d_r = surf_dist[m]
            ok_r = ok[m]
            region_stats[name] = {
                "vertices": int(m.sum()),
                "distance_m_mean": round(float(np.nanmean(d_r)), 6),
                "distance_m_p95": round(float(np.nanpercentile(d_r, 95)), 6),
                "angle_deg_mean": round(float(np.mean(angle_deg[m])), 4),
                "ok_ratio": round(float(ok_r.mean()), 6),
                "status": ("OK" if ok_r.mean() >= 0.95 else "NEEDS_REVIEW"),
            }

    # 不可靠样例（供人工复核）
    bad_idx = np.nonzero(~ok)[0]
    order = bad_idx[np.argsort(-surf_dist[bad_idx])][:max_examples] if bad_idx.size else []
    examples = [{
        "vertex_index": int(i),
        "position": [round(float(x), 5) for x in sv[i]],
        "distance_m": round(float(surf_dist[i]), 6),
        "angle_deg": round(float(angle_deg[i]), 3),
        "confidence": round(float(conf[i]), 4),
        "status": str(status[i]),
    } for i in order]

    result = {
        "schema": "cp77.surface.correspondence/v1",
        "generator": f"automation/correspondence.py v{VERSION}",
        "source_body": src.body_id,
        "target_body": dst.body_id,
        "method": {
            "name": "nearest_triangle_by_centroid" if refine else "nearest_vertex",
            "cell_m": cell_m, "rings": rings, "refine": refine,
            "note": "点-三角形最近点（Ericson 算法），先按三角形质心做网格加速取候选。",
        },
        "topology_report": topology_report(src, dst),
        "confidence": {
            "definition": "confidence = clamp(1 - d/d_tol) * (0.5 + 0.5*max(0,cos θ))",
            "d_tol_m": round(float(dist_tol_m), 6),
            "angle_tol_deg": angle_tol_deg,
            "status_rule": ("d <= d_tol 且 (θ <= angle_tol 或 d <= 1mm) → OK，否则 NEEDS_REVIEW；"
                            "d<=1mm 时忽略夹角，避免共面重复壳被误判"),
            "meaning": "衡量「这个源顶点在目标表面上是否有可信落点」，不代表顶点索引对应",
        },
        "summary": summary,
        "regions": region_stats,
        "flagged_examples": examples,
        "histogram": {
            "distance_m": _histogram(finite, [0, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 1.0]),
            "angle_deg": _histogram(angle_deg, [0, 10, 20, 30, 45, 60, 90, 180]),
        },
    }
    if with_arrays:
        # 供差异场使用；不写进 JSON
        result["_arrays"] = {
            "distance": surf_dist, "angle_deg": angle_deg, "confidence": conf,
            "ok": ok, "closest": closest, "target_normal": tn,
        }
    return result


def _histogram(values: np.ndarray, edges: list[float]) -> dict[str, int]:
    out: dict[str, int] = {}
    if values.size == 0:
        return out
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        label = f"[{lo:g},{hi:g}{')' if i < len(edges) - 2 else ']'}"
        out[label] = int(((values >= lo) & (values < hi)).sum()
                         if i < len(edges) - 2 else ((values >= lo) & (values <= hi)).sum())
    return out


def self_check(model: BodyModel, **kwargs) -> dict[str, Any]:
    """同一模型自匹配：距离应≈0、角度≈0，用来验证匹配器本身没写错。"""
    return match(model, model, **kwargs)
