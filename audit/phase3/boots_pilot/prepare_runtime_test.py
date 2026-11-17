"""Build and verify two otherwise identical boots archives for a runtime A/B test."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
CLI = ROOT.parent / "tools/WolvenKit.Console-10.0.0-beta.1/WolvenKit.CLI.exe"
TEST = BASE / "runtime_test"
SOURCE = BASE / "source_archive_extract"
PART_ENTRY = Path("5416242523622288403.bin")
MESH_ENTRY = Path(
    "wizzo/characters/garment/player_equipment/feet/"
    "s1_045_boot__00chap/s1_045_wa_boot__00chap_hyst.mesh"
)
CANDIDATE_MESH = BASE / "prototype/ready_mesh" / MESH_ENTRY.name
OLD = MESH_ENTRY.as_posix().replace("/", "\\").replace("_hyst.mesh", ".mesh")
NEW = MESH_ENTRY.as_posix().replace("/", "\\")


def cli(*args: object) -> None:
    command = [str(CLI), *(str(arg) for arg in args), "-v", "Quiet"]
    run = subprocess.run(command, capture_output=True, check=True)
    if run.returncode:
        raise RuntimeError(run.stdout.decode(errors="replace"))


def mesh_references(node):
    if isinstance(node, dict):
        if node.get("$type") == "ResourcePath" and node.get("$value") in (OLD, NEW):
            yield node
        for value in node.values():
            yield from mesh_references(value)
    elif isinstance(node, list):
        for item in node:
            yield from mesh_references(item)


def route_entity() -> Path:
    folder = TEST / "routing"
    folder.mkdir()
    original = BASE / "runtime_audit/part.ent.json"
    if (BASE / "runtime_audit/part.ent").read_bytes() != (SOURCE / PART_ENTRY).read_bytes():
        raise ValueError("Part entity does not match the original archive entry")
    data = json.loads(original.read_text(encoding="utf-8"))
    refs = list(mesh_references(data["Data"]))
    if len(refs) != 3 or any(ref["$value"] != OLD for ref in refs):
        raise ValueError("Unexpected source entity mesh routes")
    for ref in refs:
        ref["$value"] = NEW
    routed = folder / "part.ent.json"
    routed.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cli("convert", "deserialize", routed, "-o", folder)
    part = folder / "part.ent"
    audit = folder / "verify"
    audit.mkdir()
    cli("convert", "serialize", part, "-o", audit)
    checked = json.loads((audit / routed.name).read_text(encoding="utf-8"))
    if checked["Data"] != data["Data"]:
        raise ValueError("Entity round trip changed data beyond the three route references")
    return part


def inventory(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): sha(p) for p in folder.rglob("*") if p.is_file()}


def sha(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main() -> None:
    TEST.mkdir()
    part = route_entity()
    source_entries = inventory(SOURCE)
    reports = {}
    extracted = {}
    for name in ("baseline", "candidate"):
        stage = TEST / f"{name}_input"
        shutil.copytree(SOURCE, stage)
        shutil.copyfile(part, stage / PART_ENTRY)
        if name == "candidate":
            shutil.copyfile(CANDIDATE_MESH, stage / MESH_ENTRY)
        output = TEST / name
        output.mkdir()
        cli("pack", stage, "-o", output)
        archive = output / "wizzo_boots_00chap.archive"
        (output / f"{stage.name}.archive").rename(archive)
        unpacked = output / "unpacked"
        cli("unbundle", archive, "-o", unpacked)
        extracted[name] = inventory(unpacked)
        if extracted[name] != inventory(stage):
            raise ValueError(f"{name} archive changed resource paths or bytes")
        reports[name] = {
            "archive_sha256": sha(archive),
            "entry_count": len(extracted[name]),
            "changed_from_original": sorted(k for k in source_entries
                                            if source_entries[k] != extracted[name][k]),
        }
    delta = [k for k in extracted["baseline"] if extracted["baseline"][k] != extracted["candidate"][k]]
    if delta != [MESH_ENTRY.as_posix()] or len(source_entries) != 20:
        raise ValueError(f"Unexpected archive delta: {delta}")
    result = {"route": NEW, "mesh_reference_count": 3, "archives": reports,
              "changed_between_tests": delta}
    (TEST / "build_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
