"""生成带蒙皮的 glTF 2.0 (GLB)：POSITION/NORMAL/TEXCOORD_0/JOINTS_0..1/WEIGHTS_0..1 + Skin + IBM。

坐标与矩阵约定（本文件唯一事实来源）：
- CP77 为 Z-up，glTF 为 Y-up：v_gltf = B @ v_cp77，B = [[1,0,0],[0,0,1],[0,-1,0]]。
- 变换矩阵同步共轭：M_gltf = B @ M_cp77 @ B^-1。
- boneRigMatrices 已验证为逆绑定矩阵 IBM_cp77，故 IBM_gltf = B @ IBM_cp77 @ B^-1。
- 本机数据不含骨骼父子关系（CMesh 无该字段、归档内无 .rig、游戏本体缺失），
  因此关节挂在单一 Armature 节点下（扁平），每个关节的局部变换取其全局绑定矩阵。
  该选择可被数学验证：local @ IBM = I，静止姿势下蒙皮结果与静态网格逐点一致。
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

from . import cp77_skin as S

FLOAT = 5126
UNSIGNED_BYTE = 5121
UNSIGNED_SHORT = 5123
UNSIGNED_INT = 5125
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963


class GlbBuilder:
    def __init__(self) -> None:
        self.bin = bytearray()
        self.buffer_views: list[dict] = []
        self.accessors: list[dict] = []
        self.meshes: list[dict] = []
        self.nodes: list[dict] = []
        self.materials: list[dict] = []
        self.skins: list[dict] = []
        self.messages: list[str] = []

    # ------------------------------------------------------------ 底层
    def _view(self, data: bytes, target: int) -> int:
        # 4 字节对齐
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin.extend(data)
        self.buffer_views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data),
                                  "target": target})
        return len(self.buffer_views) - 1

    def _accessor(self, view: int, comp_type: int, count: int,
                  type_: str, minmax: bool = False, min_v=None, max_v=None) -> int:
        acc = {"bufferView": view, "componentType": comp_type, "count": count,
               "type": type_}
        if minmax:
            acc["min"], acc["max"] = min_v, max_v
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def add_floats(self, values: list[tuple], type_: str, target=ARRAY_BUFFER,
                   minmax=False) -> int:
        comps = {"VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[type_]
        flat: list[float] = []
        for v in values:
            flat.extend(v)
        data = struct.pack(f"<{len(flat)}f", *flat)
        view = self._view(data, target)
        mn = mx = None
        if minmax:
            mn = [min(v[i] for v in values) for i in range(comps)]
            mx = [max(v[i] for v in values) for i in range(comps)]
            mn = [round(x, 6) for x in mn]
            mx = [round(x, 6) for x in mx]
        return self._accessor(view, FLOAT, len(values), type_, minmax, mn, mx)

    def add_ubytes(self, values: list[tuple], type_: str = "VEC4",
                   target=ARRAY_BUFFER) -> int:
        data = bytes(b for v in values for b in v)
        view = self._view(data, target)
        return self._accessor(view, UNSIGNED_BYTE, len(values), type_)

    def add_indices(self, indices: list[int], vertex_count: int) -> int:
        if vertex_count <= 65535:
            data = struct.pack(f"<{len(indices)}H", *indices)
            comp = UNSIGNED_SHORT
        else:
            data = struct.pack(f"<{len(indices)}I", *indices)
            comp = UNSIGNED_INT
        view = self._view(data, ELEMENT_ARRAY_BUFFER)
        return self._accessor(view, comp, len(indices), "SCALAR")

    # ------------------------------------------------------------ 组装
    def build(self, geo: dict[str, Any], *, skinned: bool,
              generator: str, extras: dict | None = None,
              hierarchy: dict[str, str | None] | None = None,
              body_id: str = "ANGEL") -> dict[str, Any]:
        bones = geo["bone_names"]
        ibm_cp77 = geo["ibm_cp77"]
        if skinned and len(ibm_cp77) != len(bones):
            raise ValueError(f"骨骼数 {len(bones)} 与 IBM 数 {len(ibm_cp77)} 不一致，停止导出")

        armature_index = 0
        self.nodes.append({"name": f"{body_id}_Armature", "children": []})
        joint_nodes: list[int] = []
        ibm_gltf: list[list[float]] = []
        chain_error = 0.0
        if skinned:
            globals_: list[list[float]] = []
            for i, name in enumerate(bones):
                ibm_g = S.to_gltf_space(ibm_cp77[i])
                globals_.append(S.mat_inv_rigid(ibm_g))
                ibm_gltf.append(ibm_g)

            index_of = {n: i for i, n in enumerate(bones)}
            if hierarchy:
                missing = [n for n in bones if n not in hierarchy]
                if missing:
                    raise ValueError(f"层级缺少 {len(missing)} 根骨：{missing[:5]}")
                for i, name in enumerate(bones):
                    p = hierarchy[name]
                    if p is None:
                        local = globals_[i]
                    else:
                        if p not in index_of:
                            raise ValueError(f"骨骼 {name} 的父级 {p} 不在骨骼列表内")
                        local = S.mat_mul(S.mat_inv_rigid(globals_[index_of[p]]), globals_[i])
                    self.nodes.append({"name": name, "matrix": _col_major(local)})
                    joint_nodes.append(len(self.nodes) - 1)
                for i, name in enumerate(bones):
                    p = hierarchy[name]
                    if p is None:
                        self.nodes[armature_index]["children"].append(joint_nodes[i])
                    else:
                        self.nodes[joint_nodes[index_of[p]]].setdefault("children", []).append(
                            joint_nodes[i])
                acc: dict[str, list[list[float]]] = {}

                def walk(n: str) -> list[list[float]]:
                    if n in acc:
                        return acc[n]
                    node = self.nodes[joint_nodes[index_of[n]]]
                    m = _from_col_major(node["matrix"])
                    p = hierarchy[n]
                    total = m if p is None else S.mat_mul(walk(p), m)
                    acc[n] = total
                    return total

                for i, name in enumerate(bones):
                    prod = S.mat_mul(walk(name), ibm_gltf[i])
                    chain_error = max(chain_error, max(
                        abs(prod[r][c] - (1.0 if r == c else 0.0))
                        for r in range(4) for c in range(4)))
                if chain_error > 1e-4:
                    raise ValueError(
                        f"层级累乘后 global·IBM 偏离单位阵 {chain_error:.6g}，停止导出")
            else:
                for i, name in enumerate(bones):
                    local = globals_[i]
                    prod = S.mat_mul(local, ibm_gltf[i])
                    err = max(abs(prod[r][c] - (1.0 if r == c else 0.0))
                              for r in range(4) for c in range(4))
                    if err > 1e-4:
                        raise ValueError(f"骨骼 {name} 的 local@IBM 偏离单位阵 {err:.6g}，停止导出")
                    self.nodes.append({"name": name, "matrix": _col_major(local)})
                    joint_nodes.append(len(self.nodes) - 1)
                self.nodes[armature_index]["children"] = joint_nodes

        # ---- 材质 ----
        for mname in geo["materials"]:
            self.materials.append({"name": mname,
                                   "pbrMetallicRoughness": {"baseColorFactor": [0.82, 0.72, 0.66, 1.0],
                                                            "metallicFactor": 0.0,
                                                            "roughnessFactor": 0.65}})

        # ---- 网格 ----
        primitives = []
        stats = {"vertices": 0, "triangles": 0, "primitives": 0, "second_set_primitives": 0}
        for ch in geo["chunks"]:
            pos_g = [(p[0], p[2], -p[1]) for p in ch["positions"]]
            nrm_g = [(n[0], n[2], -n[1]) for n in ch["normals"]]
            uv = ch["uvs"]
            # 绕序：CP77 与 glTF 相反（实测法线点积 -1），交换第 2/3 顶点
            src = ch["indices"]
            idx = []
            for t in range(0, len(src) - 2, 3):
                idx.extend((src[t], src[t + 2], src[t + 1]))

            attrs = {
                "POSITION": self.add_floats(pos_g, "VEC3", minmax=True),
                "NORMAL": self.add_floats(nrm_g, "VEC3"),
                "TEXCOORD_0": self.add_floats(uv, "VEC2"),
            }
            if skinned:
                attrs["JOINTS_0"] = self.add_ubytes(ch["joints0"])
                attrs["WEIGHTS_0"] = self.add_floats(ch["weights0"], "VEC4")
                if any(any(w) for w in ch["weights1"]):
                    attrs["JOINTS_1"] = self.add_ubytes(ch["joints1"])
                    attrs["WEIGHTS_1"] = self.add_floats(ch["weights1"], "VEC4")
                    stats["second_set_primitives"] += 1
            prim = {"attributes": attrs,
                    "indices": self.add_indices(idx, len(pos_g)),
                    "material": ch["material_index"] if ch["material_index"] is not None else 0,
                    "mode": 4}
            primitives.append(prim)
            stats["vertices"] += len(pos_g)
            stats["triangles"] += len(idx) // 3
            stats["primitives"] += 1

        self.meshes.append({"name": f"{body_id}_Body", "primitives": primitives})
        mesh_node = {"name": f"{body_id}_Body", "mesh": 0}
        self.nodes.append(mesh_node)
        mesh_node_index = len(self.nodes) - 1

        if skinned:
            ibm_flat = struct.pack(f"<{len(ibm_gltf) * 16}f",
                                   *[c for m in ibm_gltf for c in _col_major(m)])
            view = self._view(ibm_flat, ARRAY_BUFFER)
            ibm_acc = self._accessor(view, FLOAT, len(ibm_gltf), "MAT4")
            self.skins.append({"name": f"{body_id}_Skin", "joints": joint_nodes,
                               "inverseBindMatrices": ibm_acc,
                               "skeleton": armature_index})
            mesh_node["skin"] = 0
            self.nodes[mesh_node_index]["skin"] = 0

        gltf = {
            "asset": {"version": "2.0", "generator": generator,
                      "copyright": "Hyst Angel BodyMod 3.0.0 — geometry derived locally; "
                                   "not for redistribution"},
            "scene": 0,
            # skinned 时网格节点也必须挂进场景根：否则 Blender 会把它丢到
            # "Orphan Nodes" 集合（不参与渲染），实测 glTF 导入后网格不可见。
            "scenes": [{"nodes": ([armature_index, mesh_node_index] if skinned
                                  else [mesh_node_index])}],
            "nodes": self.nodes,
            "meshes": self.meshes,
            "materials": self.materials,
            "accessors": self.accessors,
            "bufferViews": self.buffer_views,
            "buffers": [{"byteLength": len(self.bin)}],
        }
        if skinned:
            gltf["skins"] = self.skins
        if extras:
            gltf["asset"]["extras"] = extras
        stats["binary_bytes"] = len(self.bin)
        stats["bones"] = len(bones) if skinned else 0
        stats["hierarchy"] = ("tree" if (skinned and hierarchy) else
                              ("flat" if skinned else "none"))
        stats["hierarchy_chain_error"] = (round(chain_error, 9)
                                          if (skinned and hierarchy) else None)
        return {"gltf": gltf, "stats": stats,
                "ibm_dets": [round(_det3(m), 6) for m in ibm_gltf[:5]] if skinned else []}


def _from_col_major(v: list[float]) -> list[list[float]]:
    return [[v[c * 4 + r] for c in range(4)] for r in range(4)]


def _col_major(m: list[list[float]]) -> list[float]:
    """行主序 4x4 → glTF 列主序 16 元。"""
    return [m[r][c] for c in range(4) for r in range(4)]


def _det3(m) -> float:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def write_glb(gltf: dict, bin_bytes: bytes, path: Path) -> dict[str, Any]:
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(js) % 4:
        js += b" "
    bn = bytes(bin_bytes)
    while len(bn) % 4:
        bn += b"\x00"
    total = 12 + 8 + len(js) + 8 + len(bn)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(bn), 0x004E4942) + bn
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(bytes(out))
    return {"path": str(path), "bytes": len(out), "json_bytes": len(js),
            "bin_bytes": len(bn)}
