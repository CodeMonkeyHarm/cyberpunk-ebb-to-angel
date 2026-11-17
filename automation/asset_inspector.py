"""资产检查：GLB 分析（Blender）与归档资源识别（WolvenKit + CR2W 头）。

只读。所有结果写 JSON，供 validator / report 消费。
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from .blender_adapter import Blender
from .wolvenkit_adapter import WolvenKit

# CR2W 头部类型字符串 → 语义名（沿用已验证的识别表）
TYPE_TOKENS = [
    (b"entEntityTemplate", "entity_template"),
    (b"appearanceAppearanceDefinition", "appearance_definition"),
    (b"appearanceAppearanceResource", "appearance"),
    (b"entEntityResource", "entity"),
    (b"CMesh", "CMesh"),
    (b"CBitmapTexture", "texture"),
    (b"inkTextureAtlas", "inkatlas"),
    (b"Multilayer_Setup", "mlsetup"),
    (b"CMaterialInstance", "material_instance"),
    (b"CMaterialTemplate", "material_template"),
    (b"animRig", "rig"),
]


def sniff_cr2w(path: Path) -> str | None:
    try:
        head = Path(path).read_bytes()[:4096]
    except OSError:
        return None
    if not head.startswith(b"CR2W"):
        return None
    for token, name in TYPE_TOKENS:
        if token in head:
            return name
    return "CR2W_unknown"


def inspect_glb(blender: Blender, glb: Path, out_json: Path) -> dict[str, Any]:
    r = blender.analyze_glb(Path(glb), Path(out_json))
    if r.get("result") is None:
        return {"status": "FAILED", "glb": str(glb),
                "error": "Blender 未产出 JSON",
                "stdout_tail": (r.get("stdout") or "")[-800:],
                "stderr_tail": (r.get("stderr") or "")[-800:]}
    analysis = r["result"]
    analysis["_runner"] = {"rc": r.get("rc"), "duration_sec": r.get("duration_sec"),
                           "script_ok": r.get("script_ok"), "log": r.get("log")}
    return analysis


def inspect_archive(wk: WolvenKit, archive: Path, workdir: Path,
                    do_extract: bool = False) -> dict[str, Any]:
    """列举条目；可选解包并按 CR2W 头识别真实类型。"""
    archive = Path(archive)
    lst = wk.list_entries(archive)
    result: dict[str, Any] = {
        "status": "OK" if lst["ok"] else "FAILED",
        "archive": str(archive),
        "bytes": archive.stat().st_size if archive.exists() else 0,
        "entries": lst["entries"],
        "entry_count": lst["count"],
        "extension_stats": WolvenKit.entry_stats(lst["entries"]),
        "resource_types": {},
        "extracted": None,
        "list_log": lst["log"],
    }
    if not lst["ok"]:
        result["error"] = (lst.get("stderr") or "archive 列举失败")[-800:]
        return result

    hashes_only = all(Path(e).suffix.lower() in (".bin", "") for e in lst["entries"])
    result["entries_are_hashes"] = hashes_only

    if do_extract:
        outdir = Path(workdir) / "_extract"
        ex = wk.extract(archive, outdir)
        typed: dict[str, int] = {}
        files = []
        for p in sorted(outdir.rglob("*")):
            if not p.is_file():
                continue
            kind = sniff_cr2w(p)
            typed[kind or "raw"] = typed.get(kind or "raw", 0) + 1
            files.append({"path": str(p.relative_to(outdir)), "bytes": p.stat().st_size,
                          "kind": kind})
        result["resource_types"] = typed
        result["extracted"] = {"dir": str(outdir), "ok": ex["ok"],
                               "files": ex["files"], "bytes": ex["bytes"],
                               "detail": files[:200]}
        if not ex["ok"]:
            result["status"] = "FAILED"
            result["error"] = (ex.get("stderr") or "解包失败")[-800:]
    return result


def inspect_source_package(path: Path) -> dict[str, Any]:
    """不落盘地看源包内容（zip 直接读；rar 只报大小，需外部工具）。"""
    path = Path(path)
    out: dict[str, Any] = {"path": str(path), "bytes": path.stat().st_size,
                            "kind": path.suffix.lower().lstrip(".")}
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
            out.update({"status": "OK", "entry_count": len(names),
                        "entries": names[:200],
                        "extension_stats": WolvenKit.entry_stats(names)})
        except zipfile.BadZipFile as exc:
            out.update({"status": "FAILED", "error": f"zip 损坏: {exc}"})
    else:
        out.update({"status": "PARTIAL",
                    "note": "非 zip 容器，需解包后才能列举（本机用 UnRAR.exe）"})
    return out
