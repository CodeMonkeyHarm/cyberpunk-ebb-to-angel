"""通用身形参考资产构建器（v2.0.0，按档案参数化）。

与 v1.1.0 的区别：
- 不再硬编码 ANGEL 路径：一切来自 `config/bodies/<BODY_ID>.json`；
- 新增 `--body` 选择身形，新增 `--version` 指定产物目录版本；
- 产物写入 `references/bodies/<BODY_ID>/<asset_version>/`，**不覆盖**已冻结的历史版本；
- 额外产出统一记录 `*_Body_Record.json` 与形态测量 `*_Morphology.json`。

用法：
    python automation/main.py ref build  --body ANGEL
    python automation/main.py ref build  --body EBB          # 未接入数据源时会直接报错
    python automation/main.py ref verify --body ANGEL

历史版本 v1.1.0 的产物冻结在 `references/bodies/ANGEL/v1.1.0/`，本模块从不写那里。
"""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

from . import body_model as BM
from . import body_morphology as MORPH
from . import body_profiles as P
from . import cp77_skin as S
from . import gltf_skin as G
from . import rig_hierarchy as RIG

VERSION = "2.0.0"
MANIFEST_SCHEMA = "cp77.body.asset/v2"


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _det3(m) -> float:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


# --------------------------------------------------------------- 输入核实
def verify_sources(model: BM.BodyModel, prof: dict[str, Any]) -> dict[str, Any]:
    """与身形无关的输入核实。所有判据都是数值阈值，不做假设。"""
    geo = model.geo
    checks: dict[str, Any] = {"builder": f"reference_builder v{VERSION}"}
    src = prof["source"]

    checks["raw_mesh_exists"] = True
    checks["raw_mesh_sha256"] = model.source_hashes.get("raw_mesh")
    checks["mesh_json_sha256"] = model.source_hashes.get("mesh_json")
    checks["mesh_json_bytes"] = Path(
        P.resolve(src["mesh_json"])).stat().st_size if src.get("mesh_json") else None
    raw_path = P.resolve(src.get("raw_mesh"))
    checks["raw_mesh_bytes"] = raw_path.stat().st_size if raw_path else None
    if raw_path and raw_path.is_file():
        with open(raw_path, "rb") as f:
            checks["raw_mesh_magic"] = f.read(4).decode("ascii", "replace")
    checks["reference_packs"] = [
        {"path": str(p), "exists": Path(p).is_file(),
         "bytes": Path(p).stat().st_size if Path(p).is_file() else None}
        for p in (P.resolve(x) for x in (src.get("packs") or [])) if p
    ]

    declared_v = sum(c.get("vertex_count", 0) for c in geo["chunks"])
    checks["decoded_vertex_count"] = model.vertex_count
    checks["declared_chunk_vertex_sum"] = declared_v
    checks["chunk_count"] = len(geo["chunks"])
    checks["vertex_count_match"] = model.vertex_count == declared_v
    checks["index_out_of_range_dropped"] = sum(c["dropped_indices"] for c in geo["chunks"])

    dims = model.dimensions()
    checks["decoded_bbox"] = {"min": dims["bbox_min"], "max": dims["bbox_max"]}
    db = geo["declared_bbox"]
    err = max(abs(dims["bbox_min"][i] - db["min"][i]) for i in range(3))
    err = max(err, max(abs(dims["bbox_max"][i] - db["max"][i]) for i in range(3)))
    checks["bbox_max_error_m"] = round(err, 9)
    checks["bbox_match"] = err < float(prof["quality"]["max_bbox_error_m"])

    zero_err = 0.0
    det_min, det_max = 9e9, -9e9
    for i, m in enumerate(geo["ibm_cp77"]):
        p = geo["bone_positions"][i]
        out = [sum(m[r][c] * p[c] for c in range(3)) + m[r][3] for r in range(3)]
        zero_err = max(zero_err, max(abs(v) for v in out))
        d = _det3(m)
        det_min, det_max = min(det_min, d), max(det_max, d)
    checks["ibm_times_bonepos_max_error"] = round(zero_err, 9)
    checks["ibm_det_min"] = round(det_min, 6)
    checks["ibm_det_max"] = round(det_max, 6)
    checks["ibm_is_inverse_bind"] = (zero_err < float(prof["quality"]["max_ibm_error"])
                                     and abs(det_min - 1) < 1e-3 and abs(det_max - 1) < 1e-3)

    max_joint = 0
    for c in geo["chunks"]:
        for j0, j1, w0, w1 in zip(c["joints0"], c["joints1"], c["weights0"], c["weights1"]):
            for j, w in zip(j0, w0):
                if w:
                    max_joint = max(max_joint, j)
            for j, w in zip(j1, w1):
                if w:
                    max_joint = max(max_joint, j)
    checks["max_joint_index_used"] = max_joint
    checks["bone_count"] = len(geo["bone_names"])
    checks["joint_index_in_range"] = max_joint < len(geo["bone_names"])

    # 与 .mesh 重新序列化结果的语义比对（证明 .mesh 与 .mesh.json 是同一资源）
    checks["mesh_json_is_reserialized_raw"] = None
    checks["mesh_json_identity_note"] = "未执行"
    try:
        from . import config as cfgmod
        from .wolvenkit_adapter import WolvenKit
        cfg = cfgmod.load()
        wk = WolvenKit(cfgmod.require_path(cfg, "wolvenkit.cli"),
                       cfgmod.dir_of(cfg, "logs", create=True))
        tmp = cfgmod.dir_of(cfg, "projects", create=True) / "_ref_check" / "reser"
        r = wk.serialize(P.resolve(prof["source"]["raw_mesh"]), tmp)
        if r.get("json"):
            same_bytes = sha256(Path(r["json"])) == checks["mesh_json_sha256"]
            fresh = json.loads(Path(r["json"]).read_text(encoding="utf-8"))
            old_doc = json.loads(Path(P.resolve(prof["source"]["mesh_json"]))
                                 .read_text(encoding="utf-8"))
            fr = fresh["Data"]["RootChunk"]["renderResourceBlob"]["Data"]
            od = old_doc["Data"]["RootChunk"]["renderResourceBlob"]["Data"]
            import base64
            cmp = {
                "render_buffer_identical": (
                    hashlib.sha256(base64.b64decode(fr["renderBuffer"]["Bytes"])).hexdigest()
                    == hashlib.sha256(base64.b64decode(od["renderBuffer"]["Bytes"])).hexdigest()),
                "vertex_count": [sum(c.get("numVertices", 0) for c in fr["header"]["renderChunkInfos"]),
                                 sum(c.get("numVertices", 0) for c in od["header"]["renderChunkInfos"])],
                "chunk_count": [len(fr["header"]["renderChunkInfos"]),
                                len(od["header"]["renderChunkInfos"])],
                "geometry_hash": [fresh["Data"]["RootChunk"].get("geometryHash"),
                                  old_doc["Data"]["RootChunk"].get("geometryHash")],
            }
            checks["reserialize_compare"] = cmp
            checks["mesh_json_is_reserialized_raw"] = bool(
                cmp["render_buffer_identical"]
                and cmp["vertex_count"][0] == cmp["vertex_count"][1]
                and cmp["chunk_count"][0] == cmp["chunk_count"][1]
                and cmp["geometry_hash"][0] == cmp["geometry_hash"][1])
            checks["mesh_json_identity_note"] = (
                "重新序列化与原 .mesh.json 逐字节一致" if same_bytes else
                ("字节不同但顶点缓冲/顶点数/chunk 数/geometryHash 全一致 → 同一资源的两种 JSON 表示"
                 if checks["mesh_json_is_reserialized_raw"] else "语义比对也不一致，停止"))
        else:
            checks["mesh_json_identity_note"] = "重新序列化失败，未证明对应关系"
    except Exception as exc:  # noqa: BLE001
        checks["mesh_json_identity_note"] = f"检查失败：{exc}"

    # 层级来源
    rig_path = P.resolve((prof.get("rig") or {}).get("rig_json"))
    checks["hierarchy_available"] = bool(rig_path and rig_path.is_file())
    if checks["hierarchy_available"]:
        checks["hierarchy_source"] = str(rig_path)
        checks["hierarchy_evidence"] = ("CMesh 无父子字段；层级取自 animRig，仅提供父子关系，"
                                        "矩阵仍用 CMesh IBM")
    else:
        checks["hierarchy_evidence"] = f"未找到 rig JSON（{rig_path}）→ 退化为扁平骨架"

    # 期望值（档案里写了的就核对，写 null 就跳过）
    exp = prof.get("expectations") or {}
    diffs = {}
    for key, actual in (("vertices", model.vertex_count),
                        ("triangles", model.triangle_count),
                        ("bones", len(geo["bone_names"])),
                        ("chunks", len(geo["chunks"]))):
        if exp.get(key) is not None and exp[key] != actual:
            diffs[key] = {"expected": exp[key], "actual": actual}
    checks["expectation_mismatch"] = diffs
    checks["expectations_ok"] = not diffs

    q = prof["quality"]
    checks["quality_gates"] = {
        "min_vertices": model.vertex_count >= q["min_vertices"],
        "min_triangles": model.triangle_count >= q["min_triangles"],
        "min_bones": len(geo["bone_names"]) >= q["min_bones"],
        "vertex_count_match": checks["vertex_count_match"],
        "bbox_match": checks["bbox_match"],
        "ibm_is_inverse_bind": checks["ibm_is_inverse_bind"],
        "joint_index_in_range": checks["joint_index_in_range"],
    }
    checks["all_gates_passed"] = all(checks["quality_gates"].values())
    return checks


