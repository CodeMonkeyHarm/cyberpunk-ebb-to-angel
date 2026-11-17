"""校验器：对分析/检查结果做规则判定，产出 findings。

原则：只报事实，不补猜测。缺少某项就明确记为 not_checked。
"""
from __future__ import annotations

from typing import Any


def _finding(level: str, code: str, message: str, **extra) -> dict[str, Any]:
    return {"level": level, "code": code, "message": message, **extra}


def validate_glb_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """检查 Blender 分析结果是否像个可用模型。"""
    findings: list[dict[str, Any]] = []
    if analysis.get("status") != "OK":
        return {"ok": False, "findings": [_finding("error", "analysis_failed",
                                                   analysis.get("error", "分析失败"))],
                "summary": None}

    s = analysis.get("summary") or {}
    meshes = analysis.get("meshes") or []

    if s.get("mesh_count", 0) == 0:
        findings.append(_finding("error", "no_mesh", "文件中没有 Mesh 对象"))
    if s.get("total_vertices", 0) == 0:
        findings.append(_finding("error", "no_vertices", "顶点数为 0"))
    if not s.get("has_uv"):
        findings.append(_finding("warn", "no_uv", "没有 UV 层：贴图无法正确映射"))
    if not s.get("has_vertex_groups"):
        findings.append(_finding("warn", "no_vertex_groups",
                                 "没有顶点组：可能未绑定骨架，无法随动作变形"))
    if s.get("armature_count", 0) == 0:
        findings.append(_finding("warn", "no_armature", "没有 Armature：静态模型或绑定丢失"))
    if s.get("material_count", 0) == 0:
        findings.append(_finding("warn", "no_material", "没有材质"))

    for m in meshes:
        bb = m.get("local_bbox")
        if bb:
            sizes = [bb["max"][i] - bb["min"][i] for i in range(3)]
            if max(sizes) > 10:
                findings.append(_finding("warn", "huge_bbox",
                                         f"{m['object']} 尺寸异常 {max(sizes):.2f}m，可能单位错误",
                                         object=m["object"]))
            if max(sizes) <= 0:
                findings.append(_finding("error", "degenerate_bbox",
                                         f"{m['object']} 包围盒退化", object=m["object"]))
        polys = m.get("polygons", 0)
        tris = m.get("triangles", 0)
        if tris and polys and tris / max(polys, 1) > 3.01:
            findings.append(_finding("warn", "suspicious_tris",
                                     f"{m['object']} 三角化比例异常", object=m["object"]))
        if m.get("vertex_group_count", 0) == 0:
            continue
        if m.get("vertex_group_count", 0) > 200:
            findings.append(_finding("info", "many_groups",
                                     f"{m['object']} 顶点组 {m['vertex_group_count']} 个，"
                                     "注意是否为多身形合并体", object=m["object"]))

    errors = [f for f in findings if f["level"] == "error"]
    return {"ok": not errors, "findings": findings, "summary": s}


def validate_archive_inspection(result: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if result.get("status") != "OK":
        return {"ok": False,
                "findings": [_finding("error", "archive_failed",
                                      result.get("error", "归档检查失败"))],
                "summary": None}

    if result.get("entry_count", 0) == 0:
        findings.append(_finding("error", "empty_archive", "归档内没有条目"))

    types = result.get("resource_types") or {}
    if result.get("extracted"):
        if types.get("CMesh", 0) == 0:
            findings.append(_finding("warn", "no_mesh_in_archive",
                                     "归档内未识别到 CMesh：可能无模型资源"))
        if types.get("appearance", 0) == 0 and types.get("appearance_definition", 0) == 0:
            findings.append(_finding("info", "no_appearance",
                                     "未见 appearance 资源：可能依赖外部 MOD"))
    if result.get("entries_are_hashes"):
        findings.append(_finding("info", "hash_names",
                                 "条目名为哈希：类型需解包后按 CR2W 头识别"))
    errors = [f for f in findings if f["level"] == "error"]
    return {"ok": not errors, "findings": findings,
            "summary": {"entry_count": result.get("entry_count"),
                        "extension_stats": result.get("extension_stats"),
                        "resource_types": types}}


def merge(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    findings = []
    for name, r in results.items():
        for f in r.get("findings", []):
            f = dict(f)
            f["check"] = name
            findings.append(f)
    return {"ok": all(r.get("ok") for r in results.values()),
            "findings": findings,
            "by_check": {k: bool(v.get("ok")) for k, v in results.items()}}
