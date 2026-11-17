"""Build an independent v4 dress JSON from v3 using constrained chest repair."""
from __future__ import annotations

import base64
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from automation import body_model as BM, body_profiles as P, regression  # noqa: E402
from automation.cp77_skin import decode, stream_layout, v4  # noqa: E402
from audit.phase3.audit_stella_vertex_attributes import attributes  # noqa: E402
from audit.phase3.prototype_chest_collision import (  # noqa: E402
    diffuse, measure, projected_smooth, topology, unique_edges,
)
from audit.phase3.validate_v2 import as_model  # noqa: E402

SOURCE = ROOT / "audit/phase3/stella/v3/roundtrip_fixed/json/angel_dress.mesh.json"
AUTHOR = ROOT / "audit/phase3/stella/json/angel_dress.mesh.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def normalized(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    return np.divide(v, norm, out=np.zeros_like(v), where=norm > 1e-12)


def recompute_vectors(vertices: np.ndarray, uv: np.ndarray, triangles: np.ndarray,
                      original_tangent: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    _, first = np.unique(np.sort(triangles, axis=1), return_index=True, axis=0)
    tri = triangles[np.sort(first)]
    e1 = vertices[tri[:, 1]] - vertices[tri[:, 0]]
    e2 = vertices[tri[:, 2]] - vertices[tri[:, 0]]
    face = np.cross(e1, e2)
    normals = np.zeros_like(vertices)
    for k in range(3):
        np.add.at(normals, tri[:, k], -face)
    normals = normalized(normals)
    uv1 = uv[tri[:, 1]] - uv[tri[:, 0]]
    uv2 = uv[tri[:, 2]] - uv[tri[:, 0]]
    det = uv1[:, 0] * uv2[:, 1] - uv1[:, 1] * uv2[:, 0]
    valid = np.abs(det) > 1e-8
    face_tangent = np.zeros_like(face)
    face_tangent[valid] = ((e1[valid] * uv2[valid, 1, None]
                            - e2[valid] * uv1[valid, 1, None]) / det[valid, None])
    tangent = np.zeros_like(vertices)
    for k in range(3):
        np.add.at(tangent, tri[:, k], face_tangent)
    tangent = normalized(tangent - normals * np.einsum("ij,ij->i", tangent, normals)[:, None])
    dot = np.einsum("ij,ij->i", tangent, original_tangent)
    tangent[dot < 0] *= -1
    weak = (np.linalg.norm(tangent, axis=1) < 0.5) | (np.abs(dot) < 0.5)
    fallback = original_tangent - normals * np.einsum("ij,ij->i", original_tangent, normals)[:, None]
    tangent[weak] = normalized(fallback[weak])
    return normals, tangent, {"unique_triangles": int(len(tri)),
                               "valid_uv_triangles": int(valid.sum()),
                               "weak_tangent_fallback_vertices": int(weak.sum())}


def packed_dec4(vector: np.ndarray, old: np.ndarray) -> np.ndarray:
    xyz = np.clip(np.rint((np.clip(vector, -1, 1) + 1) / 2 * 1023), 0, 1023).astype(np.uint32)
    return ((old & np.uint32(0xC0000000)) | xyz[:, 0]
            | (xyz[:, 1] << np.uint32(10)) | (xyz[:, 2] << np.uint32(20)))


def diagnostic_positions(path: Path, model) -> np.ndarray:
    document, payload = regression._glb(path)
    mesh, = document["meshes"]
    primitive, = mesh["primitives"]
    accessor = primitive["attributes"]["POSITION"]
    vertices = np.frombuffer(regression._accessor_bytes(document, payload, accessor), "<f4").reshape(-1, 3)
    chunk, = model.geo["chunks"]
    original = np.asarray(chunk["indices"]).reshape(-1, 3)
    packed_indices = primitive["indices"]
    component_type = document["accessors"][packed_indices]["componentType"]
    indices = np.frombuffer(regression._accessor_bytes(document, payload, packed_indices),
                            {5123: "<u2", 5125: "<u4"}[component_type]).reshape(-1, 3)
    if not np.array_equal(indices[:, [0, 2, 1]], original) or len(vertices) != len(model.vertices):
        raise ValueError("Expected the original garment index and vertex order")
    trial = vertices[:, [0, 2, 1]].astype(np.float64)
    trial[:, 1] *= -1
    return trial


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("baseline", "wide"), default="baseline")
    parser.add_argument("--diagnostic-glb", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if bool(args.diagnostic_glb) != bool(args.output_dir):
        parser.error("--diagnostic-glb and --output-dir must be provided together")
    variant = args.diagnostic_glb.stem if args.diagnostic_glb else args.variant
    out_dir = args.output_dir or ROOT / "audit/phase3/stella" / ("v4_wide" if variant == "wide" else "v4")
    out_json = out_dir / "converted_json/angel_dress.mesh.json"
    out_report = out_dir / "build_report.json"
    model = as_model("v4_base", SOURCE)
    body = BM.load(P.load("ANGEL"))
    base = model.vertices.copy()
    triangles = model.triangles
    edges = unique_edges(triangles)
    before = measure(model, body, base)
    if args.diagnostic_glb:
        trial = diagnostic_positions(args.diagnostic_glb, model)
        correction = trial - base
    else:
        z = base[:, 2]
        seeds = before["penetrated"] & (z >= 1.26) & (z <= 1.40)
        active = (z >= (1.18 if variant == "wide" else 1.23)) & (z <= 1.41)
        desired = np.zeros_like(base)
        desired[seeds] = before["normals"][seeds] * (0.001 - before["signed"][seeds])[:, None]
        initial = diffuse(desired, seeds, active, edges, 60)
        correction = projected_smooth(initial, before["signed"], before["normals"],
                                      seeds, active, edges, 700 if variant == "wide" else 300)
        trial = base + correction
    geom = topology(base, trial, triangles, edges)
    after = measure(model, body, trial)
    if geom["inverted_index_triangles"] or geom["new_degenerate_index_triangles"] or after["penetration_count"]:
        raise RuntimeError("v4 floating geometry did not pass prototype checks")

    doc = json.loads(SOURCE.read_text(encoding="utf-8"))
    root = doc["Data"]["RootChunk"]
    blob = root["renderResourceBlob"]["Data"]
    header = blob["header"]
    chunk = header["renderChunkInfos"][0]
    if chunk["numVertices"] != len(trial):
        raise RuntimeError("Unexpected vertex count")
    layout, strides = stream_layout(chunk)
    if ([(x[0], x[2]) for x in layout[2]] !=
            [("PS_Normal", "PT_Dec4"), ("PS_Tangent", "PT_Dec4")]):
        raise RuntimeError("Unexpected normal/tangent stream layout")
    offsets = chunk["chunkVertices"]["byteOffsets"]["Elements"]
    buffer = bytearray(base64.b64decode(blob["renderBuffer"]["Bytes"]))
    source_buffer = bytes(buffer)
    count = len(trial)

    # Preserve unchanged axes' quantization; enlarge only if new coordinates exceed range.
    scale = np.array(v4(header["quantizationScale"])[:3], dtype=np.float64)
    origin = np.array(v4(header["quantizationOffset"])[:3], dtype=np.float64)
    low, high = trial.min(axis=0), trial.max(axis=0)
    outside = (low < origin - scale) | (high > origin + scale)
    if outside.any():
        center = (low + high) / 2
        half = np.maximum((high - low) / 2 * 1.02, 1e-6)
        scale[outside] = half[outside]
        origin[outside] = center[outside]
    q = np.rint((trial - origin) / scale * 32767).astype(np.int64)
    if (np.abs(q) > 32767).any():
        raise RuntimeError("Position quantization would clip")
    pos_base, pos_stride = offsets[0], strides[0]
    for i in range(count):
        struct.pack_into("<3h", buffer, pos_base + i * pos_stride, *map(int, q[i]))
    for name, values in (("quantizationScale", scale), ("quantizationOffset", origin)):
        node = header[name]
        for axis, value in zip("XYZ", values):
            node[axis] = float(value)

    raw_vectors = np.frombuffer(source_buffer[offsets[2]:offsets[2] + count * strides[2]],
                                dtype="<u4").reshape(count, 2)
    old_tangent = (((raw_vectors[:, 1, None] >> np.array([0, 10, 20], dtype=np.uint32)) & 1023)
                   .astype(np.float64) / 1023 * 2 - 1)
    old_tangent = normalized(old_tangent)
    decoded_chunk = decode(SOURCE)["chunks"][0]
    uv = np.asarray(decoded_chunk["uvs"], dtype=np.float64)
    cp77_triangles = np.asarray(decoded_chunk["indices"], dtype=np.int64).reshape(-1, 3)
    normals, tangents, vector_report = recompute_vectors(trial, uv, cp77_triangles, old_tangent)
    # Recompute shading vectors in the moved region and its immediately adjacent vertices.
    moved = np.linalg.norm(correction, axis=1) > 0.00005
    shading = moved.copy()
    shading[edges[moved[edges[:, 0]], 1]] = True
    shading[edges[moved[edges[:, 1]], 0]] = True
    if args.diagnostic_glb:
        shading[:] = True  # Match the diagnostic GLB's full normal recomputation.
    packed_normal = packed_dec4(normals, raw_vectors[:, 0])
    packed_tangent = packed_dec4(tangents, raw_vectors[:, 1])
    for i in np.flatnonzero(shading):
        struct.pack_into("<II", buffer, offsets[2] + i * strides[2],
                         int(packed_normal[i]), int(packed_tangent[i]))

    # The original authored ANGEL target uses uniform white vertex color and UV1=(0,1).
    _, author_color, author_uv1 = attributes(AUTHOR)
    if not (np.all(author_color == author_color[0]) and np.all(author_uv1 == author_uv1[0])):
        raise RuntimeError("Author target render attributes are not uniform")
    target_attr = bytes(author_color[0]) + bytes(author_uv1[0])
    for i in range(count):
        start = offsets[3] + i * strides[3]
        buffer[start:start + 8] = target_attr

    bb = root["boundingBox"]
    for axis, lo, hi in zip("XYZ", low, high):
        bb["Min"][axis] = float(min(bb["Min"][axis], lo))
        bb["Max"][axis] = float(max(bb["Max"][axis], hi))
    blob["renderBuffer"]["Bytes"] = base64.b64encode(buffer).decode("ascii")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    packed = np.concatenate([np.asarray(c["positions"], dtype=np.float64)
                             for c in decode(out_json)["chunks"]])
    quant_error = np.linalg.norm(packed - trial, axis=1)
    packed_gap = measure(model, body, packed)
    packed_geom = topology(base, packed, triangles, edges)
    report = {
        "schema": "cp77.phase3.stella_v4_dress_build/v1",
        "variant": variant,
        "source_json_sha256": sha256(SOURCE),
        "diagnostic_glb_sha256": sha256(args.diagnostic_glb) if args.diagnostic_glb else None,
        "output_json_sha256": sha256(out_json),
        "source_vertices": count,
        "source_penetration_count": before["penetration_count"],
        "float_penetration_count": after["penetration_count"],
        "quantized_penetration_count": packed_gap["penetration_count"],
        "quantization_error_max_mm": float(quant_error.max() * 1000),
        "quantization_axes_rescaled": [str(axis) for axis, flag in zip("XYZ", outside) if flag],
        "geometry_after_quantization": packed_geom,
        "shading_vertices_recomputed": int(shading.sum()),
        "author_uniform_color": author_color[0].tolist(),
        "author_uniform_uv1_bytes": author_uv1[0].tolist(),
        "vector_recomputation": vector_report,
        "skin_and_uv0_index_bytes_preserved": (
            all(buffer[offsets[0] + i * pos_stride + 8:offsets[0] + i * pos_stride + pos_stride]
                == source_buffer[offsets[0] + i * pos_stride + 8:offsets[0] + i * pos_stride + pos_stride]
                for i in range(count))
            and buffer[offsets[1]:offsets[2]] == source_buffer[offsets[1]:offsets[2]]
            and buffer[header["indexBufferOffset"]:] == source_buffer[header["indexBufferOffset"]:]
        ),
    }
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
