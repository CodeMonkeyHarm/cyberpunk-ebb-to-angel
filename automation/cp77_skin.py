"""CMesh（WolvenKit serialize 的 .mesh.json）→ 完整蒙皮几何解码器。

与旧工程 wbx/cp77mesh.py 的区别（都是实测结论）：
1. 法线：PS_Normal 是 PT_Dec4（10:10:10:2），实际编码为 **无符号 10bit → [-1,1]**
   （v/1023*2-1），与几何法线点积 ≈ -1 → 说明索引绕序与 glTF 相反。
2. 蒙皮：最多 **8 个影响**（PS_SkinIndices[0..1] + PS_SkinWeights[0..1]），
   不能只取前 4 个，否则权重和掉到 0.667（实测）。
3. 偏移必须按每个 chunk 的 vertexLayout 推导（stride 24 与 32 的权重位置不同）。
4. boneRigMatrices 已验证为 **逆绑定矩阵（IBM）**：M·bonePos=0、inv(M)原点=bonePos、
   旋转行列式=1.0（167 骨全部命中）。

坐标：CP77 为 Z-up / 米制。glTF 用 Y-up，转换矩阵 B 满足 v_gltf=(x, z, -y)。
"""
from __future__ import annotations

import base64
import json
import math
import struct
from pathlib import Path
from typing import Any

TYPE_SIZE = {
    "PT_Short4N": 8, "PT_Short2N": 4, "PT_UShort4N": 8, "PT_UShort2N": 4,
    "PT_UByte4": 4, "PT_UByte4N": 4, "PT_UByte2": 2, "PT_UByte2N": 2,
    "PT_Float16_2": 4, "PT_Float16_4": 8, "PT_Float": 4, "PT_Float2": 8,
    "PT_Float3": 12, "PT_Float4": 16, "PT_Dec4": 4, "PT_Color": 4,
    "PT_UInt4": 16, "PT_Int4": 16, "PT_UInt": 4, "PT_Int": 4,
}


# ------------------------------------------------------------------ 小工具
def v4(d) -> tuple[float, float, float, float]:
    return (d.get("X", 0.0), d.get("Y", 0.0), d.get("Z", 0.0), d.get("W", 1.0))


def cname(v):
    return v.get("$value") if isinstance(v, dict) else v


def stream_layout(chunk) -> tuple[dict, list]:
    vl = chunk["chunkVertices"]["vertexLayout"]
    strides = vl.get("slotStrides", {}).get("Elements", [])
    elems = vl.get("elements", {}).get("Elements", [])
    out: dict[int, list] = {}
    cursor: dict[int, int] = {}
    for e in elems:
        st = e.get("streamIndex", 0)
        t = e.get("type", "PT_Invalid")
        size = TYPE_SIZE.get(t, 0)
        if not size:
            continue
        off = cursor.get(st, 0)
        out.setdefault(st, []).append((e.get("usage"), e.get("usageIndex", 0), t, off, size))
        cursor[st] = off + size
    return out, strides


def _dec4_normals(u: int) -> tuple[float, float, float]:
    """PT_Dec4 → 法线（实测：无符号 10bit 映射到 [-1,1]）。"""
    x = u & 0x3FF
    y = (u >> 10) & 0x3FF
    z = (u >> 20) & 0x3FF
    return (x / 1023.0 * 2.0 - 1.0, y / 1023.0 * 2.0 - 1.0, z / 1023.0 * 2.0 - 1.0)


def _half(b: bytes, off: int) -> float:
    return struct.unpack_from("<e", b, off)[0]


# ------------------------------------------------------------------ 矩阵
def mat_from_rows(rows: list[list[float]]) -> list[list[float]]:
    return [list(r) for r in rows]


def cmesh_matrix(m) -> list[list[float]]:
    """WolvenKit Matrix → 4x4（列 = X/Y/Z/W 四个 Vector4）。"""
    cols = [v4(m[k]) for k in ("X", "Y", "Z", "W")]
    return [[cols[0][r], cols[1][r], cols[2][r], cols[3][r]] for r in range(4)]