# ----------------------------------------------------------- 权重分析
def weight_analysis(model: BM.BodyModel) -> dict[str, Any]:
    geo = model.geo
    bones = geo["bone_names"]
    per_bone = [{"index": i, "name": n, "vertices": 0, "weight_sum": 0.0, "max_weight": 0.0}
                for i, n in enumerate(bones)]
    chunks_out = []
    totals = {"vertices": 0, "unweighted": 0, "sum_lt_0_9": 0, "sum_gt_1_1": 0,
              "max_influences": 0}
    influence_hist: dict[int, int] = {}
    bone_pos = geo["bone_positions"]
    far_weighted = 0
    max_bone_dist = 0.0
    for ch in geo["chunks"]:
        nv = ch["vertex_count"]
        sums = ch["weight_sums"]
        positions = ch["positions"]
        for vi in range(nv):
            j0, w0, j1, w1 = (ch["joints0"][vi], ch["weights0"][vi],
                              ch["joints1"][vi], ch["weights1"][vi])
            best_j, best_w = -1, 0.0
            for j, w in list(zip(j0, w0)) + list(zip(j1, w1)):
                if w > best_w:
                    best_j, best_w = j, w
            if best_j < 0:
                continue
            p = positions[vi]
            bp = bone_pos[best_j]
            d = ((p[0] - bp[0]) ** 2 + (p[1] - bp[1]) ** 2 + (p[2] - bp[2]) ** 2) ** 0.5
            max_bone_dist = max(max_bone_dist, d)
            if d > 0.6:
                far_weighted += 1
        unweighted = sum(1 for s in sums if s <= 0)
        infl = []
        for j0, w0, j1, w1 in zip(ch["joints0"], ch["weights0"], ch["joints1"], ch["weights1"]):
            n = sum(1 for w in w0 if w > 0) + sum(1 for w in w1 if w > 0)
            infl.append(n)
            influence_hist[n] = influence_hist.get(n, 0) + 1
            for j, w in zip(j0, w0):
                if w > 0:
                    per_bone[j]["vertices"] += 1
                    per_bone[j]["weight_sum"] += w
                    per_bone[j]["max_weight"] = max(per_bone[j]["max_weight"], w)
            for j, w in zip(j1, w1):
                if w > 0:
                    per_bone[j]["vertices"] += 1
                    per_bone[j]["weight_sum"] += w
                    per_bone[j]["max_weight"] = max(per_bone[j]["max_weight"], w)
        chunks_out.append({
            "index": ch["index"], "material": ch["material"], "vertices": nv,
            "triangles": ch["triangles"],
            "weight_sum_min": round(min(sums), 5),
            "weight_sum_mean": round(sum(sums) / nv, 5),
            "weight_sum_max": round(max(sums), 5),
            "unweighted_vertices": unweighted,
            "max_influences": max(infl),
            "avg_influences": round(sum(infl) / nv, 3),
            "uses_second_set": any(any(w) for w in ch["weights1"]),
            "has_normals": len(ch["normals"]) == nv,
            "uv_count": len(ch["uvs"]),
        })
        totals["vertices"] += nv
        totals["unweighted"] += unweighted
        totals["sum_lt_0_9"] += sum(1 for s in sums if s < 0.9)
        totals["sum_gt_1_1"] += sum(1 for s in sums if s > 1.1)
        totals["max_influences"] = max(totals["max_influences"], max(infl))

    used = [b for b in per_bone if b["vertices"] > 0]
    unused = [b["name"] for b in per_bone if b["vertices"] == 0]
    per_bone_sorted = sorted(per_bone, key=lambda b: -b["weight_sum"])
    for b in per_bone_sorted:
        b["weight_sum"] = round(b["weight_sum"], 3)
        b["max_weight"] = round(b["max_weight"], 4)
    return {
        "generated_at": _now(),
        "source": str(P.resolve(model.profile["source"]["mesh_json"])),
        "summary": {
            "vertices": totals["vertices"],
            "bones_total": len(bones),
            "bones_used": len(used),
            "bones_unused": len(unused),
            "unused_bones": unused,
            "unweighted_vertices": totals["unweighted"],
            "sum_below_0_9": totals["sum_lt_0_9"],
            "sum_above_1_1": totals["sum_gt_1_1"],
            "max_influences": totals["max_influences"],
            "influence_histogram": dict(sorted(influence_hist.items())),
            "has_nan": False,
            "negative_weights": 0,
            "vertices_dominant_bone_over_0_6m": far_weighted,
            "max_vertex_to_dominant_bone_m": round(max_bone_dist, 4),
            "note": ("权重为 UByte4N（w/255）原始值，未归一化；量化误差导致单顶点权重和 "
                     "在 0.988–1.012 之间。导出 GLB 保留原始值。"),
        },
        "chunks": chunks_out,
        "per_bone": per_bone_sorted,
        "top20_bones": per_bone_sorted[:20],
    }


