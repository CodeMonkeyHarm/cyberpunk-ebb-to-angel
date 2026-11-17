"""Require every source byte outside position streams to survive conversion."""
from __future__ import annotations

import base64
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from automation.cp77_skin import stream_layout  # noqa: E402

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "serialized/s1_045_wa_boot__00chap_hyst.mesh.json"
CANDIDATE = BASE / "prototype/s1_045_wa_boot__00chap_hyst_butt.mesh.json"
OUT = BASE / "prototype/stream_invariants.json"


def audit_streams(source_path: Path, candidate_path: Path) -> dict:
    source = json.loads(source_path.read_text(encoding="utf-8"))["Data"]
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))["Data"]
    sr = source["RootChunk"]
    cr = candidate["RootChunk"]
    sb = sr["renderResourceBlob"]["Data"]
    cb = cr["renderResourceBlob"]["Data"]
    sbytes = base64.b64decode(sb["renderBuffer"]["Bytes"])
    cbytes = base64.b64decode(cb["renderBuffer"]["Bytes"])
    if len(sbytes) != len(cbytes):
        raise ValueError("renderBuffer length changed")
    allowed = bytearray(len(sbytes))
    position_vertices = 0
    for chunk in sb["header"]["renderChunkInfos"]:
        count = chunk.get("numVertices", 0)
        if not count:
            continue
        layout, strides = stream_layout(chunk)
        offsets = chunk["chunkVertices"]["byteOffsets"]["Elements"]
        positions = [(st, off, size) for st, items in layout.items()
                     for usage, _, typ, off, size in items if usage == "PS_Position"]
        if len(positions) != 1:
            raise ValueError("Unexpected position stream layout")
        st, off, size = positions[0]
        for i in range(count):
            start = offsets[st]+i*strides[st]+off
            allowed[start:start+6] = b"\x01"*6
        position_vertices += count
    altered = [i for i, (a, b) in enumerate(zip(sbytes, cbytes)) if a != b]
    illegal = [i for i in altered if not allowed[i]]

    src_normalized, cand_normalized = copy.deepcopy(source), copy.deepcopy(candidate)
    for item in (src_normalized, cand_normalized):
        root = item["RootChunk"]
        root.pop("boundingBox", None)
        blob = root["renderResourceBlob"]["Data"]
        blob["renderBuffer"].pop("Bytes", None)
        blob["header"].pop("quantizationScale", None)
        blob["header"].pop("quantizationOffset", None)
    other_json_equal = src_normalized == cand_normalized
    return {
        "schema": "cp77.phase3.boots_stream_invariants/v1",
        "position_vertices": position_vertices,
        "render_buffer_bytes": len(sbytes),
        "changed_bytes": len(altered),
        "changed_bytes_outside_xyz_position": len(illegal),
        "other_json_equal": other_json_equal,
        "pass": len(illegal) == 0 and other_json_equal,
    }


def main() -> None:
    result = audit_streams(SOURCE, CANDIDATE)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
