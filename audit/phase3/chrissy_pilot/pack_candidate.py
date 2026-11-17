"""Repack the Chrissy pilot, replacing only its resolved boot mesh."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from audit.phase3.boots_pilot.prepare_runtime_test import cli, inventory, sha
from audit.phase3.boots_pilot.verify_streams import audit_streams
from audit.phase3.validate_v2 import verts_of

BASE = Path(__file__).resolve().parent
MESH_ENTRY = "12750523408280256843.bin"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pack_verified_mesh(source: Path, candidate: Path, original: Path, build: Path,
                       archive_stem: str, mesh_entry: str, entry_count: int, *, run_cli=cli) -> dict:
    original_files = inventory(original)
    if len(original_files) != entry_count or mesh_entry not in original_files:
        raise ValueError("Unexpected input archive entries")
    build.mkdir()
    raw = build / "raw"
    raw.mkdir()
    run_cli("convert", "deserialize", candidate, "-o", raw)
    mesh = raw / candidate.stem
    stage = build / archive_stem
    shutil.copytree(original, stage)
    shutil.copyfile(mesh, stage / mesh_entry)
    run_cli("pack", stage, "-o", build)
    archive = build / (stage.name + ".archive")
    extracted = build / "extracted"
    run_cli("unbundle", archive, "-o", extracted)
    packed_files = inventory(extracted)
    if packed_files != inventory(stage) or packed_files.keys() != original_files.keys():
        raise ValueError("Unexpected archive entries or extracted bytes")
    changed = sorted(name for name in original_files if original_files[name] != packed_files[name])
    if changed != [mesh_entry]:
        raise ValueError(f"Unexpected changed entries: {changed}")

    packed_mesh = build / mesh.name
    shutil.copyfile(extracted / mesh_entry, packed_mesh)
    run_cli("convert", "serialize", packed_mesh, "-o", build)
    roundtrip = build / candidate.name
    streams = audit_streams(source, roundtrip)
    if not streams["pass"]:
        raise ValueError(f"Unexpected render or metadata change: {streams}")
    packed_vertices = verts_of(roundtrip)
    roundtrip_mm = float(np.linalg.norm(packed_vertices - verts_of(candidate), axis=1).max() * 1000)
    frozen = np.load(candidate.parent / "skip_mask.npy", allow_pickle=False)
    frozen_mm = float(np.linalg.norm(packed_vertices[frozen] - verts_of(source)[frozen], axis=1)
                      .max(initial=0) * 1000)
    if roundtrip_mm > 0.001 or frozen_mm > 0.05:
        raise ValueError(f"Round trip or frozen region displacement exceeded tolerance: {roundtrip_mm}, {frozen_mm}")
    result = {"sha256": sha(archive), "archive_entries": len(packed_files), "changed_entries": changed,
              "streams": streams, "roundtrip_max_mm": roundtrip_mm, "frozen_max_mm": frozen_mm}
    (build / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    source = BASE / "serialized/chrissy_ebbrb.mesh.json"
    candidate = BASE / "candidate_smooth/chrissy_angel.mesh.json"
    geometry = read_json(candidate.parent / "validation.json")["geometry"]
    if geometry["new_degenerate_indexed_triangles"] or geometry["reversed_indexed_triangles"]:
        raise ValueError("Candidate failed topology validation")
    route = read_json(BASE / "routing/routing_result.json")
    if not any(entry["fnv1a64"] + ".bin" == MESH_ENTRY for entry in route["compiled_buffer_mesh_paths"]):
        raise ValueError("Mesh entry was not found in the original entity")
    result = pack_verified_mesh(source, candidate, BASE / "original", BASE / "pack_check",
                                "Chrissy-Laced-Crotch-High-Boots-rb", MESH_ENTRY, 17)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
