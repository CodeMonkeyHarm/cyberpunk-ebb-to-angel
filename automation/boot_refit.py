"""Build and check a single-mesh EBBRB long-boot refit candidate."""
from __future__ import annotations

import json
import shutil
from pathlib import Path, PureWindowsPath

import numpy as np

from audit.phase3.audit_garment_clearance import audit_clearance, geometry_changes
from audit.phase3.boots_pilot.prepare_runtime_test import inventory
from audit.phase3.chrissy_pilot.pack_candidate import pack_verified_mesh
from audit.phase3.replay_boot_policy import refit_mesh
from audit.phase3.validate_v2 import as_model, sha256
from automation.wolvenkit_adapter import WolvenKit


def run(wk: WolvenKit, archive: Path, mesh_entry: str, output: Path) -> dict:
    archive = archive.resolve(strict=True)
    output = output.resolve()
    if not archive.is_file() or archive.suffix.lower() != ".archive":
        raise ValueError("输入必须是作者原始 EBBRB .archive 文件")
    path = PureWindowsPath(mesh_entry)
    if path.anchor or ".." in path.parts or ":" in mesh_entry or path.suffix.lower() not in (".mesh", ".bin"):
        raise ValueError("网格条目必须是归档内相对 .mesh 路径或数字 .bin 路径")
    if path.suffix.lower() == ".bin" and (len(path.parts) != 1 or not path.stem.isascii() or not path.stem.isdigit()):
        raise ValueError(".bin 条目须为 WolvenKit 解包得到的数字哈希")
    mesh_entry = path.as_posix()
    if output.exists():
        raise ValueError(f"输出目录已存在：{output}")
    output.mkdir(parents=True)
    archive_sha256 = sha256(archive)
    wk = WolvenKit(wk.cli, output / "logs", timeout=wk.timeout)

    def run_cli(*arguments):
        command = [wk.cli, *map(str, arguments), "-v", "Quiet"]
        result = wk.runner.run(command, timeout=wk.timeout, label=f"boot_refit_{arguments[0]}")
        if not result["ok"]:
            raise RuntimeError(f"WolvenKit {arguments[0]}失败：{result.get('log') or result.get('error')}")

    extracted = output / "source_entries"
    result = wk.extract(archive, extracted)
    if not result["ok"] or result["files"] == 0:
        raise RuntimeError(f"归档解包失败：{result.get('log') or result.get('error')}")
    original_files = inventory(extracted)
    if mesh_entry not in original_files:
        raise ValueError(f"归档中未找到网格条目：{mesh_entry}")
    source_mesh = output / "source" / "boot.mesh"
    source_mesh.parent.mkdir()
    shutil.copyfile(extracted / mesh_entry, source_mesh)
    run_cli("convert", "serialize", source_mesh, "-o", source_mesh.parent)
    source_json = source_mesh.with_suffix(".mesh.json")
    candidate_json = output / "candidate" / "boot.mesh.json"
    refit_mesh(source_json, candidate_json)
    geometry = geometry_changes(as_model("source", source_json), as_model("candidate", candidate_json))
    if geometry["new_degenerate_indexed_triangles"] or geometry["reversed_indexed_triangles"]:
        (output / "rejected_geometry.json").write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("网格产生翻面或新增退化，已停止打包")

    packed = output / "packed"
    archive_stem = archive.stem + "_angel_candidate"
    packaged = pack_verified_mesh(source_json, candidate_json, extracted, packed, archive_stem,
                                  mesh_entry, len(original_files), run_cli=run_cli)
    mask = np.load(candidate_json.parent / "skip_mask.npy", allow_pickle=False)
    # Use the serialized mesh from the packed archive for the final geometry gate.
    audit = audit_clearance(source_json, packed / candidate_json.name, mask)
    geometry = audit["geometry"]
    if sha256(archive) != archive_sha256:
        raise RuntimeError("运行期间源归档发生变化，请在新目录重试")
    structural_pass = not (geometry["new_degenerate_indexed_triangles"] or geometry["reversed_indexed_triangles"])
    report = {
        "source_archive": str(archive), "source_archive_sha256": archive_sha256,
        "source_mesh_entry": mesh_entry, "source_mesh_sha256": original_files[mesh_entry],
        "candidate_archive": str(packed / (archive_stem + ".archive")),
        "packing": packaged, "geometry_audit": audit,
        "structural_checks": "PASS" if structural_pass else "FAIL",
        "visual_and_game_acceptance": "NOT_CHECKED",
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not structural_pass:
        raise RuntimeError(f"打包后拓扑检查失败，详见 {output / 'report.json'}")
    return report