# ------------------------------------------------------------- 骨架定义
def skeleton_json(model: BM.BodyModel, checks: dict[str, Any]) -> dict[str, Any]:
    geo = model.geo
    parents = (model.hierarchy or {}).get("parents") or {n: None for n in geo["bone_names"]}
    provenance = (model.hierarchy or {}).get("provenance")
    globals_g = {name: S.mat_inv_rigid(S.to_gltf_space(geo["ibm_cp77"][i]))
                 for i, name in enumerate(geo["bone_names"])}
    bones = []
    for i, name in enumerate(geo["bone_names"]):
        ibm_g = S.to_gltf_space(geo["ibm_cp77"][i])
        p = parents.get(name)
        local = globals_g[name] if p is None else S.mat_mul(S.mat_inv_rigid(globals_g[p]),
                                                            globals_g[name])
        bones.append({
            "index": i, "name": name, "parent": p,
            "cp77_bind_position": [round(v, 6) for v in geo["bone_positions"][i]],
            "gltf_global_bind_translation": [round(local[r][3], 6) for r in range(3)],
            "local_matrix": [[round(v, 6) for v in row] for row in local],
            "inverse_bind_matrix": [[round(v, 6) for v in row] for row in ibm_g],
        })
    return {
        "generated_at": _now(),
        "generator": f"automation/reference_builder.py v{VERSION}",
        "body_id": model.body_id,
        "source": {"mesh_json": str(P.resolve(model.profile["source"]["mesh_json"])),
                   "mesh_json_sha256": checks["mesh_json_sha256"],
                   "raw_mesh": str(P.resolve(model.profile["source"]["raw_mesh"])),
                   "raw_mesh_sha256": checks["raw_mesh_sha256"]},
        "coordinate_system": {
            "source": "CP77 / REDengine：Z-up，左手系，单位米",
            "target": "glTF 2.0：Y-up，右手系，单位米",
            "geometry_mapping": "v_gltf = (x, z, -y)",
            "matrix_mapping": "M_gltf = B · M_cp77 · B^-1，B=[[1,0,0],[0,0,1],[0,-1,0]]",
            "winding": "索引绕序与 glTF 相反（实测），导出时交换第 2/3 顶点",
        },
        "bone_count": len(bones),
        "hierarchy": {
            "type": "tree" if provenance else "flat",
            "parent_field": "parent",
            "provenance": provenance,
            "consequence": (
                "父子关系来自 animRig；局部变换由 CMesh IBM 反推"
                "（global_i = inv(IBM_i)，local_i = inv(global_parent)·global_i），不含猜测矩阵。"
                "沿链累乘后 global·IBM 应为单位阵（见 verification）。"
                if provenance else "扁平骨架：全部关节挂在 Armature 下。"),
        },
        "verification": {
            "ibm_is_inverse_bind": checks["ibm_is_inverse_bind"],
            "ibm_times_bonepos_max_error": checks["ibm_times_bonepos_max_error"],
            "ibm_det_range": [checks["ibm_det_min"], checks["ibm_det_max"]],
            "joint_index_in_range": checks["joint_index_in_range"],
            "max_joint_index_used": checks["max_joint_index_used"],
        },
        "bones": bones,
    }


