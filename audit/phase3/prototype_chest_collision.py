"""Read-only chest collision prototype for the rejected v3 mesh; no archive output."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from automation import body_model as BM, body_profiles as P, correspondence as CORR  # noqa: E402
from audit.phase3.validate_v2 import as_model  # noqa: E402

MESH = ROOT / "audit/phase3/stella/v3/roundtrip_fixed/json/angel_dress.mesh.json"
OUT = ROOT / "audit/phase3/stella/v3/chest_collision_prototype.json"


def measure(model: BM.BodyModel, body: BM.BodyModel, vertices: np.ndarray):
    model.vertices = vertices
    match = CORR.match(model, body, cell_m=0.02, angle_tol_deg=75.0, with_arrays=True)
    arrays = match["_arrays"]
    distance = arrays["distance"]
    closest = arrays["closest"]
    normals = arrays["target_normal"]
    signed = distance * np.sign(np.einsum("ij,ij->i", vertices - closest, normals) + 1e-12)
    valid = distance <= 0.05
    penetrated = valid & (signed < -0.0005)
    return {
        "distance": distance, "signed": signed, "normals": normals,
        "valid": valid, "penetrated": penetrated,
        "penetration_count": int(penetrated.sum()),
        "deepest_mm": float(signed[penetrated].min() * 1000) if penetrated.any() else 0.0,
    }


def unique_edges(triangles: np.ndarray) -> np.ndarray:
    edges = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]],
                            triangles[:, [2, 0]]))
    return np.unique(np.sort(edges, axis=1), axis=0)


def diffuse(desired: np.ndarray, seeds: np.ndarray, active: np.ndarray,
            edges: np.ndarray, iterations: int) -> np.ndarray:
    correction = np.zeros_like(desired)
    correction[seeds] = desired[seeds]
    degree = np.bincount(edges.ravel(), minlength=len(desired)).astype(np.float64)
    movable = active & ~seeds & (degree > 0)
    for _ in range(iterations):
        acc = np.zeros_like(correction)
        np.add.at(acc, edges[:, 0], correction[edges[:, 1]])
        np.add.at(acc, edges[:, 1], correction[edges[:, 0]])
        correction[movable] = 0.25 * correction[movable] + 0.75 * (acc[movable] / degree[movable, None])
        correction[seeds] = desired[seeds]
    return correction


def projected_smooth(initial: np.ndarray, signed: np.ndarray, normals: np.ndarray,
                     seeds: np.ndarray, active: np.ndarray, edges: np.ndarray,
                     iterations: int) -> np.ndarray:
    correction = initial.copy()
    degree = np.bincount(edges.ravel(), minlength=len(correction)).astype(np.float64)
    movable = active & (degree > 0)
    for _ in range(iterations):
        acc = np.zeros_like(correction)
        np.add.at(acc, edges[:, 0], correction[edges[:, 1]])
        np.add.at(acc, edges[:, 1], correction[edges[:, 0]])
        correction[movable] = (0.5 * correction[movable]
                               + 0.5 * acc[movable] / degree[movable, None])
        residual = 0.001 - signed[seeds] - np.einsum("ij,ij->i", correction[seeds], normals[seeds])
        correction[seeds] += normals[seeds] * np.maximum(0.0, residual)[:, None]
        correction[~active] = 0.0
    return correction


def topology(base: np.ndarray, trial: np.ndarray, triangles: np.ndarray,
             edges: np.ndarray) -> dict:
    a0 = np.cross(base[triangles[:, 1]] - base[triangles[:, 0]],
                  base[triangles[:, 2]] - base[triangles[:, 0]])
    a1 = np.cross(trial[triangles[:, 1]] - trial[triangles[:, 0]],
                  trial[triangles[:, 2]] - trial[triangles[:, 0]])
    norm0 = np.linalg.norm(a0, axis=1)
    norm1 = np.linalg.norm(a1, axis=1)
    ratio = norm1 / np.maximum(norm0, 1e-12)
    stretch0 = np.linalg.norm(base[edges[:, 1]] - base[edges[:, 0]], axis=1)
    stretch1 = np.linalg.norm(trial[edges[:, 1]] - trial[edges[:, 0]], axis=1)
    stretch = stretch1 / np.maximum(stretch0, 1e-12)
    changed = np.linalg.norm(trial - base, axis=1)
    worst_edge = int(np.argmax(stretch))
    smallest_face = int(np.argmin(ratio))
    return {
        "inverted_index_triangles": int((np.einsum("ij,ij->i", a0, a1) <= 0).sum()),
        "new_degenerate_index_triangles": int(((norm1 < 2e-12) & (norm0 >= 2e-12)).sum()),
        "area_ratio_min": float(ratio.min()),
        "area_ratio_p01": float(np.percentile(ratio, 1)),
        "edge_stretch_max": float(stretch.max()),
        "edge_stretch_p99": float(np.percentile(stretch, 99)),
        "worst_edge": {
            "vertices": edges[worst_edge].tolist(),
            "source_length_mm": float(stretch0[worst_edge] * 1000),
            "trial_length_mm": float(stretch1[worst_edge] * 1000),
            "mean_z_m": float(base[edges[worst_edge], 2].mean()),
        },
        "smallest_area_face": {
            "vertices": triangles[smallest_face].tolist(),
            "source_area_mm2": float(norm0[smallest_face] * 500000),
            "trial_area_mm2": float(norm1[smallest_face] * 500000),
            "mean_z_m": float(base[triangles[smallest_face], 2].mean()),
        },
        "moved_vertices_over_0_05mm": int((changed > 0.00005).sum()),
        "max_displacement_mm": float(changed.max() * 1000),
    }


def main() -> None:
    garment = as_model("v3_chest_probe", MESH)
    body = BM.load(P.load("ANGEL"))
    base = garment.vertices.copy()
    triangles = garment.triangles
    edges = unique_edges(triangles)
    before = measure(garment, body, base)
    z = base[:, 2]
    seeds = before["penetrated"] & (z >= 1.26) & (z <= 1.40)
    active = (z >= 1.23) & (z <= 1.41)
    desired = np.zeros_like(base)
    push = np.maximum(0.0, 0.001 - before["signed"][seeds])
    desired[seeds] = before["normals"][seeds] * push[:, None]
    result = {
        "schema": "cp77.phase3.stella_chest_collision_prototype/v1",
        "source": str(MESH.relative_to(ROOT)).replace("\\", "/"),
        "scope": "read-only numerical prototype; does not modify v3 mesh or archive",
        "baseline_penetration_count": before["penetration_count"],
        "baseline_deepest_mm": before["deepest_mm"],
        "seed_count": int(seeds.sum()),
        "max_direct_seed_push_mm": float(push.max() * 1000) if len(push) else 0.0,
        "iterations": {},
    }
    for steps in (20, 60, 120):
        correction = diffuse(desired, seeds, active, edges, steps)
        trial = base + correction
        geom = topology(base, trial, triangles, edges)
        # Collision remeasurement is useful only for candidates without inverted faces.
        if geom["inverted_index_triangles"] == 0 and geom["new_degenerate_index_triangles"] == 0:
            after = measure(garment, body, trial)
            geom["penetration_count"] = after["penetration_count"]
            geom["deepest_mm"] = after["deepest_mm"]
        result["iterations"][str(steps)] = geom
        print(steps, json.dumps(geom, ensure_ascii=False))
    base_correction = diffuse(desired, seeds, active, edges, 60)
    for steps in (100, 300):
        correction = projected_smooth(base_correction, before["signed"], before["normals"],
                                      seeds, active, edges, steps)
        trial = base + correction
        geom = topology(base, trial, triangles, edges)
        if geom["inverted_index_triangles"] == 0 and geom["new_degenerate_index_triangles"] == 0:
            after = measure(garment, body, trial)
            geom["penetration_count"] = after["penetration_count"]
            geom["deepest_mm"] = after["deepest_mm"]
        result["iterations"][f"projected_{steps}"] = geom
        print(f"projected_{steps}", json.dumps(geom, ensure_ascii=False))
    active_wide = (z >= 1.18) & (z <= 1.41)
    wide_initial = diffuse(desired, seeds, active_wide, edges, 60)
    wide_correction = projected_smooth(wide_initial, before["signed"], before["normals"],
                                       seeds, active_wide, edges, 700)
    wide_trial = base + wide_correction
    wide_geom = topology(base, wide_trial, triangles, edges)
    if wide_geom["inverted_index_triangles"] == 0 and wide_geom["new_degenerate_index_triangles"] == 0:
        wide_after = measure(garment, body, wide_trial)
        wide_geom["penetration_count"] = wide_after["penetration_count"]
        wide_geom["deepest_mm"] = wide_after["deepest_mm"]
    result["iterations"]["projected_700_wide"] = wide_geom
    print("projected_700_wide", json.dumps(wide_geom, ensure_ascii=False))
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