def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def mat_inv_rigid(m):
    """刚体/正交矩阵求逆：R^T 与 -R^T t（行列式必须为 1，否则抛错）。"""
    R = [[m[r][c] for c in range(3)] for r in range(3)]
    t = [m[r][3] for r in range(3)]
    det = (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1])
           - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
           + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))
    if abs(det - 1.0) > 1e-3:
        raise ValueError(f"矩阵不是刚体变换（det={det}），拒绝猜测逆矩阵")
    Rt = [[R[c][r] for c in range(3)] for r in range(3)]
    ti = [-sum(Rt[r][k] * t[k] for k in range(3)) for r in range(3)]
    out = [[Rt[0][0], Rt[0][1], Rt[0][2], ti[0]],
           [Rt[1][0], Rt[1][1], Rt[1][2], ti[1]],
           [Rt[2][0], Rt[2][1], Rt[2][2], ti[2]],
           [0.0, 0.0, 0.0, 1.0]]
    return out


# CP77(Z-up) → glTF(Y-up) 的基变换
B_MAT = [[1.0, 0.0, 0.0, 0.0],
         [0.0, 0.0, 1.0, 0.0],
         [0.0, -1.0, 0.0, 0.0],
         [0.0, 0.0, 0.0, 1.0]]
B_INV = [[1.0, 0.0, 0.0, 0.0],
         [0.0, 0.0, -1.0, 0.0],
         [0.0, 1.0, 0.0, 0.0],
         [0.0, 0.0, 0.0, 1.0]]


def to_gltf_space(m):
    return mat_mul(mat_mul(B_MAT, m), B_INV)


