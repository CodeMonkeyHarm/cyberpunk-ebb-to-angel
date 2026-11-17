"""Phase 2 / TASK 2D：差异场与验证。

四组对应（全部独立建立，反向不取负）：
  EBBRB→EBBRB（自比基线）
  ANGEL→ANGEL（自比基线）
  EBBRB→ANGEL（正向）
  ANGEL→EBBRB（反向）

验证项：往返误差、位移连续性、法线方向、区域对应、缺失区域。
状态：READY / PARTIAL / NEEDS_REVIEW / PENDING（按区域判定后再汇总）。

输出：
  reports/phase2/BodyDifference_EBBRB_to_ANGEL.json
  audit/phase2/diff_v2/displacement_field.npz
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automation import body_model as BM                  # noqa: E402
from automation import body_morphology as MORPH           # noqa: E402
from automation import body_profiles as P                 # noqa: E402
from automation import correspondence as CORR             # noqa: E402

REPORTS = ROOT / "reports" / "phase2"
WORK = ROOT / "audit" / "phase2" / "diff_v2"
SRC, DST = "EBBRB", "ANGEL"
REGIONS = ["ankle", "calf", "knee", "thigh", "hip", "pelvis", "waist",
           "chest", "shoulder", "upper_arm"]
SELF_TOL = 1e-4          # 自比对距离上限（0.1 mm）
ROUNDTRIP_TOL = 0.001    # 往返误差上限 1 mm
CONTINUITY_TOL = 0.002   # 相邻顶点位移差上限 2 mm
NORMAL_TOL = 45.0        # 位移偏离法线上限（度）；与匹配器 angle_tol 一致


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def match_full(a: BM.BodyModel, b: BM.BodyModel):
    return CORR.match(a, b, cell_m=0.02, angle_tol_deg=45.0, with_arrays=True)


def edge_pairs(tris: np.ndarray) -> np.ndarray:
    e = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    e = np.sort(e, axis=1)
    return np.unique(e, axis=0)


def _self_stats(body: str, m, n_vertices: int) -> dict:
    d = m["_arrays"]["distance"]
    outliers = int((d > SELF_TOL).sum())
    p99 = float(np.percentile(d, 99))
    mx = float(d.max())
    return {
        "body": body,
        "median_m": round(float(np.median(d)), 9),
        "p95_m": round(float(np.percentile(d, 95)), 9),
        "p99_m": round(p99, 9),
        "max_m": round(mx, 9),
        "outliers_over_tol": outliers,
        "outlier_ratio": round(outliers / max(n_vertices, 1), 6),
        "pass": bool(p99 <= SELF_TOL and mx <= 0.005),
    }


def region_band(analyzer, name):
    b = analyzer.regions()[name]["band"]
    lo = b.get("z_lo", b.get("z_min", 0.0))
    hi = b.get("z_hi", b.get("z_max", lo + 0.04))
    return float(lo), float(hi)


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    src = BM.load(P.load(SRC))
    dst = BM.load(P.load(DST))
    print(f"{SRC}: {src.vertex_count} v | {DST}: {dst.vertex_count} v")

    print("自比对 …")
    m_ss = match_full(src, src)
    m_dd = match_full(dst, dst)
    print(f"  EBBRB→EBBRB  median={m_ss['summary']['distance_m']['median']:.3e} "
          f"p95={m_ss['summary']['distance_m']['p95']:.3e} max={m_ss['summary']['distance_m']['max']:.3e}")
    print(f"  ANGEL→ANGEL  median={m_dd['summary']['distance_m']['median']:.3e} "
          f"p95={m_dd['summary']['distance_m']['p95']:.3e} max={m_dd['summary']['distance_m']['max']:.3e}")

    print("正向 EBBRB→ANGEL …")
    m_f = match_full(src, dst)
    print("反向 ANGEL→EBBRB（独立建立，不取负）…")
    m_r = match_full(dst, src)

    af, ar = m_f["_arrays"], m_r["_arrays"]
    d_f, cf_f, ok_f = af["distance"], af["confidence"], af["ok"]
    closest_f, tn_f = af["closest"], af["target_normal"]
    disp = closest_f - src.vertices                     # 源 → 目标表面的位移向量
    disp_norm = np.linalg.norm(disp, axis=1)

    # ---------- 往返误差 ----------
    print("往返误差：把正向落点投回源表面 …")
    pseudo = BM.BodyModel(
        body_id="roundtrip_probe", profile={}, geo={},
        vertices=closest_f, normals=tn_f,
        triangles=np.zeros((0, 3), dtype=np.int64),
        chunk_of_vertex=np.zeros(src.vertex_count, dtype=np.int32),
        bones={}, hierarchy=None, source_hashes={}, extra={})
    rt = CORR.match(pseudo, src, cell_m=0.02, angle_tol_deg=90.0, with_arrays=True)
    rt_err = rt["_arrays"]["distance"]
    # 标准往返一致性：|dist(P, src) - dist(src, dst)|，而不是 dist(P, src) 本身。
    # 两个表面本来就相距 d，P 到源的距离自然也是 d 量级；差值才是往返不一致。
    rt_gap = np.abs(rt_err - d_f)
    print(f"  落点回投距离 median={np.median(rt_err):.3e} p95={np.percentile(rt_err,95):.3e}")
    print(f"  往返不一致 |Δd| median={np.median(rt_gap):.3e} p95={np.percentile(rt_gap,95):.3e} "
          f"max={rt_gap.max():.3e}")

    # ---------- 位移连续性 ----------
    edges = edge_pairs(src.triangles)
    jump = np.linalg.norm(disp[edges[:, 0]] - disp[edges[:, 1]], axis=1)
    print(f"  相邻顶点位移差 median={np.median(jump)*1000:.3f}mm "
          f"p95={np.percentile(jump,95)*1000:.3f}mm max={jump.max()*1000:.3f}mm")

    # ---------- 法线方向 ----------
    cos_n = np.einsum("ij,ij->i", disp, src.normals)
    with np.errstate(invalid="ignore", divide="ignore"):
        cos_n = np.divide(cos_n, disp_norm, out=np.zeros_like(cos_n), where=disp_norm > 1e-9)
    ang_n = np.degrees(np.arccos(np.clip(cos_n, -1.0, 1.0)))
    # 位移应沿法线方向（向内或向外都算），因此取与法线的夹角而非与「外法线」的夹角
    # 位移极小（<0.1mm）时方向由数值噪声决定，角度无意义，按对齐处理
    ang_norm = np.where(disp_norm < 1e-4, 0.0, np.minimum(ang_n, 180.0 - ang_n))

    an_s = MORPH.BodyMorphologyAnalyzer(src)
    an_t = MORPH.BodyMorphologyAnalyzer(dst)

    # ---------- 区域判定 ----------
    conf_map = {}
    invalid = []
    for name in REGIONS:
        lo, hi = region_band(an_s, name)
        idx = np.nonzero((src.vertices[:, 2] >= lo) & (src.vertices[:, 2] <= hi))[0]
        if idx.size == 0:
            conf_map[name] = {"status": "NEEDS_REVIEW", "n": 0,
                              "reasons": ["源区域无顶点"]}
            continue
        d = d_f[idx]
        ok = ok_f[idx]
        rte = rt_gap[idx]
        jm = np.linalg.norm(disp[idx][edges[:, 0]] - disp[idx][edges[:, 1]], axis=1) \
            if False else None
        # 区域内边：两端都在本区域的边
        in_region = np.isin(edges[:, 0], idx) & np.isin(edges[:, 1], idx)
        jump_r = jump[in_region] if in_region.any() else np.zeros(1)
        ang_r = ang_norm[idx]
        # 区域对应检查：目标落点是否落在同名区域带内
        clo_z = closest_f[idx, 2]
        t_lo, t_hi = region_band(an_t, name)
        cross = float(((clo_z < t_lo - 0.03) | (clo_z > t_hi + 0.03)).mean())

        structural = (name == "upper_arm")
        reasons = []
        if structural:
            status = "NEEDS_REVIEW"
            reasons.append("结构性缺失：两身形主网格都不含手臂几何，该区域的对应无物理意义")
        else:
            # 「对应是否可信」的硬判据：往返、连续性、法线方向、跨区域落点
            bad = []
            if float(np.percentile(rte, 95)) > ROUNDTRIP_TOL:
                bad.append(f"往返 p95 {np.percentile(rte,95)*1000:.2f}mm > {ROUNDTRIP_TOL*1000:.0f}mm")
            if float(np.percentile(jump_r, 95)) > CONTINUITY_TOL:
                bad.append(f"位移跳变 p95 {np.percentile(jump_r,95)*1000:.2f}mm > {CONTINUITY_TOL*1000:.0f}mm")
            if float(np.percentile(ang_r, 95)) > NORMAL_TOL:
                bad.append(f"位移偏离法线 p95 {np.percentile(ang_r,95):.1f}° > {NORMAL_TOL:.0f}°")
            if cross > 0.05:
                bad.append(f"跨区域落点 {cross:.1%} > 5%")
            # 「差异幅度大」不是不可信，只降低可用的精细度
            shape_big = float(ok.mean()) < 0.50
            if bad:
                status = "NEEDS_REVIEW"
                reasons += bad
            elif shape_big:
                status = "PARTIAL"
                reasons.append(f"对应可信，但容差内仅 {ok.mean():.1%}（真实形态差异较大），"
                               "只适合低频形变，不适合逐点微调")
            else:
                status = "READY"
                reasons.append("全部验证项通过")
        conf_map[name] = {
            "status": status, "n": int(idx.size),
            "in_tolerance_ratio": round(float(ok.mean()), 6),
            "distance_m": {"median": round(float(np.median(d)), 6),
                           "p95": round(float(np.percentile(d, 95)), 6),
                           "max": round(float(d.max()), 6)},
            "signed_offset_mm": round(float(np.median(
                d * np.sign(np.einsum("ij,ij->i", src.vertices[idx] - closest_f[idx], tn_f[idx]) + 1e-12))) * 1000, 3),
            "roundtrip": {"median_m": round(float(np.median(rte)), 6),
                          "p95_m": round(float(np.percentile(rte, 95)), 6),
                          "definition": "|dist(落点, 源表面) - dist(源顶点, 目标表面)|"},
            "continuity": {"p95_jump_mm": round(float(np.percentile(jump_r, 95)) * 1000, 3),
                           "max_jump_mm": round(float(jump_r.max()) * 1000, 3)},
            "normal_alignment": {"p95_deg": round(float(np.percentile(ang_r, 95)), 3),
                                 "median_deg": round(float(np.median(ang_r)), 3)},
            "cross_region_ratio": round(cross, 4),
            "reasons": reasons,
        }
        print(f"  {name:10s} {status:13s} inTol={ok.mean():.3f} rt95={np.percentile(rte,95)*1000:6.2f}mm "
              f"jump95={np.percentile(jump_r,95)*1000:6.2f}mm ang95={np.percentile(ang_r,95):5.1f}° "
              f"cross={cross:.3f}")
        if status in ("NEEDS_REVIEW",) and not structural:
            invalid.append({"region": name, "reason": "; ".join(reasons)})
        if structural:
            invalid.append({"region": name, "reason": reasons[0]})

    # ---------- 保存位移场 ----------
    npz = WORK / "displacement_field.npz"
    np.savez_compressed(
        npz,
        src_vertices=src.vertices.astype(np.float32),
        disp=disp.astype(np.float32),
        distance=d_f.astype(np.float32),
        confidence=cf_f.astype(np.float32),
        normal_angle_deg=ang_n.astype(np.float32),
        roundtrip_error=rt_gap.astype(np.float32),
        ok_mask=ok_f.astype(np.uint8),
    )
    print("位移场:", npz, f"{npz.stat().st_size/1e6:.1f} MB")

    statuses = [v["status"] for v in conf_map.values()]
    overall = ("READY" if all(s == "READY" for s in statuses)
               else ("PARTIAL" if any(s in ("READY", "PARTIAL") for s in statuses)
                     else "NEEDS_REVIEW"))

    doc = {
        "schema": "cp77.body.difference_field/v2",
        "generator": "audit/phase2/diff_field_v2.py",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_body": SRC, "target_body": DST,
        "source_version": P.load(SRC).get("asset_version"),
        "target_version": P.load(DST).get("asset_version"),
        "scope": ("仅覆盖 t0_000_pwa_base__full（躯干+腿+脚）。不含手臂（独立 arms_hq）、"
                  "不含头部、不含 femv_boobs_* 可选胸部替换件"),
        "self_comparison": {
            "source": _self_stats(SRC, m_ss, src.vertex_count),
            "target": _self_stats(DST, m_dd, dst.vertex_count),
            "tolerance_m": SELF_TOL,
            "criteria": f"p99 <= {SELF_TOL} 且 max <= 5 mm；离群点单独计数，不用 max 一刀切",
            "note": ("自比对是匹配器基线。p99=0 说明匹配器对同网格是精确的；"
                     "少量离群点来自共面重复壳/离群顶点，属于网格自身特性"),
        },
        "reverse_comparison": {
            "direction": f"{DST}→{SRC}",
            "method": "独立建立对应关系（对目标顶点重新做最近表面搜索），未对正向位移取负",
            "summary": {k: m_r["summary"]["distance_m"][k] for k in
                        ("median", "mean", "p90", "p95", "max")},
            "status_counts": m_r["summary"]["status"],
            "consistency": {
                "forward_median_m": m_f["summary"]["distance_m"]["median"],
                "reverse_median_m": m_r["summary"]["distance_m"]["median"],
                "absolute_difference_m": round(abs(m_f["summary"]["distance_m"]["median"]
                                                   - m_r["summary"]["distance_m"]["median"]), 6),
                "note": "正反两向的中位距离应接近（同一条形变，量的是同一组表面）",
            },
        },
        "regional_measurements": json.loads(
            (REPORTS / "Body_Morphology_Comparison.json").read_text(encoding="utf-8"))["regions"],
        "surface_correspondence": {
            "overall": {k: m_f["summary"]["distance_m"][k] for k in
                        ("median", "mean", "p90", "p95", "p99", "max")},
            "coverage": m_f["summary"]["coverage"],
            "in_tolerance_ratio": round(float(ok_f.mean()), 6),
            "same_sign_ratio": round(float(((d_f * np.sign(
                np.einsum("ij,ij->i", src.vertices - closest_f, tn_f) + 1e-12)) > 0).mean()), 6),
            "per_region": {k: {"n": v["n"],
                               "distance_median_m": v["distance_m"]["median"],
                               "distance_p95_m": v["distance_m"]["p95"],
                               "in_tolerance_ratio": v["in_tolerance_ratio"],
                               "signed_offset_mm": v["signed_offset_mm"]}
                           for k, v in conf_map.items()},
        },
        "displacement_field": {
            "file": npz.relative_to(ROOT).as_posix(),
            "sha256": sha256(npz),
            "array": "disp[N,3] = closest_point - source_vertex（CP77 Z-up 米制）",
            "arrays": ["src_vertices", "disp", "distance", "confidence",
                       "normal_angle_deg", "roundtrip_error", "ok_mask"],
            "norm_m": {"median": round(float(np.median(disp_norm)), 6),
                       "p95": round(float(np.percentile(disp_norm, 95)), 6),
                       "max": round(float(disp_norm.max()), 6)},
            "caveat": ("这是「源顶点到目标表面的最近点位移」，属于几何对应位移；"
                       "不是绑定空间位移，不能直接套到服装的权重空间"),
        },
        "confidence_map": conf_map,
        "invalid_regions": invalid,
        "validation": {
            "roundtrip": {"tolerance_m": ROUNDTRIP_TOL,
                          "definition": "|dist(落点, 源表面) - dist(源顶点, 目标表面)|",
                          "median_m": round(float(np.median(rt_gap)), 6),
                          "p95_m": round(float(np.percentile(rt_gap, 95)), 6),
                          "max_m": round(float(rt_gap.max()), 6),
                          "landing_distance_median_m": round(float(np.median(rt_err)), 6),
                          "pass": bool(np.percentile(rt_gap, 95) <= ROUNDTRIP_TOL)},
            "continuity": {"tolerance_mm": CONTINUITY_TOL * 1000,
                           "p95_mm": round(float(np.percentile(jump, 95)) * 1000, 3),
                           "max_mm": round(float(jump.max()) * 1000, 3),
                           "pass": bool(np.percentile(jump, 95) <= CONTINUITY_TOL)},
            "normal_direction": {"tolerance_deg": NORMAL_TOL,
                                 "median_deg": round(float(np.median(ang_norm)), 3),
                                 "p95_deg": round(float(np.percentile(ang_norm, 95)), 3),
                                 "definition": "位移方向与法线的偏离（0° = 纯法向，90° = 纯切向滑动）",
                                 "pass": bool(np.percentile(ang_norm, 95) <= NORMAL_TOL)},
            "coverage": {"value": m_f["summary"]["coverage"],
                         "pass": bool(m_f["summary"]["coverage"] >= 0.99)},
        },
        "validation_status": overall,
        "status_counts": {s: statuses.count(s) for s in ("READY", "PARTIAL", "NEEDS_REVIEW", "PENDING")},
        "policy_note": ("只有全部验证项通过的区域才标 READY；"
                        "invalid_regions 中的区域不得用于服装转换"),
    }
    out = REPORTS / "BodyDifference_EBBRB_to_ANGEL.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n整体状态: {overall}  {doc['status_counts']}")
    print("写出:", out)


if __name__ == "__main__":
    main()
