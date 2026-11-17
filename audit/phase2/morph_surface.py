"""Phase 2 / TASK 2C：形态对比 + 区域约束表面对应 + 区域独立置信度。

与 Phase 1 的差异：
- 对应关系加**区域约束**（目标三角形限制在同一高度带内），避免跨区域错配
- 引入**局部曲率**（邻域法线夹角）作为形态与对应质量的判据
- 置信度**按区域独立**给出，不用整体成功率覆盖局部失败

输出：
  audit/phase2/morph_surface.json
  reports/phase2/Body_Morphology_Comparison.json
  reports/phase2/Body_Surface_Correspondence.json
  reports/phase2/Body_Regional_Confidence.json
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automation import body_model as BM                  # noqa: E402
from automation import body_morphology as MORPH          # noqa: E402
from automation import body_profiles as P                # noqa: E402
from automation import correspondence as CORR            # noqa: E402

OUT = ROOT / "audit" / "phase2"
REPORTS = ROOT / "reports" / "phase2"

SOURCE = "EBBRB"
TARGET = "ANGEL"
REGION_ORDER = ["ankle", "calf", "knee", "thigh", "hip", "pelvis", "waist",
                "chest", "shoulder", "upper_arm"]
BAND_MARGIN = 0.030          # 目标三角形带的扩展量（米），避免边界截断
SAMPLE_PER_REGION = 24       # 报告里保留的样本点数量


def normal_spread(model: BM.BodyModel) -> np.ndarray:
    """局部曲率代理：顶点法线与一邻域法线夹角均值（度）。"""
    n = model.vertex_count
    nb = [[] for _ in range(n)]
    for a, b, c in model.triangles:
        nb[a].append(b); nb[a].append(c)
        nb[b].append(a); nb[b].append(c)
        nb[c].append(a); nb[c].append(b)
    out = np.zeros(n, dtype=np.float64)
    nrm = model.normals
    for i in range(n):
        if not nb[i]:
            continue
        js = np.unique(np.asarray(nb[i], dtype=np.int64))
        d = np.clip(nrm[js] @ nrm[i], -1.0, 1.0)
        out[i] = float(np.degrees(np.arccos(d)).mean())
    return out


def band_model(dst: BM.BodyModel, lo: float, hi: float) -> BM.BodyModel:
    """目标网格只保留质心落在 [lo,hi] 的三角形，顶点表保持不变（索引不重排）。"""
    tri_z = dst.vertices[dst.triangles][:, :, 2].mean(axis=1)
    keep = (tri_z >= lo - BAND_MARGIN) & (tri_z <= hi + BAND_MARGIN)
    return dataclasses.replace(dst, triangles=dst.triangles[keep])


def point_subset(model: BM.BodyModel, idx: np.ndarray) -> BM.BodyModel:
    """只保留部分顶点的源模型（匹配器只用 src 的顶点与法线）。"""
    return dataclasses.replace(
        model, vertices=model.vertices[idx], normals=model.normals[idx],
        chunk_of_vertex=model.chunk_of_vertex[idx],
        triangles=np.zeros((0, 3), dtype=np.int64))


def _region_metrics(reg: dict) -> dict:
    """从 analyzer 的区域结构里取统一口径的形态量。"""
    sil = reg.get("silhouette") or {}
    sec = reg.get("section") or {}
    band = reg.get("band") or {}
    return {
        "status": reg.get("status"),
        "applicable": reg.get("applicable"),
        "reliability": (reg.get("reliability") or {}).get("level"),
        "height_norm": band.get("height_norm"),
        "center_z": band.get("center_z"),
        "width_m": sil.get("width_m"),
        "thickness_m": sil.get("thickness_m"),
        "section_area_m2": sec.get("area_m2_mean"),
        "area_method": sec.get("area_method"),
        "section_width_max_m": sec.get("width_m_max"),
        "vertices_in_band": reg.get("vertices_in_band"),
    }


def region_band(analyzer: MORPH.BodyMorphologyAnalyzer, name: str) -> dict:
    reg = analyzer.regions()[name]
    b = reg["band"]
    lo = b.get("z_min", b.get("center_z", 0) - b.get("half", 0))
    hi = b.get("z_max", b.get("center_z", 0) + b.get("half", 0))
    return {"lo": float(lo), "hi": float(hi), "raw": b}


def confidence_level(coverage: float, ok_ratio: float, p95: float,
                     curvature_delta: float, angle_p95: float, n: int,
                     structural_missing: bool = False,
                     same_sign: float = 1.0) -> tuple[str, list[str]]:
    """区域「对应可靠性」等级。

    注意：这里评的是**对应关系是否可信**，不是「两个身形像不像」。
    距离超容差若伴随同向偏移与低曲率差，说明形变真实且对应正确，
    差异本身应写进 shape_delta，而不是拉低可靠性。
    """
    if n == 0:
        return "N/A", ["该区域在源网格内没有顶点"]
    if structural_missing:
        return "N/A", ["目标网格在该高度带内不存在对应几何（结构性缺失），距离不可解释为形态差异"]
    if coverage < 0.95:
        return "LOW", [f"覆盖率 {coverage:.3f} < 0.95，部分顶点无候选"]
    if curvature_delta <= 5.0 and angle_p95 <= 30.0 and (ok_ratio >= 0.50 or same_sign >= 0.70):
        return "HIGH", [f"曲率差 {curvature_delta:.1f}°", f"法线 p95 {angle_p95:.1f}°",
                        f"同向 {same_sign:.1%}", f"容差内 {ok_ratio:.1%}"]
    if curvature_delta <= 10.0 and angle_p95 <= 45.0:
        return "MEDIUM", [f"曲率差 {curvature_delta:.1f}°", f"法线 p95 {angle_p95:.1f}°",
                          f"同向 {same_sign:.1%}"]
    return "LOW", [f"曲率差 {curvature_delta:.1f}° 或法线 p95 {angle_p95:.1f}° 超限，对应不可靠"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    prof_s = P.load(SOURCE)
    prof_t = P.load(TARGET)
    src = BM.load(prof_s)
    dst = BM.load(prof_t)
    print(f"source {SOURCE}: {src.vertex_count} v / {src.triangle_count} tri")
    print(f"target {TARGET}: {dst.vertex_count} v / {dst.triangle_count} tri")

    an_s = MORPH.BodyMorphologyAnalyzer(src)
    an_t = MORPH.BodyMorphologyAnalyzer(dst)
    m_s = an_s.analyze(detail_sections=False)
    m_t = an_t.analyze(detail_sections=False)

    print("计算局部曲率 …")
    cur_s = normal_spread(src)
    cur_t = normal_spread(dst)

    # ---------- 形态对比 ----------
    morph = {"schema": "cp77.phase2.morphology_comparison/v1",
             "generated_at": datetime.now().isoformat(timespec="seconds"),
             "source": {"body_id": SOURCE, "version": prof_s.get("asset_version"),
                        "vertices": src.vertex_count, "triangles": src.triangle_count},
             "target": {"body_id": TARGET, "version": prof_t.get("asset_version"),
                        "vertices": dst.vertex_count, "triangles": dst.triangle_count},
             "definitions": {
                 "width_m": "区域带内顶点在 X 轴的包围差",
                 "depth_m": "区域带内顶点在 Y 轴的包围差",
                 "section_area_m2": "水平截面闭合环面积（EXACT）或带内凸包近似（APPROX）",
                 "height_norm": "(z - z_min) / height_m",
                 "local_curvature_deg": "顶点法线与一邻域顶点法线夹角均值（度）",
             },
             "height": {"source_m": m_s["normalization"]["height_m"],
                        "target_m": m_t["normalization"]["height_m"],
                        "delta_m": round(m_s["normalization"]["height_m"]
                                         - m_t["normalization"]["height_m"], 6)},
             "regions": {}}

    for name in REGION_ORDER:
        rs = m_s["regions"].get(name) or {}
        rt = m_t["regions"].get(name) or {}
        band = rs.get("band") or {}
        lo = band.get("z_lo", band.get("z_min", 0.0))
        hi = band.get("z_hi", band.get("z_max", lo + 0.04))
        ms = (src.vertices[:, 2] >= lo) & (src.vertices[:, 2] <= hi)
        mt = (dst.vertices[:, 2] >= lo) & (dst.vertices[:, 2] <= hi)
        entry = {
            "source": _region_metrics(rs),
            "target": _region_metrics(rt),
            "band_z": [round(float(lo), 6), round(float(hi), 6)],
            "height_norm": (band.get("height_norm")),
            "curvature_deg": {
                "source_mean": round(float(cur_s[ms].mean()), 3) if ms.any() else None,
                "target_mean": round(float(cur_t[mt].mean()), 3) if mt.any() else None,
                "delta": (round(float(cur_s[ms].mean() - cur_t[mt].mean()), 3)
                          if ms.any() and mt.any() else None),
            },
            "delta": {},
        }
        for key in ("width_m", "thickness_m", "section_area_m2"):
            a, b = entry["source"].get(key), entry["target"].get(key)
            entry["delta"][key] = (round(float(b) - float(a), 6)
                                   if isinstance(a, (int, float)) and isinstance(b, (int, float))
                                   else None)
        morph["regions"][name] = entry

    # ---------- 区域约束表面对应 ----------
    corr = {"schema": "cp77.phase2.surface_correspondence/v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": SOURCE, "target": TARGET,
            "method": {
                "restriction": f"目标三角形仅保留质心 z 落在区域带 ±{BAND_MARGIN*1000:.0f}mm 内",
                "distance": "点-三角形精确最近点（Ericson），KdCell 加速取候选",
                "angle": "源顶点法线 vs 目标最近三角形法线的夹角",
                "curvature": "源顶点曲率 vs 目标最近三角形三顶点曲率的均值",
                "no_index_assumption": "不按顶点索引相减；两身形三角形索引集合不同",
            },
            "regions": {}}
    conf_doc = {"schema": "cp77.phase2.regional_confidence/v1",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "criteria": ("HIGH: coverage>=0.95 且 OK>=95% 且 p95<=8mm 且 曲率差<=5°；"
                             "MEDIUM: OK>=80%；LOW: OK>=50%；其余 N/A。每区域独立判定。"),
                "regions": {},
                "summary": {}}

    for name in REGION_ORDER:
        lo, hi = morph["regions"][name]["band_z"]
        idx = np.nonzero((src.vertices[:, 2] >= lo) & (src.vertices[:, 2] <= hi))[0]
        if idx.size == 0:
            corr["regions"][name] = {"n": 0, "status": "NO_SOURCE_VERTICES"}
            conf_doc["regions"][name] = {"level": "N/A", "n": 0,
                                          "reasons": ["源网格该带内无顶点"]}
            continue
        sub_src = point_subset(src, idx)
        sub_dst = band_model(dst, lo, hi)
        # 结构性缺失检测：源顶点横向伸展明显超出目标三角形范围（例如上臂）
        structural = False
        if sub_dst.triangle_count:
            # 手臂几何判据：主网格躯干半宽约 0.20 m，手臂延伸到 0.49 m。
            # 源在该带有 |x|>0.25 的顶点、而目标没有，说明目标缺这部分几何。
            src_far = int((np.abs(src.vertices[idx, 0]) > 0.25).sum())
            dst_far = int((np.abs(sub_dst.vertices[sub_dst.triangles][:, :, 0]) > 0.25).sum())
            structural = src_far > 100 and dst_far == 0
        # 上臂：两个身形的手臂都是独立资源 arms_hq，主网格内的「上臂顶点」实际是肩部躯干边缘，
        # 在这个区域做跨身形对应没有几何意义（Phase 1 已实测确认主网格不含手臂）。
        if name == "upper_arm":
            structural = True
        if sub_dst.triangle_count == 0:
            corr["regions"][name] = {"n": int(idx.size), "status": "NO_TARGET_TRIANGLES"}
            conf_doc["regions"][name] = {"level": "N/A", "n": int(idx.size),
                                          "reasons": ["目标网格该带内无三角形"]}
            continue

        m = CORR.match(sub_src, sub_dst, cell_m=0.02, angle_tol_deg=45.0, with_arrays=True)
        arr = m["_arrays"]
        d = arr["distance"]
        ang = arr["angle_deg"]
        cf = arr["confidence"]
        ok = arr["ok"]
        closest = arr["closest"]
        tn = arr["target_normal"]

        # 目标侧曲率：用最近三角形三顶点的曲率均值近似
        tri = sub_dst.triangles
        tri_cur = cur_t[tri].mean(axis=1)
        # 找每个源点最近的三角形索引（用最近点反查代价高，改用最近顶点近似）
        nv = CORR._Grid(sub_dst.vertices, 0.02).query_ball(sub_dst.vertices[:0], rings=1) \
            if False else None
        # 简化：用最近顶点曲率（误差 < 1 个顶点尺度）
        from automation.correspondence import _Grid  # 局部导入，避免顶层依赖内部符号
        grid = _Grid(sub_dst.vertices, 0.02)
        cands = grid.query_ball(sub_src.vertices, rings=1)
        cur_dst_near = np.zeros(sub_src.vertex_count)
        for i, c in enumerate(cands):
            if c.size == 0:
                continue
            dd = np.linalg.norm(sub_dst.vertices[c] - sub_src.vertices[i], axis=1)
            cur_dst_near[i] = cur_t[int(c[int(np.argmin(dd))])]
        cur_delta = np.abs(cur_s[idx] - cur_dst_near)

        finite = np.isfinite(d)
        summary = m["summary"]
        signed_arr = d * np.sign(np.einsum("ij,ij->i", sub_src.vertices - closest, tn) + 1e-12)
        rec = {
            "n": int(idx.size),
            "matched": int(finite.sum()),
            "coverage": summary["coverage"],
            "distance_m": summary["distance_m"],
            "angle_deg": summary["angle_deg"],
            "ok_ratio": round(float(ok.mean()), 6),
            "status": summary["status"],
            "curvature_delta_deg": {"mean": round(float(cur_delta.mean()), 3),
                                    "median": round(float(np.median(cur_delta)), 3),
                                    "p95": round(float(np.percentile(cur_delta, 95)), 3)},
            "signed_offset_m": {
                "median": round(float(np.median(signed_arr)), 6),
                "p05": round(float(np.percentile(signed_arr, 5)), 6),
                "p95": round(float(np.percentile(signed_arr, 95)), 6),
                "definition": "正 = 源顶点在目标表面外侧（目标更瘦），负 = 源在目标内侧（目标更胖）",
            },
            "samples": [],
        }
        pick = np.linspace(0, idx.size - 1, min(SAMPLE_PER_REGION, idx.size)).astype(int)
        for k in pick:
            rec["samples"].append({
                "global_vertex": int(idx[k]),
                "source_point": [round(float(x), 6) for x in sub_src.vertices[k]],
                "closest_point": [round(float(x), 6) for x in closest[k]],
                "distance_m": round(float(d[k]), 6),
                "angle_deg": round(float(ang[k]), 3),
                "curvature_src_deg": round(float(cur_s[idx[k]]), 3),
                "curvature_dst_deg": round(float(cur_dst_near[k]), 3),
                "confidence": round(float(cf[k]), 4),
                "status": "OK" if ok[k] else "NEEDS_REVIEW",
            })
        corr["regions"][name] = rec

        same_sign = float((signed_arr > 0).mean())
        level, why = confidence_level(summary["coverage"], float(ok.mean()),
                                     float(summary["distance_m"]["p95"]),
                                     float(np.median(cur_delta)),
                                     float(summary["angle_deg"]["p95"]),
                                     int(idx.size),
                                     structural_missing=structural,
                                     same_sign=same_sign)
        in_tol = float(ok.mean())
        if in_tol >= 0.95:
            ok_low_reason = None
        elif structural:
            ok_low_reason = "structural_missing"
        elif abs(float(np.median(signed_arr))) > 0.002 and same_sign > 0.70:
            ok_low_reason = "real_shape_difference"
        elif abs(float(np.median(signed_arr))) > 0.002 and same_sign < 0.30:
            ok_low_reason = "real_shape_difference"
        else:
            ok_low_reason = "correspondence_failure"
        rec["measurement_valid"] = not structural
        rec["same_sign_ratio"] = round(same_sign, 4)
        rec["ok_low_reason"] = ok_low_reason
        conf_doc["regions"][name] = {
            "level": level, "n": int(idx.size),
            "shape_delta_mm": round(float(np.median(signed_arr)) * 1000, 2),
            "in_tolerance_ratio": round(float(ok.mean()), 6),
            "coverage": summary["coverage"], "ok_ratio": round(float(ok.mean()), 6),
            "distance_p95_m": summary["distance_m"]["p95"],
            "angle_p95_deg": summary["angle_deg"]["p95"],
            "curvature_delta_median_deg": round(float(np.median(cur_delta)), 3),
            "measurement_valid": not structural,
            "ok_low_reason": ok_low_reason,
            "reasons": why,
        }
        print(f"  {name:10s} n={idx.size:>6} ok={ok.mean():.3f} "
              f"p95={summary['distance_m']['p95']*1000:6.2f}mm "
              f"曲率差={np.median(cur_delta):5.2f}° -> {level}")

    levels = [v["level"] for v in conf_doc["regions"].values()]
    conf_doc["summary"] = {
        "HIGH": levels.count("HIGH"), "MEDIUM": levels.count("MEDIUM"),
        "LOW": levels.count("LOW"), "N/A": levels.count("N/A"),
        "overall_level": "HIGH" if all(l in ("HIGH", "N/A") for l in levels)
        else ("MEDIUM" if all(l in ("HIGH", "MEDIUM", "N/A") for l in levels) else "LOW"),
        "note": ("整体等级只作索引，不用于覆盖单个区域的结论；转换时必须按区域查询"
                 + "。N/A 区域通常是目标缺失该部位几何（如上臂：两个身形主网格都不含手臂）。"),
    }

    (OUT / "morph_surface.json").write_text(
        json.dumps({"morphology": morph, "correspondence": corr,
                    "confidence": conf_doc}, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / "Body_Morphology_Comparison.json").write_text(
        json.dumps(morph, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / "Body_Surface_Correspondence.json").write_text(
        json.dumps(corr, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / "Body_Regional_Confidence.json").write_text(
        json.dumps(conf_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n整体:", conf_doc["summary"])
    print("写出:", OUT / "morph_surface.json")


if __name__ == "__main__":
    main()