# ------------------------------------------------------------------ 解码
def decode(path: str | Path, max_influences: int = 8) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    root = doc["Data"]["RootChunk"]
    blob = root["renderResourceBlob"]["Data"]
    header = blob["header"]
    buf = base64.b64decode(blob["renderBuffer"]["Bytes"])

    qs = v4(header.get("quantizationScale", {}))
    qo = v4(header.get("quantizationOffset", {}))

    bone_names = [cname(b) for b in root.get("boneNames", [])]
    bone_pos = [v4(p)[:3] for p in header.get("bonePositions", [])]
    ibm_cp77 = [cmesh_matrix(m) for m in root.get("boneRigMatrices", [])]

    materials = [cname(m.get("name")) for m in root.get("materialEntries", [])]
    appearances = []
    for a in root.get("appearances", []):
        d = a.get("Data", {})
        appearances.append({"name": cname(d.get("name")),
                            "chunk_materials": [cname(c) for c in d.get("chunkMaterials", [])]})
    chunk_material_names = appearances[0]["chunk_materials"] if appearances else []

    chunks = []
    for ci, ch in enumerate(header.get("renderChunkInfos", [])):
        nv = ch.get("numVertices", 0)
        ni = ch.get("numIndices", 0)
        if not nv:
            continue
        layout, strides = stream_layout(ch)
        offs = ch["chunkVertices"]["byteOffsets"]["Elements"]

        def find(usage, uidx=0):
            for st, items in layout.items():
                for (u, ui, t, off, size) in items:
                    if u == usage and ui == uidx:
                        return st, off, t, size
            return None

        def base_of(usage, uidx=0):
            f = find(usage, uidx)
            if not f:
                return None
            st, off, t, size = f
            stride = strides[st] if st < len(strides) else size
            base = offs[st] if st < len(offs) else 0
            return {"stream": st, "offset": off, "type": t, "stride": stride, "base": base}

        p_pos = base_of("PS_Position")
        if not p_pos:
            continue
        p_uv = base_of("PS_TexCoord", 0)
        p_nrm = base_of("PS_Normal", 0)
        skin_i = [base_of("PS_SkinIndices", k) for k in (0, 1)]
        skin_w = [base_of("PS_SkinWeights", k) for k in (0, 1)]

        positions, normals, uvs = [], [], []
        joints0, weights0, joints1, weights1 = [], [], [], []
        full_sums = []
        fmt_p = "<4h" if p_pos["type"] == "PT_Short4N" else "<4H"
        for i in range(nv):
            o = p_pos["base"] + i * p_pos["stride"] + p_pos["offset"]
            x, y, z, _ = struct.unpack_from(fmt_p, buf, o)
            positions.append((x / 32767.0 * qs[0] + qo[0],
                              y / 32767.0 * qs[1] + qo[1],
                              z / 32767.0 * qs[2] + qo[2]))
            if p_uv:
                uo = p_uv["base"] + i * p_uv["stride"] + p_uv["offset"]
                uvs.append((_half(buf, uo), _half(buf, uo + 2)))
            if p_nrm:
                no = p_nrm["base"] + i * p_nrm["stride"] + p_nrm["offset"]
                u = struct.unpack_from("<I", buf, no)[0]
                normals.append(_dec4_normals(u))

            pairs: list[tuple[int, float]] = []
            for k in (0, 1):
                si, sw = skin_i[k], skin_w[k]
                if not si or not sw:
                    continue
                oi = si["base"] + i * si["stride"] + si["offset"]
                ow = sw["base"] + i * sw["stride"] + sw["offset"]
                if oi + 4 > len(buf) or ow + 4 > len(buf):
                    continue
                idx = struct.unpack_from("<4B", buf, oi)
                wts = struct.unpack_from("<4B", buf, ow)
                for b, w in zip(idx, wts):
                    if w:
                        pairs.append((b, w / 255.0))
            pairs.sort(key=lambda t: -t[1])
            full_sums.append(sum(w for _, w in pairs))
            if max_influences > 4:
                chunk_pairs, rest = pairs[:4], pairs[4:8]
            else:
                chunk_pairs, rest = pairs[:4], []
            j0, w0 = [0] * 4, [0.0] * 4
            for n, (b, w) in enumerate(chunk_pairs):
                j0[n], w0[n] = b, w
            j1, w1 = [0] * 4, [0.0] * 4
            for n, (b, w) in enumerate(rest):
                j1[n], w1[n] = b, w
            joints0.append(j0)
            weights0.append(w0)
            joints1.append(j1)
            weights1.append(w1)

        # 索引（绕序与 glTF 相反，导出时反转）
        ci_info = ch.get("chunkIndices", {})
        ibase = header.get("indexBufferOffset", 0) + ci_info.get("teOffset", 0)
        fmt = ci_info.get("pe", "IBCT_IndexUShort")
        if fmt == "IBCT_IndexUInt":
            indices = list(struct.unpack_from(f"<{ni}I", buf, ibase)) if ibase + ni * 4 <= len(buf) else []
        else:
            indices = list(struct.unpack_from(f"<{ni}H", buf, ibase)) if ibase + ni * 2 <= len(buf) else []
        dropped = sum(1 for i in indices if i >= nv)
        indices = [i for i in indices if i < nv]

        mat_name = chunk_material_names[ci] if ci < len(chunk_material_names) else None
        # 材质索引必须是 materials 数组中的位置（不是 chunk 序号）
        mat_index = materials.index(mat_name) if mat_name in materials else None
        chunks.append({
            "index": ci,
            "material_index": mat_index,
            "material": mat_name,
            "vertex_count": nv,
            "index_count": ni,
            "triangles": len(indices) // 3,
            "dropped_indices": dropped,
            "stride": strides[0] if strides else None,
            "has_second_set": bool(skin_i[1] and skin_w[1]),
            "positions": positions,
            "normals": normals,
            "uvs": uvs,
            "joints0": joints0,
            "weights0": weights0,
            "joints1": joints1,
            "weights1": weights1,
            "weight_sums": full_sums,
            "indices": indices,
        })

    bb = root.get("boundingBox", {})
    return {
        "source": str(path),
        "object_type": root.get("objectType"),
        "geometry_hash": root.get("geometryHash"),
        "declared_bbox": {"min": [v4(bb.get("Min", {}))[k] for k in range(3)],
                          "max": [v4(bb.get("Max", {}))[k] for k in range(3)]},
        "quantization": {"scale": qs[:3], "offset": qo[:3]},
        "materials": materials,
        "appearances": appearances,
        "bone_names": bone_names,
        "bone_positions": bone_pos,
        "ibm_cp77": ibm_cp77,
        "chunks": chunks,
        "vertex_count": sum(c["vertex_count"] for c in chunks),
        "triangle_count": sum(c["triangles"] for c in chunks),
    }
