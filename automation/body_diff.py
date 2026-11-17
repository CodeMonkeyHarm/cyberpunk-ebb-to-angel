"""BodyDifferenceField：两个身形之间的差异场。

**边界（必须记住）**：
- 截面测量（宽度/厚度/面积）与三维顶点位移场是**两种不同的数据**。
  前者是标量测量，后者是每顶点一个三维向量；不能用前者代替后者，
  也不能把截面数据「积分」回三维位移。
- 只有当两个身形都有真实数据时才允许产出 `status=READY`；缺一个就返回 `PENDING`，
  并写清缺什么。**不许编造 EBB 数据。**

差异场内容：
1. 身高差异
2. 区域宽度/厚度/面积差异（按标准化高度对齐，不强制同名）
3. 表面局部差异（源顶点 → 目标表面最近点距离，按目标法线取符号 → 近似厚度变化）
4. 区域对应关系
5. 数据置信度（覆盖率、距离中位数/p95、法向夹角、NEEDS_REVIEW 比例）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from . import body_morphology as MORPH
from . import body_profiles as P
from . import correspondence as CORR

VERSION = "1.1.0"
SCHEMA = "cp77.body.difference_field/v1"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ PENDING
def pending(target_id: str, source_id: str, reasons: list[str],
            *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """差异场未就绪时的标准返回：字段齐全、数值为空，绝不填占位数字。"""
    return {
        "schema": SCHEMA,
        "generator": f"automation/body_diff.py v{VERSION}",
        "generated_at": _now(),
        "source_body": source_id,
        "target_body": target_id,
        "status": "PENDING",
        "reasons": reasons,
        "measurements": None,
        "surface": None,
        "region_map": None,
        "confidence": {"level": "NONE", "why": "缺少至少一方身形数据，未做任何计算"},
        "notes": [
            "PENDING 表示数据缺口，不是「没有差异」。",
            "拿到缺失身形后，用同一条命令即可生成差异场；不需要改代码。",
        ],
        **(extra or {}),
    }


# ------------------------------------------------------------------ 核心计算
def compare_models(src, dst, *, src_morph: dict[str, Any] | None = None,
                   dst_morph: dict[str, Any] | None = None,
                   correspondence_kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    """两个已载入的身形对象 → 差异场（READY）。不碰档案与磁盘。"""
    if src_morph is None:
        src_morph = MORPH.BodyMorphologyAnalyzer(src).analyze()
    if dst_morph is None:
        dst_morph = MORPH.BodyMorphologyAnalyzer(dst).analyze()

    rmap = _region_map(src_morph, dst_morph)
    regions = _compare_regions(src_morph, dst_morph, rmap)

    corr = CORR.match(src, dst, regions=src_morph["regions"],
                      with_arrays=True, **(correspondence_kwargs or {}))
    arr = corr.pop("_arrays")
    dist = arr["distance"]
    closest, tnorm = arr["closest"], arr["target_normal"]
    signed = np.einsum("ij,ij->i", src.vertices - closest, tnorm)

    height_src = src_morph["overall"]["dimensions"]["height_m"]
    height_dst = dst_morph["overall"]["dimensions"]["height_m"]
    ok = arr["ok"]
    finite = dist[np.isfinite(dist)]
    p95 = float(np.percentile(finite, 95)) if finite.size else None
    ok_ratio = float(ok.mean())
    level = ("HIGH" if ok_ratio >= 0.95 and p95 is not None and p95 <= 0.01
             else "MEDIUM" if ok_ratio >= 0.80 else "LOW")

    return {
        "schema": SCHEMA,
        "generator": f"automation/body_diff.py v{VERSION}",
        "generated_at": _now(),
        "source_body": src.body_id,
        "target_body": dst.body_id,
        "status": "READY",
        "reasons": [],
        "identity": {
            "source": {"body_id": src.body_id, "vertices": src.vertex_count,
                       "triangles": src.triangle_count,
                       "mesh_json_sha256": src.source_hashes.get("mesh_json")},
            "target": {"body_id": dst.body_id, "vertices": dst.vertex_count,
                       "triangles": dst.triangle_count,
                       "mesh_json_sha256": dst.source_hashes.get("mesh_json")},
        },
        "measurements": {
            "height": {"source_m": height_src, "target_m": height_dst,
                       "delta_m": round(height_dst - height_src, 6),
                       "delta_ratio": round((height_dst - height_src) / height_src, 6)},
            "regions": regions,
            "region_map": rmap,
            "note": ("宽度/厚度取带内顶点包围（silhouette_band），面积取水平截面；"
                     "两者都是标量测量，不是三维位移。"),
        },
        "surface": {
            "correspondence_summary": corr["summary"],
            "distance_m": corr["summary"]["distance_m"],
            "signed_normal_delta_m": {
                "mean": round(float(np.mean(signed)), 6),
                "median": round(float(np.median(signed)), 6),
                "p05": round(float(np.percentile(signed, 5)), 6),
                "p95": round(float(np.percentile(signed, 95)), 6),
                "max_outward": round(float(signed.max()), 6),
                "max_inward": round(float(signed.min()), 6),
                "positive_ratio": round(float((signed > 0).mean()), 6),
                "definition": "d·n（源顶点 − 目标最近点）投影到目标法线；正=源在目标外侧",
            },
            "per_region": corr["regions"],
            "flagged_examples": corr["flagged_examples"],
            "topology_report": corr["topology_report"],
            "caveat": ("这是「源顶点到目标表面」的对应距离，可用于判断各区域偏胖/偏瘦；"
                       "它不是绑定点意义上的顶点位移，也不能直接套到服装的权重空间。"),
        },
        "confidence": {
            "level": level,
            "ok_ratio": round(ok_ratio, 6),
            "needs_review": int((~ok).sum()),
            "distance_p95_m": round(p95, 6) if p95 is not None else None,
            "angle_p95_deg": corr["summary"]["angle_deg"]["p95"],
            "criteria": "HIGH: OK≥95% 且 p95 ≤10mm；MEDIUM: OK≥80%；其余 LOW",
        },
        "notes": [
            "截面差异与表面位移场是不同数据：前者标量、按高度切片；后者逐顶点三维向量。",
            "区域对应按标准化高度匹配，不强制同名（两身形地标位置不同）。",
            "NEEDS_REVIEW 的顶点保留在 flagged_examples，不做丢弃。",
        ],
    }


# ------------------------------------------------------------------ 档案入口
def _require(body_id: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        prof = P.load(body_id)
    except P.ProfileError as exc:
        return None, str(exc)
    if not prof["available"]:
        return prof, (f"身形 {body_id} 状态为 {prof['status']}：数据源未接入"
                      "（source.mesh_json 为空）")
    mesh_json = P.resolve(prof["source"].get("mesh_json"))
    if mesh_json is None or not mesh_json.is_file():
        return prof, f"身形 {body_id} 的 source.mesh_json 不存在：{mesh_json}"
    raw = P.resolve(prof["source"].get("raw_mesh"))
    if raw is None or not raw.is_file():
        return prof, f"身形 {body_id} 的 source.raw_mesh 不存在：{raw}"
    return prof, None


def field(source_id: str, target_id: str, *,
          correspondence_kwargs: dict[str, Any] | None = None,
          morphology_src: dict[str, Any] | None = None,
          morphology_dst: dict[str, Any] | None = None) -> dict[str, Any]:
    """按档案计算差异场。任一方缺数据 → PENDING（不抛错，方便批量调度）。"""
    src_prof, src_err = _require(source_id)
    dst_prof, dst_err = _require(target_id)
    reasons = [r for r in (src_err, dst_err) if r]
    if reasons:
        return pending(target_id, source_id, reasons,
                       extra={"datasource": {
                           "source": {"body_id": source_id, "error": src_err},
                           "target": {"body_id": target_id, "error": dst_err}}})

    assert src_prof and dst_prof
    from . import body_model as BM
    src = BM.load(src_prof)
    dst = BM.load(dst_prof)
    return compare_models(src, dst, src_morph=morphology_src, dst_morph=morphology_dst,
                          correspondence_kwargs=correspondence_kwargs)


# ------------------------------------------------------------------ 辅助
def _region_map(src_morph: dict[str, Any], dst_morph: dict[str, Any]) -> dict[str, Any]:
    """区域对应：按 height_norm 中心找最近的区域（不强制同名）。"""
    out: dict[str, Any] = {}
    dst_regions = dst_morph["regions"]
    for name, reg in src_morph["regions"].items():
        hn = reg["band"]["height_norm"]
        best, best_d = None, 9e9
        for dn, dreg in dst_regions.items():
            d = abs(dreg["band"]["height_norm"] - hn)
            if d < best_d:
                best, best_d = dn, d
        out[name] = {
            "target_region": best,
            "height_norm_source": hn,
            "height_norm_target": dst_regions[best]["band"]["height_norm"],
            "delta_height_norm": round(dst_regions[best]["band"]["height_norm"] - hn, 6),
            "same_name": best == name,
            "method": "按标准化高度中心最近匹配（两个身形地标不同，不能强按同名对齐）",
        }
    return out


def _compare_regions(src_morph: dict[str, Any], dst_morph: dict[str, Any],
                     rmap: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, reg in src_morph["regions"].items():
        target_name = rmap[name]["target_region"]
        dreg = dst_morph["regions"][target_name]
        s_sil, d_sil = reg.get("silhouette") or {}, dreg.get("silhouette") or {}
        s_sec, d_sec = reg["section"], dreg["section"]

        def delta(a, b):
            return None if (a is None or b is None) else round(b - a, 8)

        out[name] = {
            "source_region": name,
            "target_region": target_name,
            "same_name": rmap[name]["same_name"],
            "width_m": {"source": s_sil.get("width_m"), "target": d_sil.get("width_m"),
                        "delta": delta(s_sil.get("width_m"), d_sil.get("width_m")),
                        "source_kind": "silhouette_band"},
            "thickness_m": {"source": s_sil.get("thickness_m"),
                            "target": d_sil.get("thickness_m"),
                            "delta": delta(s_sil.get("thickness_m"), d_sil.get("thickness_m")),
                            "source_kind": "silhouette_band"},
            "area_m2": {"source": s_sec.get("area_m2_mean"),
                        "target": d_sec.get("area_m2_mean"),
                        "delta": delta(s_sec.get("area_m2_mean"), d_sec.get("area_m2_mean")),
                        "source_kind": f"section:{s_sec.get('area_method')}",
                        "comparable": (s_sec.get("area_method") == "EXACT"
                                       and d_sec.get("area_method") == "EXACT")},
            "reliability": {"source": reg["reliability"]["level"],
                            "target": dreg["reliability"]["level"]},
            "comparable": bool(reg["applicable"] and dreg["applicable"]),
            "not_comparable_reason": None if (reg["applicable"] and dreg["applicable"])
            else f"适用性：source={reg['applicable']} target={dreg['applicable']}",
        }
    return out
