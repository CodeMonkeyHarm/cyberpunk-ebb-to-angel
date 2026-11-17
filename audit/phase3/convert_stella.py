"""Phase 3 / TASK 3C：Stella 受控转换。

只做三件事：
  1. 用 3B 的计划，按区域权限把 EBBRB 版服装顶点位移到 ANGEL 身形
  2. 把结果写回 CR2W 网格（重量化 + 更新包围盒）
  3. 打包成独立 archive

不做：改骨骼/权重/三角面、改胸（chest）、生成上臂对应、触碰其它服装。

输出：output/phase3/stella/
诊断：audit/phase3/stella/convert_diagnostics.json
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import struct
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automation import body_model as BM                  # noqa: E402
from automation import body_profiles as P                 # noqa: E402
from automation import correspondence as CORR             # noqa: E402
from automation.cp77_skin import decode, v4, stream_layout
from automation import correspondence as CORR  # noqa: E402

BASE = ROOT / "audit" / "phase3" / "stella"
OUT = ROOT / "output" / "phase3" / "stella"
REPORTS = ROOT / "reports" / "phase3"
PLAN = REPORTS / "Conversion_Plan.json"
DIFF = ROOT / "reports" / "phase2" / "BodyDifference_EBBRB_to_ANGEL.json"
NPZ = ROOT / "audit" / "phase2" / "diff_v2" / "displacement_field.npz"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def vertex_adjacency(tris: np.ndarray, n: int) -> list[np.ndarray]:
    nb = [[] for _ in range(n)]
    for a, b, c in tris:
        nb[a].append(b); nb[a].append(c)
        nb[b].append(a); nb[b].append(c)
        nb[c].append(a); nb[c].append(b)
    seen = []
    for x in nb:
        seen.append(np.array(sorted(set(x)), dtype=np.int64) if x else np.zeros(0, np.int64))
    return seen


def laplacian_smooth(values: np.ndarray, adj: list[np.ndarray], iterations: int,
                     factor: float = 0.5) -> np.ndarray:
    v = values.astype(np.float64).copy()
    for _ in range(iterations):
        out = v.copy()
        for i, js in enumerate(adj):
            if js.size:
                out[i] = (1 - factor) * v[i] + factor * v[js].mean(axis=0)
        v = out
    return v


def region_of_z(z: float, bands: dict) -> str | None:
    """落在某个测量窄带内则返回该区域名，否则 None（只用于诊断统计）。"""
    for name, (lo, hi) in bands.items():
        if lo <= z <= hi:
            return name
    return None


def build_weights(verts_z: np.ndarray, bands: dict, policy: dict
                  ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """构造受限于 Phase 2 区域权限的权重场。

    归属规则（整改后）：每个顶点**归属于最近的区域带中心**（一维 Voronoi），
    权重 = 该区域的权限值；归属于禁止区域（chest / upper_arm）的顶点恒为 0。

    为什么不用"带内才生效"：区域带只有 4–8 cm 宽，是**测量用的截面位置**，
    不是身体分区的全部。若只在带内生效，连衣裙 79% 的顶点会落空，转换失效。
    Voronoi 归属给每个高度一个明确的区域身份，且禁止区仍然绝对不碰。

    为什么不用旧版的"区域中心全局线性插值"：旧版让 waist(1.112)→chest(1.364)
    之间的空白高度获得 0.08–0.30 的权重，等于在无授权的高度上施加位移。
    Voronoi 把这段中点为界：1.238 以下归 waist（授权），以上归 chest（禁止）。
    """
    base = {"APPLY": 1.0, "APPLY_LOW_FREQ": policy.get("_attenuation", 0.6), "SKIP": 0.0}
    items = sorted((sum(bands[k]) / 2.0, k, policy.get(k, "SKIP"),
                    base.get(policy.get(k, "SKIP"), 0.0)) for k in bands)
    centers = np.array([i[0] for i in items])
    names = [i[1] for i in items]
    acts = [i[2] for i in items]
    vals = np.array([i[3] for i in items])

    idx = np.abs(verts_z[:, None] - centers[None, :]).argmin(axis=1)
    w = vals[idx].copy()
    lab = np.array([names[i] for i in idx], dtype=object)
    forbidden = np.array([acts[i] == "SKIP" for i in idx])
    w[forbidden] = 0.0
    authorized = ~forbidden
    return w, lab, authorized


def convert_mesh(name: str, mesh_json: Path, dst_json: Path,
                 body: BM.BodyModel, disp: np.ndarray, body_verts: np.ndarray,
                 bands: dict, policy: dict, diag: dict,
                 target_body: BM.BodyModel | None = None,
                 min_clearance_m: float = 0.0005) -> dict:
    g = decode(mesh_json)
    n = g["vertex_count"]
    verts = np.concatenate([np.asarray(c["positions"]) for c in g["chunks"]])
    tris = []
    off = 0
    for c in g["chunks"]:
        idx = np.asarray(c["indices"], dtype=np.int64)
        if idx.size % 3 == 0:
            tris.append(idx.reshape(-1, 3) + off)
        off += c["vertex_count"]
    tris = np.concatenate(tris) if tris else np.zeros((0, 3), np.int64)
    adj = vertex_adjacency(tris, n)

    # --- 位移插值：服装顶点附近的身体顶点做反距离加权 ---
    from automation.correspondence import _Grid
    grid = _Grid(body_verts, 0.02)
    cands = grid.query_ball(verts, rings=2)
    disp_at = np.zeros_like(verts)
    near_count = np.zeros(n, dtype=np.int32)
    radius = policy.get("_sampling_radius_m")
    for i, c in enumerate(cands):
        if c.size == 0:
            continue
        d = np.linalg.norm(body_verts[c] - verts[i], axis=1)
        if radius is not None:
            inside = d < radius
            if inside.any():
                weights = (1 - (d[inside] / radius) ** 2) ** 2
                disp_at[i] = (disp[c[inside]] * weights[:, None]).sum(axis=0) / weights.sum()
                near_count[i] = int(inside.sum())
                continue
        k = min(4, c.size)
        sel = np.argsort(d)[:k]
        w = 1.0 / np.maximum(d[sel], 1e-6)
        w /= w.sum()
        disp_at[i] = (disp[c[sel]] * w[:, None]).sum(axis=0)
        near_count[i] = k

    # --- 区域与权重（按最近区域带中心归属，带外延伸须单独验收）---
    w_col, labels, authorized = build_weights(verts[:, 2], bands, policy)
    w_raw = w_col.reshape(-1, 1)
    lowfreq_mask = np.array([str(l).startswith(("hip", "pelvis")) and w_col[i] > 0
                             for i, l in enumerate(labels)])

    disp_low = laplacian_smooth(disp_at, adj, policy.get("_smooth_iters", 6))
    disp_use = (disp_low if policy.get("_smooth_all", False)
                else np.where(lowfreq_mask[:, None], disp_low, disp_at))
    w_smooth = laplacian_smooth(w_raw, adj, policy.get("_smooth_iters", 6))
    # 关键修复：平滑会把 0 从邻居拉起来，必须把「未授权 / 禁止区域」重新压回 0，
    # 否则 chest / upper_arm 的顶点会获得非零位移（越权）。
    w_smooth[~authorized, 0] = 0.0
    taper_width = float(policy.get("_taper_width_m", 0.0))
    if taper_width > 0:
        ordered = sorted((sum(bands[k]) / 2.0, k) for k in bands)
        z = verts[:, 2]
        for (_, left), (_, right) in zip(ordered, ordered[1:]):
            left_ok = policy.get(left) != "SKIP"
            right_ok = policy.get(right) != "SKIP"
            if left_ok == right_ok:
                continue
            boundary = (sum(bands[left]) + sum(bands[right])) / 4.0
            distance = boundary - z if left_ok else z - boundary
            t = np.clip(distance / taper_width, 0.0, 1.0)
            smoothstep = t * t * (3.0 - 2.0 * t)
            m = authorized & (distance >= 0) & (distance < taper_width)
            w_smooth[m, 0] *= smoothstep[m]
    disp_final = disp_use * w_smooth
    skip_mask = w_smooth[:, 0] <= 1e-9

    # --- 穿透保护：修正不得让服装穿进目标身体 ---
    # 只作用于已授权顶点；SKIP 顶点位移恒为 0，不需要也不会被改动。
    guard = {"applied": 0, "max_push_mm": 0.0, "min_clearance_m": min_clearance_m,
             "applied_fraction": 0.0}
    if target_body is not None and authorized.any():
        probe = BM.BodyModel(body_id=name, profile={}, geo=g, vertices=verts,
                             normals=np.zeros_like(verts), triangles=tris,
                             chunk_of_vertex=np.zeros(len(verts), dtype=np.int32),
                             bones={}, hierarchy=None, source_hashes={}, extra={})
        gm = CORR.match(probe, target_body, cell_m=0.02, angle_tol_deg=90.0, with_arrays=True)
        d0 = gm["_arrays"]["distance"]
        cl0 = gm["_arrays"]["closest"]
        tn0 = gm["_arrays"]["target_normal"]
        sgn0 = np.sign(np.einsum("ij,ij->i", verts - cl0, tn0) + 1e-12)
        g0 = d0 * sgn0                                  # 源顶点到目标身体的有符号间隙
        g1 = g0 + np.einsum("ij,ij->i", disp_final, tn0)  # 位移后的预测间隙
        need = authorized & (d0 <= 0.05) & (g1 < min_clearance_m)
        if need.any():
            push = (min_clearance_m - g1[need])
            correction = np.zeros_like(disp_final)
            correction[need] = tn0[need] * push[:, None]
            fraction = 1.0
            if policy.get("_topology_guard", False):
                original_normal = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]],
                                           verts[tris[:, 2]] - verts[tris[:, 0]])
                original_size = np.linalg.norm(original_normal, axis=1)
                if np.any(original_size <= 1e-12):
                    raise ValueError(f"{name}: source mesh contains degenerate triangles")

                def faces_ok(alpha: float) -> bool:
                    trial = verts + disp_final + alpha * correction
                    face_normal = np.cross(trial[tris[:, 1]] - trial[tris[:, 0]],
                                           trial[tris[:, 2]] - trial[tris[:, 0]])
                    size_ratio = np.linalg.norm(face_normal, axis=1) / original_size
                    same_direction = np.einsum("ij,ij->i", original_normal, face_normal) > 0
                    return bool(np.all(size_ratio >= 0.10) and np.all(same_direction))

                if not faces_ok(0.0):
                    raise ValueError(f"{name}: displacement before penetration guard damages faces")
                if not faces_ok(1.0):
                    low, high = 0.0, 1.0
                    for _ in range(24):
                        mid = (low + high) / 2
                        if faces_ok(mid):
                            low = mid
                        else:
                            high = mid
                    fraction = low * 0.98  # margin for int16 requantization
            disp_final += fraction * correction
            guard["applied"] = int(need.sum())
            guard["max_push_mm"] = round(float(push.max()) * 1000, 4)
            guard["applied_fraction"] = round(fraction, 6)

    new_verts = verts + disp_final

    # --- 写回 CR2W ---
    doc = json.loads(mesh_json.read_text(encoding="utf-8"))
    root = doc["Data"]["RootChunk"]
    blob = root["renderResourceBlob"]["Data"]
    header = blob["header"]
    buf = bytearray(base64.b64decode(blob["renderBuffer"]["Bytes"]))
    qs = np.array(v4(header["quantizationScale"])[:3])
    qo = np.array(v4(header["quantizationOffset"])[:3])

    # 若新顶点超出原量化范围，等比放大范围（精度损失可忽略，避免 int16 截断）
    lo = new_verts.min(axis=0)
    hi = new_verts.max(axis=0)
    center = (lo + hi) / 2.0
    half = np.maximum((hi - lo) / 2.0, 1e-6) * 1.02
    need = (center - half < qo - qs) | (center + half > qo + qs)
    if need.any():
        idx_need = np.where(need)[0]
        qs[idx_need] = half[idx_need]
        qo[idx_need] = center[idx_need]
    scale_before = np.array(v4(header["quantizationScale"])[:3])
    offset_before = np.array(v4(header["quantizationOffset"])[:3])
    qs = np.where(need, qs, scale_before)
    qo = np.where(need, qo, offset_before)

    v_off = 0
    clipped = 0
    for ci, ch in enumerate(header.get("renderChunkInfos", [])):
        nv = ch.get("numVertices", 0)
        if not nv:
            continue
        layout, strides = stream_layout(ch)
        offs = ch["chunkVertices"]["byteOffsets"]["Elements"]
        pos = None
        for st, items in layout.items():
            for (u, ui, t, off, size) in items:
                if u == "PS_Position":
                    pos = (st, off, t, size)
                    break
            if pos:
                break
        if not pos:
            v_off += nv
            continue
        st, poff, ptype, psize = pos
        stride = strides[st] if st < len(strides) else psize
        base = offs[st] if st < len(offs) else 0
        fmt = "<4h" if ptype == "PT_Short4N" else "<4H"
        for i in range(nv):
            o = base + i * stride + poff
            for ax in range(3):
                q = (new_verts[v_off + i, ax] - qo[ax]) / qs[ax] * 32767.0
                qi = int(round(q))
                if qi < -32768:
                    qi = -32768; clipped += 1
                elif qi > 32767:
                    qi = 32767; clipped += 1
                struct.pack_into("<h", buf, o + ax * 2, qi)
        v_off += nv

    # 更新 json 内的量化参数与包围盒
    def set_v4(key, arr):
        node = root if key in root else header
        node[key] = {"$type": "Vector4", "W": 1.0,
                     "X": float(arr[0]), "Y": float(arr[1]), "Z": float(arr[2])}
    set_v4("quantizationScale", qs)
    set_v4("quantizationOffset", qo)
    bb = root.get("boundingBox") or {}
    mn = bb.get("Min") or {}
    mx = bb.get("Max") or {}
    for ax, key in enumerate(("X", "Y", "Z")):
        if key in mn:
            mn[key] = float(min(mn[key], lo[ax]))
        if key in mx:
            mx[key] = float(max(mx[key], hi[ax]))
    blob["renderBuffer"]["Bytes"] = base64.b64encode(bytes(buf)).decode("ascii")

    dst_json.parent.mkdir(parents=True, exist_ok=True)
    dst_json.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    disp_norms = np.linalg.norm(disp_final, axis=1)
    info = {
        "mesh": name,
        "vertices": int(n),
        "triangles_indexed": int(tris.shape[0]),
        "triangles_unique": int(len(np.unique(np.sort(tris, axis=1), axis=0))),
        "displacement_mm": {"median": round(float(np.median(disp_norms)) * 1000, 4),
                            "p95": round(float(np.percentile(disp_norms, 95)) * 1000, 3),
                            "max": round(float(disp_norms.max()) * 1000, 3)},
        "region_vertex_counts": {k: int((labels == k).sum()) for k in sorted(set(labels)) if k},
        "authorized_vertices": int(authorized.sum()),
        "unauthorized_vertices": int((~authorized).sum()),
        "skip_vertices": int(skip_mask.sum()),
        "skip_max_displacement_mm": (round(float(disp_norms[skip_mask].max()) * 1000, 6)
                                     if skip_mask.any() else 0.0),
        "authorized_displacement_mm": {
            "n": int(authorized.sum()),
            "median": (round(float(np.median(disp_norms[authorized])) * 1000, 4)
                       if authorized.any() else 0.0),
            "p95": (round(float(np.percentile(disp_norms[authorized], 95)) * 1000, 3)
                    if authorized.any() else 0.0),
            "max": (round(float(disp_norms[authorized].max()) * 1000, 3)
                    if authorized.any() else 0.0)},
        "penetration_guard": guard,
        "skip_z_range": ([round(float(verts[skip_mask, 2].min()), 4),
                          round(float(verts[skip_mask, 2].max()), 4)]
                         if skip_mask.any() else None),
        "weight_band_counts": {"w=0": int((w_smooth[:, 0] <= 1e-9).sum()),
                               "0<w<0.99": int(((w_smooth[:, 0] > 1e-9) & (w_smooth[:, 0] < 0.99)).sum()),
                               "w>=0.99": int((w_smooth[:, 0] >= 0.99).sum())},
        "active_vertices": int((w_smooth[:, 0] > 1e-9).sum()),
        "fully_skipped_vertices": int(skip_mask.sum()),
        "vertices_without_body_neighbor": int((near_count == 0).sum()),
        "clipped_quantized_components": int(clipped),
        "quantization_changed": [bool(x) for x in need],
        "bbox_before": {"min": [round(float(x), 6) for x in verts.min(0)],
                        "max": [round(float(x), 6) for x in verts.max(0)]},
        "bbox_after": {"min": [round(float(x), 6) for x in new_verts.min(0)],
                       "max": [round(float(x), 6) for x in new_verts.max(0)]},
        "output_json": dst_json.relative_to(ROOT).as_posix(),
        "output_json_sha256": sha256(dst_json),
    }
    return info, skip_mask


def main(run_tag: str = "v3") -> None:
    """run_tag 用于隔离整改前后的产物；旧产物保留为可追溯基线。"""
    OUT.mkdir(parents=True, exist_ok=True)
    run_dir = BASE / run_tag
    (run_dir / "converted_json").mkdir(parents=True, exist_ok=True)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    diff = json.loads(DIFF.read_text(encoding="utf-8"))
    npz = np.load(NPZ)
    disp = npz["disp"].astype(np.float64)
    body_verts = npz["src_vertices"].astype(np.float64)

    bands = {}
    for k, v in diff["regional_measurements"].items():
        bands[k] = (float(v["band_z"][0]), float(v["band_z"][1]))

    policy = {k: v for k, v in plan["meshes"][0]["region_policy"].items()}
    policy["_attenuation"] = plan["constraints"]["partial_attenuation"]
    policy["_smooth_iters"] = plan["constraints"]["partial_smoothing_iterations"]
    if run_tag != "v3":
        raise ValueError("Current converter writes v3 only; v2 source snapshot is preserved separately")
    policy["_taper_width_m"] = 0.02
    policy["_topology_guard"] = True
    policy["_weight_rule"] = ("最近 Phase 2 区域带中心的 Voronoi 归属；READY=1，PARTIAL=0.6，"
                              "SKIP=0；权重平滑后重新归零 SKIP；授权侧 20mm 渐变。"
                              "带外授权仍待正式验收")

    body = BM.load(P.load("EBBRB"))
    target = BM.load(P.load("ANGEL"))
    diag = {"schema": "cp77.phase3.conversion_diagnostics/v3",
            "generator": f"audit/phase3/convert_stella.py (run_tag={run_tag})",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "revision_note": ("v3 试验：禁用侧零位移、授权侧 20mm 渐变；"
                              "穿透保护设置面方向和最小面积约束。带外延伸尚待验收"),
            "plan_sha256": sha256(PLAN),
            "difference_field_sha256": sha256(DIFF),
            "displacement_field_sha256": sha256(NPZ),
            "policy": policy, "bands": bands, "meshes": []}

    jdir = BASE / "json"
    skip_masks: dict[str, "np.ndarray"] = {}
    for item in plan["meshes"]:
        if item["action"] != "DEFORM":
            print(f"跳过 {item['mesh']}：{item.get('reason')}")
            continue
        src = next(jdir.rglob(item["mesh"] + ".mesh.json"))
        dst = run_dir / "converted_json" / (item["mesh"] + ".mesh.json")
        print(f"转换 {item['mesh']} …")
        info, skip = convert_mesh(item["mesh"], src, dst, body, disp, body_verts, bands, policy, diag,
                                  target_body=target)
        skip_masks[item["mesh"]] = skip
        info["source_json"] = src.relative_to(ROOT).as_posix()
        info["source_json_sha256"] = sha256(src)
        diag["meshes"].append(info)
        print(f"  顶点 {info['vertices']} / 索引三角 {info['triangles_indexed']} "
              f"/ 唯一三角 {info['triangles_unique']}")
        print(f"  位移 中位 {info['displacement_mm']['median']}mm 最大 {info['displacement_mm']['max']}mm | "
              f"授权 {info['authorized_vertices']} / 跳过 {info['skip_vertices']} "
              f"(跳过者最大位移 {info['skip_max_displacement_mm']}mm)")

    np.savez_compressed(run_dir / "skip_masks.npz", **skip_masks)
    diag["skip_masks_file"] = (run_dir / "skip_masks.npz").relative_to(ROOT).as_posix()
    diag["skip_masks_sha256"] = sha256(run_dir / "skip_masks.npz")
    (run_dir / "convert_diagnostics.json").write_text(
        json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n写出:", run_dir / "convert_diagnostics.json")

    (BASE / "convert_diagnostics.json").write_text(
        json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n写出:", BASE / "convert_diagnostics.json")


if __name__ == "__main__":
    main()
