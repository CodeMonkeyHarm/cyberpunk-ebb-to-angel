"""Reduce v6 skirt widening using the two measured lateral contact sectors."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from audit.phase3.prototype_stella_smooth_surface import write_diagnostic
from audit.phase3.validate_v2 import as_model


def ease(values, start, end):
    t = np.clip((values - start) / (end - start), 0, 1)
    return t**3 * (10 - 15 * t + 6 * t**2)


def main():
    stella = ROOT / "audit/phase3/stella"
    output = stella / "v5_runtime_20261117/v7_local_clearance"
    output.mkdir(exist_ok=True)
    source = stella / "smooth_surface_trial/source_skirt_68_margin_cr2w/roundtrip/angel_dress.mesh.json"
    model = as_model("v5", source)
    x, y, z = model.vertices.T
    center_y = -0.018
    side_angle = np.degrees(np.arctan2(np.abs(y - center_y), np.abs(x)))
    sector = 1 - ease(side_angle, 24, 68)
    height = ease(z, 0.995, 1.095) * (1 - ease(z, 1.123, 1.208))
    radial = np.column_stack((x, y - center_y))
    radial /= np.maximum(np.linalg.norm(radial, axis=1, keepdims=True), 1e-9)
    for label, millimeters in (("lateral_475", 4.75), ("lateral_525", 5.25), ("lateral_575", 5.75)):
        trial = model.vertices.copy()
        trial[:, :2] += radial * (sector * height)[:, None] * (millimeters / 1000)
        write_diagnostic(model, trial, label, output)


if __name__ == "__main__":
    main()
