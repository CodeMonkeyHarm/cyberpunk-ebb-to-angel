"""Add a small local underbust margin to the statically accepted Dolly v1."""
import json
import numpy as np

from audit.phase3.prototype_dolly_chest import PILOT, SOURCE, rebuild
from audit.phase3.prototype_stella_lateral_clearance import ease
from audit.phase3.audit_garment_clearance import geometry_changes
from audit.phase3.validate_v2 import as_model
from automation.gltf_skin import GlbBuilder, write_glb


def main():
    name = "fairyexe_dollygogomini_dress1_w_angel.mesh.json"
    source = as_model("source", SOURCE)
    previous = as_model("v1", PILOT / "candidate_v1/roundtrip_json" / name)
    x, y, z = previous.vertices.T
    mask = (ease(y, .050, .101) * (1 - ease(abs(x), .102, .158))
            * ease(z, 1.14, 1.22) * (1 - ease(z, 1.32, 1.39)))
    trial = previous.vertices.copy()
    # shortcut: extra clearance is a runtime hypothesis until walking/running are retested.
    trial[:, 1] += mask * .003
    output = PILOT / "candidate_v2"
    output.mkdir(exist_ok=True)
    path = output / name
    rebuild(source, trial, path)
    candidate = as_model("v2", path)
    assert np.array_equal(previous.triangles, candidate.triangles)
    assert np.array_equal(previous.vertices[:, [0, 2]], candidate.vertices[:, [0, 2]])
    assert np.max(abs(previous.vertices[mask == 0] - candidate.vertices[mask == 0])) < 1e-9
    assert all(a[key] == b[key] for a, b in zip(previous.geo["chunks"], candidate.geo["chunks"], strict=True)
               for key in ("joints0", "joints1", "weights0", "weights1"))
    verification = geometry_changes(previous, candidate)
    assert verification["max_displacement_mm"] <= 3.01
    assert verification["new_degenerate_indexed_triangles"] == verification["reversed_indexed_triangles"] == 0
    verification["scope"] = "3 mm smooth front-only underbust/abdomen clearance hypothesis; runtime pending"
    (output / "geometry.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    for model in (previous, candidate):
        builder = GlbBuilder()
        glb = builder.build(model.geo, skinned=False, generator="Dolly motion margin comparison", body_id=model.body_id)
        write_glb(glb["gltf"], builder.bin, output / f"{model.body_id}.glb")
    print(json.dumps(verification))


if __name__ == "__main__":
    main()
