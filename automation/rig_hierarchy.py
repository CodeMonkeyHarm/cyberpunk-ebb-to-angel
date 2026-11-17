"""从 basegame 的 animRig 提取骨骼父子关系，并投影到 CMesh 的骨骼集合上。

数据源（实测，2026-11-15）：
    basegame_1_engine.archive
      base\\characters\\entities\\player\\deformations_rigs_wa\\player_woman_base_deformations.rig
    183 骨，单根 Root，boneParentIndexes 自洽（local = 父级相对，183/183 零误差）

CMesh 的 167 根骨是它的子集（缺失的 16 根是 Root/Head/HandEnd/Heel 等非本网格骨）。
因此把每个骨挂到「最近的、存在于网格中的祖先」，得到 167 节点的真实树，
根为 Hips。矩阵仍全部来自 CMesh 的 IBM，不含任何猜测。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_rig(path: str | Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    rc = doc["Data"]["RootChunk"]
    names = [b["$value"] for b in rc["boneNames"]]
    par = rc["boneParentIndexes"]
    parents = par["Elements"] if isinstance(par, dict) and "Elements" in par else par
    def _elems(v):
        return v["Elements"] if isinstance(v, dict) and "Elements" in v else v

    return {"names": names, "parents": parents, "type": rc.get("$type"),
            "path": str(path), "bone_count": len(names),
            "raw": {"aPoseMS": _elems(rc.get("aPoseMS")),
                    "aPoseLS": _elems(rc.get("aPoseLS"))}}


def project_to_mesh(rig: dict[str, Any], mesh_bones: list[str]) -> dict[str, Any]:
    """返回 {parents: name→parent_name|None, provenance}。"""
    rnames, rpar = rig["names"], rig["parents"]
    ridx = {n: i for i, n in enumerate(rnames)}
    mesh_set = set(mesh_bones)

    missing = [n for n in mesh_bones if n not in ridx]
    if missing:
        raise RuntimeError(f"rig 不包含 {len(missing)} 根网格骨，无法建立层级：{missing[:8]}")

    def parent_of(i: int):
        p = rpar[i]
        return p if isinstance(p, int) and 0 <= p < len(rnames) else None

    parents: dict[str, str | None] = {}
    skipped_intermediate = []
    for name in mesh_bones:
        cur = parent_of(ridx[name])
        origin_parent = rnames[cur] if cur is not None else None
        hops = 0
        while cur is not None and rnames[cur] not in mesh_set:
            skipped_intermediate.append(rnames[cur])
            cur = parent_of(cur)
            hops += 1
            if hops > 256:
                raise RuntimeError(f"骨骼 {name} 的父链异常（>256 层）")
        parents[name] = rnames[cur] if cur is not None else None

    roots = [n for n, p in parents.items() if p is None]
    depth: dict[str, int] = {}

    def d(n: str) -> int:
        if n in depth:
            return depth[n]
        p = parents[n]
        depth[n] = 1 if p is None else d(p) + 1
        return depth[n]

    for n in mesh_bones:
        d(n)

    children: dict[str, int] = {n: 0 for n in mesh_bones}
    for n, p in parents.items():
        if p:
            children[p] += 1

    return {
        "parents": parents,
        "provenance": {
            "source": rig["path"],
            "rig_type": rig["type"],
            "rig_bones": rig["bone_count"],
            "mesh_bones": len(mesh_bones),
            "rig_only_bones": sorted(n for n in rnames if n not in mesh_set),
            "skipped_non_mesh_bones": sorted(set(skipped_intermediate)),
            "roots": roots,
            "max_depth": max(depth.values()),
            "depth_histogram": {k: list(depth.values()).count(k) for k in sorted(set(depth.values()))},
            "bones_with_children": sum(1 for v in children.values() if v > 0),
            "method": "每个网格骨挂到最近的、存在于网格中的祖先；矩阵仍取 CMesh IBM",
        },
    }


def _quat_to_mat(q: dict) -> list[list[float]]:
    x, y, z, w = q["i"], q["j"], q["k"], q["r"]
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def compare_pose(rig: dict[str, Any], mesh_bones: list[str],
                 ibm_cp77: list[list[list[float]]]) -> dict[str, Any]:
    """比 rig 的 aPoseMS 与 CMesh 的 inv(IBM)，判断能否直接使用 rig 矩阵。

    结论（2026-11-15 实测）：**不能**。Angel 身体是自定义身形，绑定姿势与
    vanilla `player_woman_base_deformations` 的 A-pose 逐骨不同（平移中位差 ~5cm，
    最大 5.8cm；旋转元素最大差 0.53）。因此 rig 只用于父子关系，矩阵仍取 CMesh IBM。
    """
    import statistics

    from . import cp77_skin as S

    rnames = rig["names"]
    ridx = {n: i for i, n in enumerate(rnames)}
    ms = rig["raw"]["aPoseMS"]
    ts: list[float] = []
    rs: list[float] = []
    worst_t = {"bone": None, "m": 0.0}
    for i, name in enumerate(mesh_bones):
        t = ms[ridx[name]]["Translation"]
        p = (t.get("X", 0.0), t.get("Y", 0.0), t.get("Z", 0.0))
        inv = S.mat_inv_rigid(ibm_cp77[i])
        r = _quat_to_mat(ms[ridx[name]]["Rotation"])
        et = max(abs(p[k] - inv[k][3]) for k in range(3))
        er = max(abs(r[a][b] - inv[a][b]) for a in range(3) for b in range(3))
        ts.append(et)
        rs.append(er)
        if et > worst_t["m"]:
            worst_t = {"bone": name, "m": round(et, 6)}
    return {
        "bones_compared": len(ts),
        "translation_diff_m": {"max": round(max(ts), 6),
                               "median": round(statistics.median(ts), 6),
                               "over_1mm": sum(1 for x in ts if x > 0.001)},
        "rotation_element_diff": {"max": round(max(rs), 6),
                                  "median": round(statistics.median(rs), 6),
                                  "over_0_01": sum(1 for x in rs if x > 0.01)},
        "worst_translation_bone": worst_t,
        "matrices_usable_from_rig": False,
        "conclusion": ("rig 的 aPoseMS 与 CMesh 的 inv(IBM) 逐骨不同 → rig 仅用于父子关系，"
                       "关节矩阵仍取 CMesh boneRigMatrices"),
    }