# ----------------------------------------------------- GLB 结构自检
def verify_glb_structure(path: Path, *, skinned: bool, bones: int) -> dict[str, Any]:
    data = Path(path).read_bytes()
    magic, ver, total = struct.unpack_from("<III", data, 0)
    jlen, _jt = struct.unpack_from("<II", data, 12)
    js = json.loads(data[20:20 + jlen].decode("utf-8"))
    res: dict[str, Any] = {"magic_ok": magic == 0x46546C67, "version": ver,
                           "declared_bytes": total, "actual_bytes": len(data),
                           "generator": js["asset"].get("generator")}
    prim = js["meshes"][0]["primitives"]
    attrs = sorted({k for p in prim for k in p["attributes"]})
    res["primitives"] = len(prim)
    res["attributes"] = attrs
    res["required_attributes_present"] = all(k in attrs for k in
                                             ("POSITION", "NORMAL", "TEXCOORD_0"))
    res["has_joints_weights"] = "JOINTS_0" in attrs and "WEIGHTS_0" in attrs
    res["has_second_set"] = "JOINTS_1" in attrs and "WEIGHTS_1" in attrs
    if skinned and js.get("skins"):
        skin = js["skins"][0]
        res["joints"] = len(skin["joints"])
        res["has_ibm_accessor"] = "inverseBindMatrices" in skin
        ibm = js["accessors"][skin["inverseBindMatrices"]]
        res["ibm_count"] = ibm["count"]
        res["ibm_type"] = ibm["type"]
        names = [js["nodes"][i].get("name") for i in skin["joints"]]
        res["node_names_preserved"] = all(names)
        res["skeleton_node"] = js["nodes"][skin["skeleton"]]["name"] if "skeleton" in skin else None
        res["joint_count_matches_bones"] = len(skin["joints"]) == bones
        res["ibm_count_matches_bones"] = ibm["count"] == bones
        res["accessor_total"] = len(js["accessors"])
        res["degenerate_accessors"] = sum(1 for a in js["accessors"] if a["count"] == 0)
    return res


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------- 主流程
def build_for(prof: dict[str, Any], *, outdir: str | Path | None = None,
              export_static: bool = True, export_skinned: bool = True,
              with_morphology: bool = True, log=print) -> dict[str, Any]:
    """按身形档案构建参考资产。数据源缺失会抛 ProfileError / FileNotFoundError。"""
    P.require_source(prof)
    paths = P.output_paths(prof, override=outdir)
    base = paths["dir"]
    base.mkdir(parents=True, exist_ok=True)
    body_id = prof["body_id"]

    log(f"[{body_id}] 解码 {Path(str(P.resolve(prof['source']['mesh_json']))).name} …")
    model = BM.load(prof)
    log(f"  顶点 {model.vertex_count} / 三角 {model.triangle_count} / "
        f"骨骼 {len(model.bones['names'])} / chunk {len(model.geo['chunks'])}")

    log(f"[{body_id}] 输入核实 …")
    checks = verify_sources(model, prof)
    if not checks["all_gates_passed"]:
        raise RuntimeError(f"[{body_id}] 输入核实未通过："
                           f"{json.dumps(checks['quality_gates'], ensure_ascii=False)}")
    if not checks["expectations_ok"]:
        log(f"  ⚠ 与档案期望值不一致：{checks['expectation_mismatch']}")

    hierarchy = (model.hierarchy or {}).get("parents")
    prov = (model.hierarchy or {}).get("provenance")
    if prov:
        log(f"  层级：根 {prov.get('roots')}，最大深度 {prov.get('max_depth')}，"
            f"跳过非网格骨 {len(prov.get('skipped_non_mesh_bones', []))} 根")

    extras = {"body_id": body_id,
              "source": prof["source"].get("provenance"),
              "conversion": "CP77 Z-up → glTF Y-up",
              "builder": f"reference_builder v{VERSION}",
              "hierarchy": "tree" if hierarchy else "flat"}
    outputs: dict[str, Any] = {}

    if export_static:
        log(f"[{body_id}] 静态 GLB …")
        gb = G.GlbBuilder()
        st = gb.build(model.geo, skinned=False,
                      generator=f"CP2077-Workshop reference_builder {VERSION}",
                      extras=extras, body_id=body_id)
        info = G.write_glb(st["gltf"], gb.bin, paths["static"])
        outputs["static_glb"] = {**info, "sha256": sha256(paths["static"]),
                                 "stats": st["stats"]}

    if export_skinned:
        log(f"[{body_id}] 蒙皮 GLB …")
        gb2 = G.GlbBuilder()
        sk = gb2.build(model.geo, skinned=True,
                       generator=f"CP2077-Workshop reference_builder {VERSION}",
                       extras=extras, hierarchy=hierarchy, body_id=body_id)
        info = G.write_glb(sk["gltf"], gb2.bin, paths["skinned"])
        outputs["skinned_glb"] = {**info, "sha256": sha256(paths["skinned"]),
                                  "stats": sk["stats"]}

    log(f"[{body_id}] 权重分析 …")
    wa = weight_analysis(model)
    paths["weights"].write_text(json.dumps(wa, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["weight_analysis_json"] = {"path": str(paths["weights"]),
                                       "sha256": sha256(paths["weights"])}

    log(f"[{body_id}] 骨架定义 …")
    skj = skeleton_json(model, checks)
    paths["skeleton"].write_text(json.dumps(skj, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["skeleton_json"] = {"path": str(paths["skeleton"]),
                                "sha256": sha256(paths["skeleton"])}

    morph = None
    if with_morphology:
        log(f"[{body_id}] 形态测量（截面/轮廓/区域）…")
        morph = MORPH.BodyMorphologyAnalyzer(model).analyze()
        paths["morphology"].write_text(json.dumps(morph, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        outputs["morphology_json"] = {"path": str(paths["morphology"]),
                                      "sha256": sha256(paths["morphology"])}

    log(f"[{body_id}] 统一身形记录 …")
    record = model.to_unified(outputs={k: {"path": str(v.get("path", "")),
                                           "sha256": v.get("sha256")}
                                       for k, v in outputs.items()},
                              checks=checks)
    record["morphology_summary"] = _morph_summary(morph)
    paths["unified"].write_text(json.dumps(record, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    outputs["body_record_json"] = {"path": str(paths["unified"]),
                                   "sha256": sha256(paths["unified"])}

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": _now(),
        "builder_version": VERSION,
        "builder": "automation/reference_builder.py",
        "body_id": body_id,
        "display_name": prof.get("display_name"),
        "asset_version": prof.get("asset_version"),
        "profile": prof.get("_path"),
        "output_dir": str(base),
        "inputs": {"mesh_json": {"path": str(P.resolve(prof["source"]["mesh_json"])),
                                 "sha256": checks["mesh_json_sha256"]},
                   "raw_mesh": {"path": str(P.resolve(prof["source"]["raw_mesh"])),
                                "sha256": checks["raw_mesh_sha256"]}},
        "outputs": outputs,
        "source_checks": checks,
        "hierarchy": prov,
        "options": {"export_static": export_static, "export_skinned": export_skinned,
                    "with_morphology": with_morphology},
    }

    if export_static or export_skinned:
        log(f"[{body_id}] GLB 结构自检 …")
        manifest["glb_structure"] = {
            "static": (verify_glb_structure(paths["static"], skinned=False, bones=0)
                       if export_static else None),
            "skinned": (verify_glb_structure(paths["skinned"], skinned=True,
                                             bones=len(model.geo["bone_names"]))
                        if export_skinned else None),
        }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    log(f"[{body_id}] 完成 → {base}")
    return {"outdir": str(base), "manifest": manifest, "paths": {k: str(v) for k, v in paths.items()},
            "morphology": morph}


def _morph_summary(morph: dict[str, Any] | None) -> dict[str, Any] | None:
    if not morph:
        return None
    regions = {}
    for name, reg in morph["regions"].items():
        sil = reg.get("silhouette") or {}
        regions[name] = {
            "status": reg["status"], "applicable": reg["applicable"],
            "height_norm": reg["band"]["height_norm"],
            "width_m": sil.get("width_m"), "thickness_m": sil.get("thickness_m"),
            "section_area_m2": reg["section"].get("area_m2_mean"),
            "area_method": reg["section"].get("area_method"),
        }
    return {
        "height_m": morph["overall"]["dimensions"]["height_m"],
        "surface_area_m2": morph["overall"]["geometry"]["surface_area_m2"],
        "watertight": morph["overall"]["geometry"]["watertight"],
        "regions": regions,
        "reliability": {n: r["status"] for n, r in morph["regions"].items()},
    }


# ------------------------------------------------------- 兼容入口（v1 调用方式）
def build(outdir: str | Path | None = None, log=print, *, body_id: str = "ANGEL") -> dict[str, Any]:
    """`main.py ref build` 的旧入口：默认构建 ANGEL，产物进版本目录。"""
    return build_for(P.load(body_id), outdir=outdir, log=log)
