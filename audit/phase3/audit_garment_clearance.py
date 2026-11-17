"""Run the Phase 3 clearance checks on serialized EBBRB garment meshes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from audit.phase3.validate_v2 import BM, P, as_model, sha256, signed_clearance

PENETRATION_M = 0.0005
BANDS_M = (0.0, 0.25, 0.55, 0.75, 0.9, 1.05, 1.21, 1.24)


def summarize(z, signed, valid):
    def region(mask):
        values = signed[valid & mask] * 1000
        penetration = values[values < -PENETRATION_M * 1000]
        return {
            "vertices": int(mask.sum()),
            "valid": len(values),
            "median_signed_mm": round(float(np.median(values)), 3) if len(values) else None,
            "penetrating_vertices": len(penetration),
            "deepest_mm": round(float(penetration.min()), 3) if len(penetration) else None,
        }

    edges = (-np.inf, *BANDS_M, np.inf)
    bands = []
    for lo, hi in zip(edges, edges[1:]):
        mask = (z >= lo) & (z < hi)
        if mask.any():
            bands.append({"z_m": [lo if np.isfinite(lo) else None, hi if np.isfinite(hi) else None],
                          **region(mask)})
    return {"total": region(np.ones(len(z), dtype=bool)), "bands": bands}


def paired_changes(z, before, after):
    old_gap, old_valid = before
    new_gap, new_valid = after
    paired = old_valid & new_valid
    old_in = old_gap < -PENETRATION_M
    new_in = new_gap < -PENETRATION_M
    entered = paired & ~old_in & new_in
    exited = paired & old_in & ~new_in
    penetrating = paired & new_in
    return {
        "threshold_mm": PENETRATION_M * 1000,
        "vertices_valid_in_both": int(paired.sum()),
        "validity_changes": int((old_valid != new_valid).sum()),
        "source_beyond_threshold": int((old_in & old_valid).sum()),
        "candidate_beyond_threshold": int((new_in & new_valid).sum()),
        "crossed_into_penetration": int(entered.sum()),
        "crossed_out_of_penetration": int(exited.sum()),
        "new_crossings_max_depth_mm": round(float(-new_gap[entered].min() * 1000), 5) if entered.any() else None,
        "new_crossings_source_z_max_m": round(float(z[entered].max()), 6) if entered.any() else None,
        "worst_deepening_mm_on_paired_penetrating_vertices": (
            round(max(0.0, float((old_gap[penetrating] - new_gap[penetrating]).max()) * 1000), 5)
            if penetrating.any() else None
        ),
    }


def geometry_changes(source, candidate):
    triangles = source.triangles

    def normals(vertices):
        a, b, c = vertices[triangles].transpose(1, 0, 2)
        return np.cross(b - a, c - a)

    before = normals(source.vertices)
    after = normals(candidate.vertices)
    old_area = np.linalg.norm(before, axis=1)
    new_area = np.linalg.norm(after, axis=1)
    original_faces = old_area > 1e-12
    surviving = original_faces & (new_area > 1e-12)
    direction = np.einsum("ij,ij->i", before, after)
    movement = np.linalg.norm(candidate.vertices - source.vertices, axis=1) * 1000
    return {
        "source_degenerate_indexed_triangles": int((~original_faces).sum()),
        "new_degenerate_indexed_triangles": int((original_faces & ~surviving).sum()),
        "reversed_indexed_triangles": int((surviving & (direction < 0)).sum()),
        "minimum_area_ratio": round(float(np.min(new_area[original_faces] / old_area[original_faces])), 5)
        if original_faces.any() else None,
        "max_displacement_mm": round(float(movement.max()), 5),
    }


def audit_clearance(source_path: Path, candidate_path: Path | None = None,
                    frozen_mask: np.ndarray | None = None) -> dict:
    source = as_model("source", source_path)
    candidate = as_model("candidate", candidate_path) if candidate_path else None
    if candidate is not None and (
        not np.array_equal(source.chunk_of_vertex, candidate.chunk_of_vertex)
        or not np.array_equal(source.triangles, candidate.triangles)
    ):
        raise ValueError("paired audit requires unchanged chunk order, vertex order and indices")
    if frozen_mask is not None and (
        candidate is None or frozen_mask.dtype != np.bool_ or frozen_mask.shape != (len(source.vertices),)
        or not frozen_mask.any()
    ):
        raise ValueError("frozen mask must be a nonempty Boolean selection in source vertex order")
    z = source.vertices[:, 2]
    angel = BM.load(P.load("ANGEL"))
    source_on_angel = signed_clearance(source, angel)
    report = {
        "schema": "cp77.phase3.garment_clearance/v1",
        "source_sha256": sha256(source_path),
        "source_z_range_m": [float(z.min()), float(z.max())],
        "indexed_triangles": len(source.triangles),
        "source_on_ANGEL": summarize(z, *source_on_angel),
    }
    if candidate is None:
        report["source_on_EBBRB"] = summarize(z, *signed_clearance(source, BM.load(P.load("EBBRB"))))
    else:
        after = signed_clearance(candidate, angel)
        report["candidate_sha256"] = sha256(candidate_path)
        report["candidate_on_ANGEL"] = summarize(z, *after)
        report["paired_penetration"] = paired_changes(z, source_on_angel, after)
        report["geometry"] = geometry_changes(source, candidate)
        if frozen_mask is not None:
            movement = candidate.vertices[frozen_mask] - source.vertices[frozen_mask]
            maximum_mm = float(np.linalg.norm(movement, axis=1).max() * 1000)
            report["frozen_region"] = {"vertices": int(frozen_mask.sum()), "max_mm": maximum_mm}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_clearance(args.source, args.candidate)
    except ValueError as exc:
        parser.error(str(exc))
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
