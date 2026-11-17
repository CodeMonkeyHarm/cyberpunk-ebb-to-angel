"""身形档案（body profile）：把「哪个身形、数据在哪、产物叫什么」从代码里抽出来。

档案位置：`config/bodies/<BODY_ID>.json`，schema = `cp77.body.profile/v1`。

新增身形只需加一个 JSON，不需要改 `reference_builder` / `body_morphology` / `body_diff`。

约定：
- 相对路径按 workshop 根解析；绝对路径原样使用。
- `output.*` 支持 `{body_id}` / `{asset_version}` 占位符。
- `available=false` 的档案（如 EBB 未接入）允许 `source.mesh_json` 为 null，
  调用方在构建前必须检查，不允许用占位数据生成任何资产。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROFILE_DIR = Path(__file__).resolve().parent.parent / "config" / "bodies"
SCHEMA = "cp77.body.profile/v1"
REQUIRED = ("schema", "body_id", "available", "status", "source", "output")


class ProfileError(RuntimeError):
    """档案缺失、结构非法或数据源未就绪。"""


def _workshop_root() -> Path:
    return Path(__file__).resolve().parent.parent


def list_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.json"))


def load(body_id: str) -> dict[str, Any]:
    body_id = (body_id or "").strip().upper()
    if not body_id:
        raise ProfileError("body_id 不能为空")
    path = PROFILE_DIR / f"{body_id}.json"
    if not path.is_file():
        avail = ", ".join(list_profiles()) or "（无）"
        raise ProfileError(f"找不到身形档案 {path}；可用：{avail}")
    prof = json.loads(path.read_text(encoding="utf-8"))
    validate(prof, source=path)
    prof["_path"] = str(path)
    return prof


def validate(prof: dict[str, Any], *, source: str | Path = "<dict>") -> None:
    missing = [k for k in REQUIRED if k not in prof]
    if missing:
        raise ProfileError(f"{source}: 缺少字段 {missing}")
    if prof["schema"] != SCHEMA:
        raise ProfileError(f"{source}: schema 应为 {SCHEMA}，实际 {prof['schema']}")
    if prof["body_id"] != prof["body_id"].upper():
        raise ProfileError(f"{source}: body_id 必须大写，实际 {prof['body_id']}")
    for key in ("output",):
        if not isinstance(prof[key], dict):
            raise ProfileError(f"{source}: {key} 必须是对象")
    for key in ("dir", "static", "skinned", "skeleton", "weights", "manifest"):
        if key not in prof["output"]:
            raise ProfileError(f"{source}: output 缺少 {key}")
    # 数据源一致性：available=true 必须给 mesh_json，false 时必须为空
    src = prof["source"]
    if prof["available"] and not src.get("mesh_json"):
        raise ProfileError(f"{source}: available=true 但 source.mesh_json 为空")
    if not prof["available"] and src.get("mesh_json"):
        raise ProfileError(f"{source}: available=false 却填了 source.mesh_json，容易误用占位数据")


def resolve(path_like: str | None) -> Path | None:
    """相对路径按 workshop 根解析；绝对路径原样返回。"""
    if not path_like:
        return None
    p = Path(path_like)
    return p if p.is_absolute() else (_workshop_root() / p)


def _expand(template: str, prof: dict[str, Any]) -> str:
    return (template.replace("{body_id}", prof["body_id"])
                    .replace("{asset_version}", str(prof.get("asset_version", ""))))


def output_dir(prof: dict[str, Any], *, override: str | Path | None = None) -> Path:
    if override:
        return Path(override)
    return resolve(_expand(prof["output"]["dir"], prof))


def output_paths(prof: dict[str, Any], *, override: str | Path | None = None) -> dict[str, Path]:
    base = output_dir(prof, override=override)
    out: dict[str, Path] = {"dir": base}
    for key, tmpl in prof["output"].items():
        if key == "dir":
            continue
        out[key] = base / _expand(tmpl, prof)
    return out


def require_source(prof: dict[str, Any]) -> dict[str, Path]:
    """构建前的硬闸门：数据源不存在就直接报错，不生成任何资产。"""
    if not prof["available"]:
        raise ProfileError(
            f"身形 {prof['body_id']} 状态为 {prof['status']}：尚未接入数据源，"
            "不允许生成任何参考资产或差异场（差异场状态应为 PENDING）")
    missing: list[str] = []
    resolved: dict[str, Path] = {}
    for key in ("mesh_json", "raw_mesh"):
        p = resolve(prof["source"].get(key))
        if p is None or not p.is_file():
            missing.append(f"{key}={p}")
        else:
            resolved[key] = p
    if missing:
        raise ProfileError(f"身形 {prof['body_id']} 数据源缺失：{'; '.join(missing)}")
    packs = prof["source"].get("packs") or []
    resolved["packs"] = [p for p in (resolve(x) for x in packs) if p and p.is_file()]
    rig = resolve((prof.get("rig") or {}).get("rig_json"))
    if rig and rig.is_file():
        resolved["rig_json"] = rig
    return resolved


def status_table() -> list[dict[str, Any]]:
    rows = []
    for bid in list_profiles():
        prof = load(bid)
        src = prof["source"]
        rows.append({
            "body_id": prof["body_id"],
            "status": prof["status"],
            "available": prof["available"],
            "asset_version": prof.get("asset_version"),
            "mesh_json": src.get("mesh_json"),
            "mesh_json_exists": bool(src.get("mesh_json")
                                     and (resolve(src["mesh_json"]) or Path()).is_file()),
            "output_dir": str(output_dir(prof)),
        })
    return rows
