"""Phase 3 整改验证：SKIP 位移归零 + 间隙/穿透 + 细粒度分带对比。

针对审核意见 1/2/3：
  1. 打包后网格中，被定义为 SKIP 的顶点位移必须为零（量化误差阈值明确给出依据）
  2. 逐 2 cm 分带比较「原始 ebbrb / 整改版 / v1 / 作者 angel」的穿透数量与深度，
     明确 1.288–1.344 段的区域归属
  3. 间隙与穿透分开报告，不用中位间隙代表整体质量

输出：audit/phase3/stella/v2/remediation_validation.json
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
from automation import body_profiles as P                 # noqa: E402
from automation import correspondence as CORR             # noqa: E402
from automation.cp77_skin import decode                   # noqa: E402

BASE = ROOT / "audit" / "phase3" / "stella"
V2 = BASE / "v2"
OUT = V2 / "remediation_validation.json"
MAX_GAP = 0.050
# 量化误差阈值依据：int16 有符号量化，分辨率 = 2*scale/65535。
# 连衣裙 x 轴 scale≈0.22 m → 6.7 µm；极端情况下 scale 放大到 bbox 全宽也不会超过
# 0.0001 m 的百分之一。取 0.05 mm 作为"位移为零"的判定阈值，比量化噪声大 7 倍以上，
# 足以区分"真的没动"与"被移动了"。
SKIP_TOL_M = 0.00005


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def verts_of(p: Path) -> np.ndarray:
    g = decode(p)
    return np.concatenate([np.asarray(c["positions"]) for c in g["chunks"]])


def as_model(name, p: Path) -> BM.BodyModel:
    g = decode(p)
    verts, norms, tris, ch = [], [], [], []
    off = 0
    for ci, c in enumerate(g["chunks"]):
        n = c["vertex_count"]
        v = np.asarray(c["positions"], dtype=float)
        nm = np.asarray(c["normals"], dtype=float) if c.get("normals") else np.zeros((n, 3))
        idx = np.asarray(c["indices"], dtype=np.int64)
        if idx.size % 3 == 0:
            idx = idx.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1)
        verts.append(v); norms.append(nm); ch.append(np.full(n, ci, np.int32))
        if idx.size:
            tris.append(idx + off)
        off += n
    vv = np.vstack(verts); nn = np.vstack(norms)
    ln = np.linalg.norm(nn, axis=1, keepdims=True)
    nn = np.divide(nn, ln, out=np.zeros_like(nn), where=ln > 0)
    return BM.BodyModel(body_id=name, profile={}, geo=g, vertices=vv, normals=nn,
                        triangles=np.concatenate(tris).reshape(-1, 3) if tris
                        else np.zeros((0, 3), np.int64),
                        chunk_of_vertex=np.concatenate(ch), bones={}, hierarchy=None,
                        source_hashes={}, extra={})


def signed_clearance(model: BM.BodyModel, body: BM.BodyModel) -> tuple[np.ndarray, np.ndarray]:
    m = CORR.match(model, body, cell_m=0.02, angle_tol_deg=75.0, with_arrays=True)
    d = m["_arrays"]["distance"]
    cl = m["_arrays"]["closest"]
    tn = m["_arrays"]["target_normal"]
    signed = d * np.sign(np.einsum("ij,ij->i", model.vertices - cl, tn) + 1e-12)
    return signed, d <= MAX_GAP


def gap_stats(model: BM.BodyModel, body: BM.BodyModel) -> dict:
    signed_all, valid = signed_clearance(model, body)
    signed = signed_all[valid]
    distance = np.abs(signed)
    pen = signed < -0.0005
    z = model.vertices[:, 2][valid]
    return {
        "valid_vertices": int(valid.sum()),
        "gap_mm": {"median": round(float(np.median(distance)) * 1000, 3),
                   "p95": round(float(np.percentile(distance, 95)) * 1000, 3),
                   "max": round(float(distance.max()) * 1000, 3)},
        "penetration": {"count": int(pen.sum()),
                        "ratio_pct": round(float(pen.sum() / max(int(valid.sum()), 1)) * 100, 3),
                        "deepest_mm": round(float(signed[pen].min()) * 1000, 3) if pen.any() else 0.0,
                        "z_p05": round(float(np.percentile(z[pen], 5)), 4) if pen.any() else None,
                        "z_median": round(float(np.median(z[pen])), 4) if pen.any() else None,
                        "z_p95": round(float(np.percentile(z[pen], 95)), 4) if pen.any() else None},
        "_z": z, "_signed": signed,
    }


def band_table(z: np.ndarray, signed: np.ndarray, edges=None) -> list[dict]:
    if edges is None:
        edges = [round(1.20 + 0.02 * i, 4) for i in range(12)]      # 1.20 → 1.44
    rows = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        m = (z >= lo) & (z < hi)
        if not m.any():
            continue
        s = signed[m]
        pen = s < -0.0005
        rows.append({"z": [lo, hi], "n": int(m.sum()),
                     "pen": int(pen.sum()),
                     "pen_pct": round(float(pen.mean()) * 100, 2),
                     "deepest_mm": round(float(s[pen].min()) * 1000, 2) if pen.any() else 0.0})
    return rows


def main() -> None:
    bodies = {"EBBRB": BM.load(P.load("EBBRB")), "ANGEL": BM.load(P.load("ANGEL"))}
    masks = np.load(V2 / "skip_masks.npz")
    doc = {"schema": "cp77.phase3.remediation_validation/v1",
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "inputs": {},
           "checks": {}}

    files = {
        "source": next((BASE / "json").rglob("ebbrb_dress.mesh.json")),
        "v1": next((BASE / "verify_json").rglob("ebbrb_dress.mesh.json")),
        "v2_packed": next((V2 / "roundtrip" / "json").rglob("angel_dress.mesh.json")),
        "author": next((BASE / "json").rglob("angel_dress.mesh.json")),
    }
    for k, p in files.items():
        doc["inputs"][k] = {"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)}

    src_v = verts_of(files["source"])
    skip = masks["ebbrb_dress"]

    # ---------- 1. SKIP 位移归零 ----------
    for tag in ("v1", "v2_packed"):
        v = verts_of(files[tag])
        d = np.linalg.norm(v - src_v, axis=1)
        d_skip = d[skip]
        d_auth = d[~skip]
        doc["checks"][f"skip_zero_{tag}"] = {
            "skip_vertices": int(skip.sum()),
            "skip_max_displacement_m": round(float(d_skip.max()), 9) if d_skip.size else 0.0,
            "skip_max_displacement_mm": round(float(d_skip.max()) * 1000, 6) if d_skip.size else 0.0,
            "threshold_m": SKIP_TOL_M,
            "pass": bool(d_skip.size == 0 or d_skip.max() <= SKIP_TOL_M),
            "authorized_vertices": int((~skip).sum()),
            "authorized_displacement_mm": {"median": round(float(np.median(d_auth)) * 1000, 4),
                                           "p95": round(float(np.percentile(d_auth, 95)) * 1000, 3),
                                           "max": round(float(d_auth.max()) * 1000, 3)},
        }
        print(f"[{tag}] skip {int(skip.sum())} 顶点，最大位移 "
              f"{doc['checks'][f'skip_zero_{tag}']['skip_max_displacement_mm']:.6f} mm "
              f"-> {'PASS' if doc['checks'][f'skip_zero_{tag}']['pass'] else 'FAIL'}")

    # ---------- 2. 间隙与穿透（分离） ----------
    for tag in ("source", "v1", "v2_packed", "author"):
        m = as_model(tag, files[tag])
        st = gap_stats(m, bodies["ANGEL"])
        z, sg = st.pop("_z"), st.pop("_signed")
        doc["checks"][f"gap_{tag}"] = st
        doc["checks"].setdefault("band_tables", {})[tag] = band_table(z, sg)
        print(f"[{tag:10s}] 间隙中位 {st['gap_mm']['median']:>6.2f}mm | "
              f"穿透 {st['penetration']['count']:>4} 点 ({st['penetration']['ratio_pct']:>5.2f}%) "
              f"最深 {st['penetration']['deepest_mm']:>7.2f}mm | "
              f"z 中位 {st['penetration']['z_median']}")

    (V2 / "remediation_validation.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n写出:", OUT)


if __name__ == "__main__":
    main()
