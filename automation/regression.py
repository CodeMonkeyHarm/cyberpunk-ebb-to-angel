"""回归比对：新版本产物是否与已冻结的旧版本等价。

判据分三层，全部要过：
1. **几何字节**：GLB 里每个 primitive 的 POSITION / NORMAL / TEXCOORD_0 / JOINTS / WEIGHTS /
   indices 的原始字节 sha256 必须与旧版一致（顶点顺序、量化、绕序完全没变）。
2. **骨架**：骨名顺序、父级关系、IBM（±1e-6）一致。
3. **权重统计**：无权重顶点数、最大影响数、权重和区间一致。

允许且必须**解释**的差异：`asset.generator` 字符串、`scenes[].nodes` 结构、
以及新增的产物文件（形态测量、统一记录）。
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
ATTRS = ("POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0", "JOINTS_1", "WEIGHTS_1")


def _glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    magic, _ver, _total = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"{path} 不是 GLB")
    off = 12
    js, bin_chunk = None, b""
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        body = data[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(body.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_chunk = body
        off += 8 + clen + ((4 - clen % 4) % 4)
    return js, bin_chunk


def _accessor_bytes(js: dict, bin_chunk: bytes, idx: int) -> bytes:
    acc = js["accessors"][idx]
    view = js["bufferViews"][acc["bufferView"]]
    comp_size = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}[acc["componentType"]]
    n_comp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[acc["type"]]
    stride = view.get("byteStride") or comp_size * n_comp
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    if stride == comp_size * n_comp:
        return bin_chunk[start: start + stride * acc["count"]]
    out = bytearray()
    for i in range(acc["count"]):
        s = start + i * stride
        out += bin_chunk[s: s + comp_size * n_comp]
    return bytes(out)


def compare_glb(old: Path, new: Path) -> dict[str, Any]:
    js_o, bin_o = _glb(old)
    js_n, bin_n = _glb(new)
    res: dict[str, Any] = {"old": str(old), "new": str(new)}

    prims_o = js_o["meshes"][0]["primitives"]
    prims_n = js_n["meshes"][0]["primitives"]
    res["primitive_count"] = {"old": len(prims_o), "new": len(prims_n),
                              "equal": len(prims_o) == len(prims_n)}

    attrs: dict[str, Any] = {}
    mismatch: list[str] = []
    for i, (po, pn) in enumerate(zip(prims_o, prims_n)):
        for name in ATTRS:
            ao, an = po["attributes"].get(name), pn["attributes"].get(name)
            if ao is None and an is None:
                continue
            key = f"prim{i}.{name}"
            if ao is None or an is None:
                mismatch.append(key)
                attrs[key] = "PRESENCE_DIFFERS"
                continue
            ho = hashlib.sha256(_accessor_bytes(js_o, bin_o, ao)).hexdigest()
            hn = hashlib.sha256(_accessor_bytes(js_n, bin_n, an)).hexdigest()
            attrs[key] = "identical" if ho == hn else "DIFFER"
            if ho != hn:
                mismatch.append(key)
        io, inn = po.get("indices"), pn.get("indices")
        if io is not None and inn is not None:
            ho = hashlib.sha256(_accessor_bytes(js_o, bin_o, io)).hexdigest()
            hn = hashlib.sha256(_accessor_bytes(js_n, bin_n, inn)).hexdigest()
            attrs[f"prim{i}.indices"] = "identical" if ho == hn else "DIFFER"
            if ho != hn:
                mismatch.append(f"prim{i}.indices")

    if js_o.get("skins") and js_n.get("skins"):
        so, sn = js_o["skins"][0], js_n["skins"][0]
        ibm_o = hashlib.sha256(_accessor_bytes(js_o, bin_o, so["inverseBindMatrices"])).hexdigest()
        ibm_n = hashlib.sha256(_accessor_bytes(js_n, bin_n, sn["inverseBindMatrices"])).hexdigest()
        attrs["skin.IBM"] = "identical" if ibm_o == ibm_n else "DIFFER"
        if ibm_o != ibm_n:
            mismatch.append("skin.IBM")
        res["joints"] = {"old": len(so["joints"]), "new": len(sn["joints"]),
                         "equal": len(so["joints"]) == len(sn["joints"])}

    res["accessors"] = attrs
    res["mismatches"] = mismatch
    res["geometry_identical"] = not mismatch
    res["structure"] = {
        "scene_nodes_old": js_o["scenes"][0]["nodes"],
        "scene_nodes_new": js_n["scenes"][0]["nodes"],
        "generator_old": js_o["asset"].get("generator"),
        "generator_new": js_n["asset"].get("generator"),
        "node_count": {"old": len(js_o["nodes"]), "new": len(js_n["nodes"])},
    }
    return res


def compare_skeleton(old: Path, new: Path, tol: float = 1e-6) -> dict[str, Any]:
    a = json.loads(old.read_text(encoding="utf-8"))
    b = json.loads(new.read_text(encoding="utf-8"))
    na = [x["name"] for x in a["bones"]]
    nb = [x["name"] for x in b["bones"]]
    pa = [x.get("parent") for x in a["bones"]]
    pb = [x.get("parent") for x in b["bones"]]
    max_ibm = 0.0
    for x, y in zip(a["bones"], b["bones"]):
        for r in range(4):
            for c in range(4):
                max_ibm = max(max_ibm, abs(x["inverse_bind_matrix"][r][c]
                                           - y["inverse_bind_matrix"][r][c]))
    return {
        "bone_count": {"old": len(na), "new": len(nb), "equal": len(na) == len(nb)},
        "names_identical": na == nb,
        "parents_identical": pa == pb,
        "ibm_max_abs_diff": round(max_ibm, 12),
        "ibm_within_tol": max_ibm <= tol,
        "identical": na == nb and pa == pb and max_ibm <= tol,
    }


def compare_weights(old: Path, new: Path) -> dict[str, Any]:
    a = json.loads(old.read_text(encoding="utf-8"))["summary"]
    b = json.loads(new.read_text(encoding="utf-8"))["summary"]
    keys = ("vertices", "unweighted_vertices", "max_influences", "bones_used",
            "weight_sum_min", "weight_sum_max")
    diffs = {k: {"old": a.get(k), "new": b.get(k)} for k in keys if a.get(k) != b.get(k)}
    return {"compared": list(keys), "differences": diffs, "identical": not diffs}


def run(old_dir: str | Path, new_dir: str | Path) -> dict[str, Any]:
    old_dir, new_dir = Path(old_dir), Path(new_dir)
    man_o = json.loads((old_dir / "manifest.json").read_text(encoding="utf-8"))
    man_n = json.loads((new_dir / "manifest.json").read_text(encoding="utf-8"))

    def find(man: dict, key: str, fallback: str) -> Path:
        e = man["outputs"].get(key) or {}
        return Path(e["path"]) if e.get("path") else (
            Path(man.get("output_dir", ".")) / fallback)

    bid = man_n.get("body_id", "ANGEL")
    out: dict[str, Any] = {
        "schema": "cp77.body.regression/v1",
        "generator": f"automation/regression.py v{VERSION}",
        "old_dir": str(old_dir), "new_dir": str(new_dir),
        "versions": {"old": man_o.get("builder_version"), "new": man_n.get("builder_version")},
        "static_glb": compare_glb(find(man_o, "static_glb", f"{bid}_Body_Static.glb"),
                                  find(man_n, "static_glb", f"{bid}_Body_Static.glb")),
        "skinned_glb": compare_glb(find(man_o, "skinned_glb", f"{bid}_Body_Skinned.glb"),
                                   find(man_n, "skinned_glb", f"{bid}_Body_Skinned.glb")),
        "skeleton": compare_skeleton(find(man_o, "skeleton_json", f"{bid}_Skeleton.json"),
                                     find(man_n, "skeleton_json", f"{bid}_Skeleton.json")),
        "weights": compare_weights(find(man_o, "weight_analysis_json",
                                        f"{bid}_Weight_Analysis.json"),
                                   find(man_n, "weight_analysis_json",
                                        f"{bid}_Weight_Analysis.json")),
    }
    st, sk = out["static_glb"], out["skinned_glb"]
    out["verdict"] = {
        "geometry_identical": st["geometry_identical"] and sk["geometry_identical"],
        "skeleton_identical": out["skeleton"]["identical"],
        "weights_identical": out["weights"]["identical"],
        "structural_changes": {
            "scene_nodes": (st["structure"]["scene_nodes_old"]
                            != st["structure"]["scene_nodes_new"]),
            "generator": (st["structure"]["generator_old"]
                          != st["structure"]["generator_new"]),
            "new_outputs": sorted(set(man_n["outputs"]) - set(man_o["outputs"])),
        },
    }
    out["verdict"]["pass"] = (out["verdict"]["geometry_identical"]
                              and out["verdict"]["skeleton_identical"]
                              and out["verdict"]["weights_identical"])
    return out
