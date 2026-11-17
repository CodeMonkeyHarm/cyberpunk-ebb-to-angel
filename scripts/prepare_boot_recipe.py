"""Pin a locally generated EBBRB-to-ANGEL field to the controlled boot policy."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from automation import body_model, body_profiles


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    output = ROOT / "config/boot_recipe.local.json"
    if output.exists():
        raise ValueError("Local recipe already exists. Keep it with its inputs or use a fresh checkout.")
    difference = ROOT / "reports/phase2/BodyDifference_EBBRB_to_ANGEL.json"
    field = ROOT / "audit/phase2/diff_v2/displacement_field.npz"
    report = json.loads(difference.read_text(encoding="utf-8"))
    if report.get("source_body") != "EBBRB" or report.get("target_body") != "ANGEL":
        raise ValueError("Expected an EBBRB-to-ANGEL difference field")
    if report.get("displacement_field", {}).get("sha256") != digest(field):
        raise ValueError("Field bytes do not match the difference report")
    for side in ("source", "target"):
        if not report.get("self_comparison", {}).get(side, {}).get("pass"):
            raise ValueError(f"Failed {side} self-comparison")
    for region, accepted in (("thigh", ("READY",)), ("hip", ("READY", "PARTIAL")),
                             ("pelvis", ("READY", "PARTIAL"))):
        if report.get("confidence_map", {}).get(region, {}).get("status") not in accepted:
            raise ValueError(f"Unsupported confidence for {region}")
    for body, key in (("EBBRB", "source_version"), ("ANGEL", "target_version")):
        if report.get(key) != body_profiles.load(body).get("asset_version"):
            raise ValueError(f"Reference version mismatch for {body}")
    source = body_model.load(body_profiles.load("EBBRB"))
    with np.load(field, allow_pickle=False) as arrays:
        vertices, displacement = arrays["src_vertices"], arrays["disp"]
        if vertices.shape != source.vertices.shape or displacement.shape != vertices.shape:
            raise ValueError("Invalid field dimensions")
        if not np.isfinite(displacement).all() or not np.isfinite(vertices).all():
            raise ValueError("Non-finite field values")
        if not np.allclose(vertices, source.vertices, rtol=0, atol=1e-7):
            raise ValueError("Field does not match the configured source body")
    recipe = json.loads((ROOT / "config/boot_recipe.json").read_text(encoding="utf-8"))
    recipe.update(policy_sha256=digest(difference), field_sha256=digest(field),
                  reference_source_hashes=source.source_hashes,
                  scope="Controlled long-boot policy. New outputs require visual and game acceptance.")
    with output.open("x", encoding="utf-8") as stream:
        json.dump(recipe, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(output)


if __name__ == "__main__":
    main()
