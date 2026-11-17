"""环境探测：实际执行检测，不猜测路径与版本。

所有结论都来自真实调用结果；探测失败的项写 ok=False + 原因，不填默认值。
"""
from __future__ import annotations

import glob
import re
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import config as cfgmod
from .task_runner import Runner, now_iso


def _run_quick(cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    """轻量执行（探测用），不经 Runner 以免产生大量日志文件。"""
    if not cmd or not Path(cmd[0]).exists():
        return {"ok": False, "rc": None, "out": "", "err": f"不存在: {cmd[0] if cmd else ''}"}
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        return {"ok": p.returncode == 0, "rc": p.returncode,
                "out": (p.stdout or "").strip(), "err": (p.stderr or "").strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": None, "out": "", "err": f"超时 {timeout}s"}


def detect_os() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "platform": sys.platform,
        "node": platform.node(),
    }


def detect_python() -> dict[str, Any]:
    return {
        "executable": sys.executable,
        "version": sys.version.split()[0],
        "impl": platform.python_implementation(),
        "bitness": platform.architecture()[0],
    }


# ------------------------------------------------------------------ Blender
def _blender_candidates() -> list[Path]:
    pats = [
        r"C:\Program Files\Blender Foundation\*\blender.exe",
        r"C:\Program Files (x86)\Blender Foundation\*\blender.exe",
        str(Path.home() / r"AppData\Local\Programs\Blender Foundation\*\blender.exe"),
        str(Path.home() / r"AppData\Roaming\Blender Foundation\*\blender.exe"),
    ]
    found: list[Path] = []
    env_home = os.environ.get("BLENDER_HOME")
    if env_home:
        found.append(Path(env_home) / "blender.exe")
    for pat in pats:
        found += [Path(p) for p in glob.glob(pat)]
    which = shutil.which("blender")
    if which:
        found.append(Path(which))
    uniq = {str(p).lower(): p for p in found if Path(p).exists()}
    return sorted(uniq.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def detect_blender(script_dir: Path) -> dict[str, Any]:
    cands = _blender_candidates()
    out: dict[str, Any] = {"candidates": [str(p) for p in cands], "exe": None,
                           "version": None, "background_ok": False,
                           "bpy_version": None, "python_version": None,
                           "cp77_addon": None, "error": None}
    if not cands:
        out["error"] = "未找到 blender.exe（已搜 Program Files / 用户目录 / PATH）"
        return out
    exe = cands[0]
    out["exe"] = str(exe)
    ver = _run_quick([str(exe), "--version"], timeout=120)
    if ver["ok"]:
        first = ver["out"].splitlines()[0] if ver["out"] else ""
        out["version"] = first.replace("Blender", "").strip() or None
    # 后台启动 + Python API 实跑
    probe = ("import bpy,sys,addon_utils;"
             "print('BPY='+bpy.app.version_string);"
             "print('PY='+sys.version.split()[0]);"
             "print('ADDON='+','.join(sorted(m.__name__ for m in addon_utils.modules() "
             "if 'cp77' in m.__name__.lower())))")
    r = _run_quick([str(exe), "-b", "--factory-startup", "--python-expr", probe], timeout=300)
    out["background_ok"] = r["ok"] and "BPY=" in r["out"]
    for line in r["out"].splitlines():
        if line.startswith("BPY="):
            out["bpy_version"] = line[4:].strip()
        elif line.startswith("PY="):
            out["python_version"] = line[3:].strip()
        elif line.startswith("ADDON="):
            names = [n for n in line[6:].split(",") if n]
            out["cp77_addon"] = names[0] if names else None
    if not out["background_ok"]:
        out["error"] = (r["err"] or r["out"] or "后台启动失败")[-500:]
    return out


# --------------------------------------------------------------- WolvenKit
def _wk_candidates(workshop_root: Path) -> list[Path]:
    out: list[Path] = []
    env_cli = os.environ.get("CP77_WORKSHOP_WK")
    if env_cli:
        out.append(Path(env_cli))
    roots = [workshop_root, workshop_root / "references",
             workshop_root.parent / "tools"]
    for base in roots:
        if not base or not Path(base).exists():
            continue
        out += [Path(p) for p in glob.glob(str(Path(base) / "**" / "WolvenKit.CLI.exe"),
                                          recursive=True)]
    which = shutil.which("WolvenKit.CLI")
    if which:
        out.append(Path(which))
    uniq = {str(p).lower(): p for p in out if Path(p).exists()}
    # 版本目录名越新优先（10.x 在 9.x 前），再按修改时间
    return sorted(uniq.values(), key=lambda p: (str(p), p.stat().st_mtime), reverse=True)


def detect_wolvenkit(workshop_root: Path) -> dict[str, Any]:
    cands = _wk_candidates(workshop_root)
    info: dict[str, Any] = {"candidates": [], "cli": None, "version": None,
                            "subcommands": [], "convert_subcommands": [],
                            "error": None}

    def ver_key(v: str | None):
        """按主版本号排序；同主版本时正式版优于 beta。"""
        if not v:
            return (-1, -1)
        nums = re.findall(r"\d+", v.split("-")[0])
        major = tuple(int(n) for n in nums[:3]) if nums else (0,)
        return (major, 0 if "-" in v else 1)

    for p in cands:
        v = _run_quick([str(p), "--version"], timeout=120)
        info["candidates"].append({"path": str(p),
                                    "version": v["out"].splitlines()[0].strip() if v["ok"] and v["out"] else None,
                                    "ok": v["ok"]})
    valid = [c for c in info["candidates"] if c["version"]]
    if not valid:
        info["error"] = "未找到可用的 WolvenKit.CLI.exe（--version 无输出）"
        return info
    valid.sort(key=lambda c: ver_key(c["version"]), reverse=True)
    best = valid[0]
    info["cli"], info["version"] = best["path"], best["version"]
    h = _run_quick([info["cli"], "--help"], timeout=120)
    lines = h["out"].splitlines()
    cmds = []
    in_cmds = False
    for line in lines:
        if line.strip().lower().startswith("commands:"):
            in_cmds = True
            continue
        if in_cmds and line.startswith("  ") and line.strip():
            cmds.append(line.strip().split()[0].rstrip(","))
    info["subcommands"] = cmds
    c = _run_quick([info["cli"], "convert", "--help"], timeout=120)
    sub = []
    for line in c["out"].splitlines():
        s = line.strip()
        if s.startswith(("d,", "s,")):
            sub.append(s.split("<")[0].strip())
    info["convert_subcommands"] = sub
    # 功能实测：hash 命令（不依赖游戏）
    hsh = _run_quick([info["cli"], "hash", "base\\characters\\test.mesh"], timeout=120)
    line = next((l for l in hsh["out"].splitlines() if "Information" in l), "")
    info["hash_selftest"] = {"ok": bool(line), "output": line}
    return info


# ---------------------------------------------------------------- 游戏本体
def detect_game(steam_libs: list[Path] | None = None) -> dict[str, Any]:
    libs = steam_libs or [Path(r"D:\steam"), Path(r"C:\Program Files (x86)\Steam")]
    out: dict[str, Any] = {"dir": None, "exe": None, "installed": False,
                            "checked": [], "note": None}
    for lib in libs:
        game = Path(lib) / "steamapps" / "common" / "Cyberpunk 2077"
        if not game.exists():
            continue
        exe = game / "bin" / "x64" / "Cyberpunk2077.exe"
        manifest = Path(lib) / "steamapps" / "appmanifest_1091500.acf"
        files = sum(1 for _ in game.rglob("*") if _.is_file())
        out["checked"].append({"dir": str(game), "exe": str(exe), "exe_exists": exe.exists(),
                               "appmanifest": manifest.exists(), "file_count": files})
        if exe.exists():
            out.update({"dir": str(game), "exe": str(exe), "installed": True})
            return out
        out["dir"] = str(game)
        out["note"] = (f"目录存在但游戏本体不完整：exe 缺失、文件数 {files}、"
                       f"appmanifest_1091500 {'存在' if manifest.exists() else '缺失'}")
    if out["dir"] is None:
        out["note"] = "未在已检查的 Steam 库中找到 Cyberpunk 2077 目录"
    return out


# ------------------------------------------------------------------ 权限
def detect_permissions(workshop_root: Path) -> dict[str, Any]:
    res: dict[str, Any] = {"dirs": {}, "disk": {}}
    for name in cfgmod.DIRS:
        d = workshop_root / name
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f".perm_probe_{os.getpid()}"
        try:
            probe.write_text("ok", encoding="utf-8")
            txt = probe.read_text(encoding="utf-8")
            probe.unlink()
            res["dirs"][name] = {"path": str(d), "writable": txt == "ok"}
        except OSError as exc:
            res["dirs"][name] = {"path": str(d), "writable": False, "error": str(exc)}
    try:
        usage = shutil.disk_usage(workshop_root)
        res["disk"] = {"free_gb": round(usage.free / 2**30, 1),
                       "total_gb": round(usage.total / 2**30, 1)}
    except OSError as exc:
        res["disk"] = {"error": str(exc)}
    return res


# ------------------------------------------------------------------- 汇总
def probe_all(workshop_root: Path) -> dict[str, Any]:
    workshop_root = Path(workshop_root)
    cfg = cfgmod.default_config()
    py = detect_python()
    blender = detect_blender(workshop_root / "blender" / "scripts")
    wk = detect_wolvenkit(workshop_root)
    game = detect_game()
    perms = detect_permissions(workshop_root)

    cfg["python"] = {"executable": py["executable"], "version": py["version"]}
    cfg["blender"].update({"exe": blender["exe"], "version": blender["version"],
                           "cp77_addon": blender["cp77_addon"]})
    cfg["wolvenkit"].update({"cli": wk["cli"], "version": wk["version"],
                             "alternates": [c["path"] for c in wk["candidates"] if c["path"] != wk["cli"]]})
    cfg["game"].update({"dir": game["dir"], "exe": game["exe"],
                        "installed": game["installed"], "note": game["note"]})
    cfg["cp77_addon"] = blender["cp77_addon"]
    cfg["detected_at"] = now_iso()

    return {
        "generated_at": now_iso(),
        "os": detect_os(),
        "python": py,
        "blender": blender,
        "wolvenkit": wk,
        "game": game,
        "permissions": perms,
        "workshop_root": str(workshop_root),
        "config_candidate": cfg,
    }
