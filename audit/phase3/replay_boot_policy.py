"""Replay the accepted Chrissy offline displacement policy on a new EBBRB boot mesh."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit.phase3.chrissy_pilot.build_candidate import DIFF, FIELD
from audit.phase3.convert_stella import convert_mesh
from audit.phase3.validate_v2 import BM, P, sha256

RECIPE = ROOT / "config/boot_recipe.local.json"


def refit_mesh(source: Path, output: Path) -> None:
    recipe = json.loads(RECIPE.read_text(encoding="utf-8"))
    if sha256(DIFF) != recipe["policy_sha256"] or sha256(FIELD) != recipe["field_sha256"]:
        raise RuntimeError("Phase 2 inputs differ from the accepted Chrissy recipe")
    diff = json.loads(DIFF.read_text(encoding="utf-8"))
    bands = {name: tuple(region["band_z"]) for name, region in diff["regional_measurements"].items()}
    scale = recipe["displacement_scale"]
    policy = recipe["policy"]
    with np.load(FIELD, allow_pickle=False) as field:
        info, skipped = convert_mesh(
            source.name, source, output, BM.load(P.load("EBBRB")),
            field["disp"].astype(np.float64) * scale, field["src_vertices"].astype(np.float64),
            bands, policy, {}, target_body=None,
        )
    np.save(output.parent / "skip_mask.npy", skipped, allow_pickle=False)
    report = {
        "source_sha256": sha256(source), "recipe": RECIPE.relative_to(ROOT).as_posix(),
        "recipe_sha256": sha256(RECIPE), "field_sha256": recipe["field_sha256"],
        "policy_sha256": recipe["policy_sha256"], "displacement_scale": scale,
        "policy": policy, "conversion": info,
    }
    (output.parent / "build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Original EBBRB boot mesh serialized by WolvenKit")
    parser.add_argument("output", type=Path, help="New candidate mesh JSON path within the project")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.parent.exists():
        parser.error("output must be in a new directory within the project")
    refit_mesh(source, output)
    print(output)


if __name__ == "__main__":
    main()
