"""Test front-only chest clearance on the original Dolly Dress 1 mesh."""
import base64
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from audit.phase3.build_v4_dress_json import normalized, packed_dec4, recompute_vectors
from audit.phase3.audit_garment_clearance import geometry_changes
from audit.phase3.prototype_chest_collision import measure
from audit.phase3.prototype_stella_lateral_clearance import ease
from audit.phase3.validate_v2 import BM, P, as_model
from automation.cp77_skin import stream_layout, v4
from automation.gltf_skin import GlbBuilder, write_glb

PILOT = ROOT / "audit/phase3/dolly_dress_pilot"
SOURCE = PILOT / "json/fairyexe_dollygogomini_dress1_w_ebbrb.mesh.json"
OUT = PILOT / "chest_candidates"


def rebuild(model, trial, destination):
    doc = json.loads(SOURCE.read_text(encoding="utf-8"))
    root = doc["Data"]["RootChunk"]
    blob = root["renderResourceBlob"]["Data"]
    header = blob["header"]
    scale = np.array(v4(header["quantizationScale"])[:3])
    origin = np.array(v4(header["quantizationOffset"])[:3])
    q = np.rint((trial - origin) / scale * 32767)
    if np.abs(q).max() > 32767:
        raise ValueError("Candidate exceeds source quantization bounds")
    buffer = bytearray(base64.b64decode(blob["renderBuffer"]["Bytes"]))
    allowed = np.zeros(len(buffer), dtype=bool)
    start = 0
    for chunk, geo in zip(header["renderChunkInfos"], model.geo["chunks"], strict=True):
        n = chunk["numVertices"]
        rows = slice(start, start + n)
        start += n
        layout, strides = stream_layout(chunk)
        if layout[0][0][2:] != ("PT_Short4N", 0, 8) or strides[2] != 8 or [el[2] for el in layout[2]] != ["PT_Dec4"] * 2:
            raise ValueError("Unexpected vertex stream layout")
        pos, _, vec, *_ = chunk["chunkVertices"]["byteOffsets"]["Elements"]
        position = np.ndarray((n, 3), dtype="<i2", buffer=buffer, offset=pos, strides=(strides[0], 2))
        moved = np.any(position != q[rows], axis=1)
        position[moved] = q[rows][moved]
        np.ndarray((n, 6), dtype=bool, buffer=allowed, offset=pos, strides=(strides[0], 1))[moved] = True
        if not moved.any():
            continue
        raw = np.ndarray((n, 2), dtype="<u4", buffer=buffer, offset=vec)
        old_tangent = normalized(((raw[:, 1, None] >> np.array([0, 10, 20], dtype=np.uint32)) & 1023) / 511.5 - 1)
        triangles = np.asarray(geo["indices"], dtype=np.int64).reshape(-1, 3)
        normals, tangents, _ = recompute_vectors(trial[rows], np.array(geo["uvs"]), triangles, old_tangent)
        shading = moved.copy()
        shading[triangles[moved[triangles].any(axis=1)].ravel()] = True
        shading &= (np.linalg.norm(normals, axis=1) > 0.5) & (np.linalg.norm(tangents, axis=1) > 0.5)
        raw[shading, 0] = packed_dec4(normals[shading], raw[shading, 0])
        raw[shading, 1] = packed_dec4(tangents[shading], raw[shading, 1])
        allowed[vec:vec + n * 8].reshape(n, 8)[shading] = True
    assert start == len(trial)
    original = np.frombuffer(base64.b64decode(blob["renderBuffer"]["Bytes"]), dtype=np.uint8)
    assert np.array_equal(np.frombuffer(buffer, dtype=np.uint8)[~allowed], original[~allowed])
    blob["renderBuffer"]["Bytes"] = base64.b64encode(buffer).decode("ascii")
    for axis, low, high in zip("XYZ", trial.min(axis=0), trial.max(axis=0)):
        box = root["boundingBox"]
        box["Min"][axis] = float(min(box["Min"][axis], low))
        box["Max"][axis] = float(max(box["Max"][axis], high))
    destination.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def main():
    model = as_model("ebbrb", SOURCE)
    body = BM.load(P.load("ANGEL"))
    base = model.vertices.copy()
    x, y, z = base.T
    front = ease(y, 0.050, 0.101) * (1 - ease(np.abs(x), 0.102, 0.158))
    height = ease(z, 1.175, 1.280) * (1 - ease(z, 1.355, 1.456))
    OUT.mkdir(exist_ok=True)
    summary = {}
    for mm in (14, 18, 22):
        trial = base.copy()
        trial[:, 1] += front * height * (mm / 1000)
        label = f"front_{mm:02d}mm"
        folder = OUT / label
        folder.mkdir(exist_ok=True)
        path = folder / "fairyexe_dollygogomini_dress1_w_angel.mesh.json"
        rebuild(model, trial, path)
        packed = as_model(label, path)
        assert np.array_equal(model.triangles, packed.triangles)
        shift = np.linalg.norm(packed.vertices - base, axis=1)
        assert shift[(front * height) == 0].max() < 1e-9
        assert np.array_equal(base[:, [0, 2]], packed.vertices[:, [0, 2]])
        stats = geometry_changes(model, packed)
        result = measure(packed, body, packed.vertices)
        stats["penetration_count"] = result["penetration_count"]
        stats["deepest_mm"] = result["deepest_mm"]
        summary[label] = stats
        builder = GlbBuilder()
        glb = builder.build(packed.geo, skinned=False, generator="Dolly chest clearance", body_id=label)
        write_glb(glb["gltf"], builder.bin, OUT / f"{label}.glb")
    (OUT / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
