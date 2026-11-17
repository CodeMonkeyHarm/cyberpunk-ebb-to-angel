"""统一配置：读写 config/workshop.json，所有路径都来自实际探测结果。

约定：代码里不硬编码任何外部程序路径，一律通过本模块取的配置项。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

WORKSHOP_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = WORKSHOP_ROOT / "config" / "workshop.json"

DIRS = ("config", "inbox", "projects", "references", "knowledge",
        "automation", "blender", "logs", "reports", "skills")


def default_config() -> dict[str, Any]:
    return {
        "workshop_root": str(WORKSHOP_ROOT),
        "python": {"executable": None, "version": None},
        "blender": {"exe": None, "version": None, "script_dir": "blender/scripts",
                    "timeout_sec": 1800},
        "wolvenkit": {"cli": None, "version": None, "alternates": [], "timeout_sec": 3600},
        "game": {"dir": None, "exe": None, "installed": False, "note": None},
        "depot": None,
        "cp77_addon": None,
        "dirs": {d: d for d in DIRS},
        "limits": {"subprocess_timeout_sec": 1800, "max_project_bytes": None},
        "policy": {
            "source_readonly": True,
            "backup_before_write": True,
            "require_confirm_for_game_install": True,
            "no_unverified_success": True,
        },
        "detected_at": None,
    }


def load() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"配置不存在：{CONFIG_PATH}。先运行 python automation/main.py env")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save(cfg: dict[str, Any]) -> Path:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return CONFIG_PATH


def get(cfg: dict[str, Any], dotted: str, default=None):
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def root(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("workshop_root") or WORKSHOP_ROOT)


def dir_of(cfg: dict[str, Any], key: str, create: bool = False) -> Path:
    p = root(cfg) / (cfg.get("dirs", {}).get(key) or key)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def require_path(cfg: dict[str, Any], dotted: str, kind: str = "file") -> Path:
    """取配置里的外部路径并校验存在性，缺了就明确报错（不猜）。"""
    raw = get(cfg, dotted)
    if not raw:
        raise RuntimeError(f"配置项 {dotted} 为空：需要先探测环境")
    p = Path(raw)
    exists = p.is_file() if kind == "file" else p.is_dir()
    if not exists:
        raise FileNotFoundError(f"配置项 {dotted} 指向的{kind}不存在：{p}")
    return p


def env_overrides() -> dict[str, str]:
    """可选的运行期覆盖，便于换机时不必改配置文件。"""
    keys = ("CP77_WORKSHOP_BLENDER", "CP77_WORKSHOP_WK", "CP77_WORKSHOP_GAME")
    return {k: os.environ[k] for k in keys if os.environ.get(k)}
