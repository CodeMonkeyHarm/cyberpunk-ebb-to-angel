"""Test a spatially smooth and seam-locked dress correction in Blender GLBs."""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from audit.phase3.build_v4_dress_json import recompute_vectors
from audit.phase3.prototype_chest_collision import MESH, measure, topology, unique_edges
from audit.phase3.validate_v2 import BM, P, as_model, sha256
from automation.gltf_skin import GlbBuilder, write_glb

BASE = ROOT / "audit/phase3/stella"
SOURCE = BASE / "json/ebbrb_dress.mesh.json"
GUIDE = BASE / "v4_wide/converted_json/angel_dress.mesh.json"
OUT = BASE / "smooth_surface_trial"
WIDTHS_M = (0.026, 0.036, 0.046)


def mean_for_group(positions, groups, counts):
    totals = np.zeros((len(counts), 3))
    np.add.at(totals, groups, positions)
    return totals / counts[:, None]


def smoothstep(height, start, end):
    fraction = np.clip((height - start) / (end - start), 0, 1)
    return fraction**2 * (3 - 2 * fraction)


def basis(positions, centers, width, taper):
    distance_squared = np.sum((positions[:, None, :] - centers) ** 2, axis=2)
    kernel = np.exp(-0.5 * distance_squared / width**2)
    height_taper = smoothstep(positions[:, 2], *taper)
    return kernel * height_taper[:, None]


def write_diagnostic(mesh, vertices, label, out_dir=OUT):
    chunk, = mesh.geo["chunks"]
    uv = np.asarray(chunk["uvs"], dtype=float)
    indices = np.asarray(chunk["indices"], dtype=np.int64).reshape(-1, 3)
    normals, _, _ = recompute_vectors(vertices, uv, indices, np.zeros_like(vertices))
    geo = {**mesh.geo, "chunks": [{**chunk, "positions": vertices.tolist(), "normals": normals.tolist()}]}
    builder = GlbBuilder()
    result = builder.build(geo, skinned=False, generator="Stelle surface diagnostic", body_id=label)
    write_glb(result["gltf"], builder.bin, out_dir / f"{label}.glb")


def resolve_residual(garment, body, base, groups, kernel, coef, gap, clearance=0.0):
    trial = (base + kernel @ coef)[groups]
    chest = (trial[:, 1] >= 0.04) & (trial[:, 2] >= 1.25) & (trial[:, 2] <= 1.38)
    for _ in range(24 if clearance else 6):
        deficient = gap["penetrated"] | (chest & gap["valid"] & (gap["signed"] < clearance))
        if not deficient.any():
            break
        vertex = np.argmin(np.where(deficient, gap["signed"], np.inf))
        row = kernel[groups[vertex]]
        norm_squared = row @ row
        if norm_squared < 1e-12:
            break
        correction = (clearance + 0.0002 - gap["signed"][vertex]) * gap["normals"][vertex]
        coef += np.outer(row, correction) / norm_squared
        trial = (base + kernel @ coef)[groups]
        gap = measure(garment, body, trial)
    return trial, gap


def record(report, garment, source_vertices, trial, label, gap, triangles, edges, groups, counts):
    result = topology(source_vertices, trial, triangles, edges)
    spread = np.linalg.norm(trial - mean_for_group(trial, groups, counts)[groups], axis=1)
    result.update(penetration_count=gap["penetration_count"], deepest_mm=gap["deepest_mm"],
                  max_deviation_from_coincident_group_center_mm=float(spread.max() * 1000))
    report["variants"][label] = result
    write_diagnostic(garment, trial, label)
    print(label, json.dumps(result), flush=True)


def main():
    OUT.mkdir(exist_ok=True)
    source = as_model("source", SOURCE)
    garment = as_model("v3", MESH)
    guide = as_model("wide", GUIDE)
    triangles = garment.triangles
    if not (np.array_equal(source.triangles, triangles) and np.array_equal(guide.triangles, triangles)):
        raise ValueError("Probe requires matching topology and vertex ordering")
    edges = unique_edges(triangles)
    original, groups, counts = np.unique(source.vertices, axis=0, return_inverse=True, return_counts=True)
    base = mean_for_group(garment.vertices, groups, counts)
    guide_positions = mean_for_group(guide.vertices, groups, counts)
    centers = np.asarray(list(itertools.product(np.linspace(-0.15, 0.15, 7),
                                               [0.035, 0.085, 0.135],
                                               np.linspace(1.19, 1.40, 7))))
    body = BM.load(P.load("ANGEL"))
    source_vertices = garment.vertices.copy()
    report = {"source_sha256": sha256(SOURCE), "v3_sha256": sha256(MESH), "guide_sha256": sha256(GUIDE),
              "author_geometry_used_as_input": False, "variants": {}}
    source_blend = smoothstep(original[:, 2], 1.03, 1.18)[:, None]
    blended = base + source_blend * (original - base)
    variants = [(f"smooth_{round(width * 1000)}", base, width, (1.16, 1.28)) for width in WIDTHS_M]
    variants.extend((f"source_{round(width * 1000)}", blended, width, (1.05, 1.19))
                    for width in (0.036, 0.052, 0.068))
    variants.append(("source_skirt_68", original, 0.068, (1.05, 1.19)))
    for label, base, width, taper in variants:
        kernel = basis(base, centers, width, taper)
        fit = (base[:, 2] > taper[0]) & (base[:, 2] < 1.43)
        restricted = kernel[fit]
        gram = restricted.T @ restricted
        coef = np.linalg.solve(gram + np.eye(len(centers)) * 0.025,
                               restricted.T @ (guide_positions[fit] - base[fit]))
        trial = (base + kernel @ coef)[groups]
        gap = measure(garment, body, trial)
        record(report, garment, source_vertices, trial, label, gap, triangles, edges, groups, counts)
        if label == "smooth_36" or label in ("source_36", "source_52", "source_68"):
            corrected, residual_gap = resolve_residual(garment, body, base, groups, kernel, coef.copy(), gap)
            record(report, garment, source_vertices, corrected, f"{label}_clearance", residual_gap,
                   triangles, edges, groups, counts)
        if label in ("source_52", "source_68", "source_skirt_68"):
            corrected, residual_gap = resolve_residual(garment, body, base, groups, kernel, coef, gap,
                                                      clearance=0.001)
            record(report, garment, source_vertices, corrected, f"{label}_margin", residual_gap,
                   triangles, edges, groups, counts)
    (OUT / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
