"""Inspect color and UV1 channels across Stelle Dress body variants."""
from __future__ import annotations

import base64
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent / "stella"


def attributes(path: Path):
    root = json.loads(path.read_text(encoding="utf-8"))["Data"]["RootChunk"]
    blob = root["renderResourceBlob"]["Data"]
    header = blob["header"]
    raw = base64.b64decode(blob["renderBuffer"]["Bytes"])
    chunk = header["renderChunkInfos"][0]
    count = chunk["numVertices"]
    offsets = chunk["chunkVertices"]["byteOffsets"]["Elements"]
    uv0_bytes = np.frombuffer(raw[offsets[1]:offsets[1] + count * 4],
                              dtype=np.uint8).reshape(count, 4).copy()
    color_uv1 = np.frombuffer(raw[offsets[3]:offsets[3] + count * 8],
                              dtype=np.uint8).reshape(count, 8).copy()
    return uv0_bytes, color_uv1[:, :4], color_uv1[:, 4:]


def main() -> None:
    rows = {}
    for path in sorted((BASE / "json").glob("*dress.mesh.json")):
        uv0, color, uv1 = attributes(path)
        colors = Counter(map(bytes, color))
        uvs = Counter(map(bytes, uv1))
        rows[path.stem] = {
            "vertices": len(color),
            "colors": [{"rgba": list(key), "count": value}
                       for key, value in colors.most_common(5)],
            "uv1": [{"raw_half_float_bytes": list(key), "count": value}
                    for key, value in uvs.most_common(8)],
            "uv0_unique": len(set(map(bytes, uv0))),
        }
    src_uv0, _, _ = attributes(BASE / "json/ebbrb_dress.mesh.json")
    dst_uv0, _, dst_uv1 = attributes(BASE / "json/angel_dress.mesh.json")
    mapping = defaultdict(set)
    for key, uv1 in zip(map(bytes, dst_uv0), map(bytes, dst_uv1)):
        mapping[key].add(uv1)
    keys = list(map(bytes, src_uv0))
    rows["transfer_feasibility"] = {
        "source_vertices_with_exact_uv0_in_author": sum(key in mapping for key in keys),
        "source_vertices_with_unambiguous_author_uv1": sum(len(mapping.get(key, ())) == 1 for key in keys),
        "source_vertices_with_ambiguous_author_uv1": sum(len(mapping.get(key, ())) > 1 for key in keys),
        "source_vertices_with_no_exact_uv0": sum(key not in mapping for key in keys),
    }
    out = BASE / "v3/game_test_20261116/vertex_attribute_audit.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
