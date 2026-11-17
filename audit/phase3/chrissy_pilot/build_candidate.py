"""Build the first offline Chrissy candidate from the original EBBRB mesh."""
from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from audit.phase3.convert_stella import convert_mesh
from audit.phase3.validate_v2 import BM, P, sha256

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "serialized/chrissy_ebbrb.mesh.json"
DIFF = ROOT / "reports/phase2/BodyDifference_EBBRB_to_ANGEL.json"
FIELD = ROOT / "audit/phase2/diff_v2/displacement_field.npz"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smooth-sampling", action="store_true")
    args = parser.parse_args()
    subfolder = "candidate_smooth" if args.smooth_sampling else "candidate"
    candidate = BASE / subfolder / "chrissy_angel.mesh.json"
    diff = json.loads(DIFF.read_text(encoding="utf-8"))
    bands = {name: tuple(region["band_z"]) for name, region in diff["regional_measurements"].items()}
    policy = dict.fromkeys(bands, "SKIP")
    policy.update(thigh="APPLY", hip="APPLY_LOW_FREQ", pelvis="APPLY_LOW_FREQ",
                  _attenuation=0.6, _smooth_iters=6, _taper_width_m=0.02)
    if args.smooth_sampling:
        policy["_sampling_radius_m"] = 0.045
    # Start with a conservative displacement. Keep the original intersections in
    # frozen regions and inspect the result independently before packaging.
    scale = 0.6
    with np.load(FIELD) as field:
        info, skipped = convert_mesh(
            "chrissy_ebbrb", SOURCE, candidate, BM.load(P.load("EBBRB")),
            field["disp"].astype(np.float64) * scale, field["src_vertices"].astype(np.float64),
            bands, policy, {}, target_body=None,
        )
    np.save(candidate.parent / "skip_mask.npy", skipped, allow_pickle=False)
    report = {"source_sha256": sha256(SOURCE), "field_sha256": sha256(FIELD), "policy_sha256": sha256(DIFF),
              "displacement_scale": scale, "policy": policy, "conversion": info}
    (candidate.parent / "build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(candidate)


if __name__ == "__main__":
    main()
