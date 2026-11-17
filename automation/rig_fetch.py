"""从 basegame 归档中取玩家女性骨架（animRig），供骨骼层级使用。

实测（2026-11-15）：
    basegame_1_engine.archive
      base\\characters\\entities\\player\\deformations_rigs_wa\\player_woman_base_deformations.rig
    183 骨；boneParentIndexes 与 aPoseLS/aPoseMS 自洽（local 与父级推导零误差）。

该资源只提供「父子关系」，骨骼变换仍取自 CMesh 的 boneRigMatrices。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

RIG_NAME = "player_woman_base_deformations.rig"
CONTENT_ARCHIVE = "basegame_1_engine.archive"


def fetch(cfg, *, pattern: str = RIG_NAME, force: bool = False) -> dict[str, Any]:
    """解包 basegame 里的 rig 并序列化为 JSON。已存在则跳过（force 强制重取）。"""
    from . import config as cfgmod
    from .wolvenkit_adapter import WolvenKit

    root = cfgmod.root(cfg)
    game_dir = Path(cfgmod.get(cfg, "game.dir") or "")
    archive = game_dir / "archive" / "pc" / "content" / CONTENT_ARCHIVE
    if not archive.is_file():
        raise FileNotFoundError(f"找不到 basegame 归档：{archive}")

    raw_dir = root / "references" / "rigs" / "raw"
    json_dir = root / "references" / "rigs" / "json"
    target = json_dir / f"{pattern}.json"
    if target.is_file() and not force:
        return {"skipped": True, "json": str(target), "reason": "已存在（force=True 可重取）"}

    wk = WolvenKit(cfgmod.require_path(cfg, "wolvenkit.cli"),
                   cfgmod.dir_of(cfg, "logs", create=True))
    ex = wk.extract(archive, raw_dir, pattern=f"*{pattern}")
    rigs = sorted(raw_dir.rglob(pattern))
    if not rigs:
        raise FileNotFoundError(f"解包后未找到 {pattern}（{ex.get('files')} 个文件）")
    ser = wk.serialize(rigs[0], json_dir)
    if not ser.get("json"):
        raise RuntimeError(f"序列化失败：{rigs[0]}")
    return {"skipped": False, "rig": str(rigs[0]), "json": ser["json"],
            "extract_sec": ex.get("duration_sec"), "files": ex.get("files")}
