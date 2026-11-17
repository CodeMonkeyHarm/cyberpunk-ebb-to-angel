"""子进程执行器 + 任务状态机。

所有外部程序（Blender / WolvenKit / 打包工具）都必须经这里调用：
统一超时、统一日志、统一返回结构，禁止裸 subprocess。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


class Runner:
    def __init__(self, logs_dir: Path):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def run(self, cmd: list[str], *, cwd: Path | None = None, timeout: int = 1800,
            label: str = "run", env: dict[str, str] | None = None) -> dict[str, Any]:
        """执行一次命令。永不抛异常（除参数错误），结果里带 ok/rc/timed_out。"""
        if not cmd:
            raise ValueError("cmd 为空")
        exe = Path(cmd[0])
        if not exe.exists():
            return {"ok": False, "rc": None, "error": f"可执行文件不存在: {exe}",
                    "cmd": cmd, "stdout": "", "stderr": "", "started_at": now_iso(),
                    "duration_sec": 0.0, "timed_out": False}

        log_path = self.logs_dir / f"{_stamp()}_{label}.log"
        started = time.perf_counter()
        stdout, stderr, timed_out = "", "", False
        rc: int | None = None

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        try:
            proc = subprocess.run(
                [str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, creationflags=_CREATE_NO_WINDOW, env=merged_env,
            )
            rc, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            stderr += f"\n[TIMEOUT] 超过 {timeout}s 被终止"

        duration = round(time.perf_counter() - started, 2)
        result = {
            "ok": (rc == 0) and not timed_out,
            "rc": rc,
            "timed_out": timed_out,
            "cmd": [str(c) for c in cmd],
            "cwd": str(cwd) if cwd else None,
            "stdout": stdout,
            "stderr": stderr,
            "duration_sec": duration,
            "started_at": now_iso(),
            "log": str(log_path),
        }
        log_path.write_text(
            "# cmd\n" + " ".join(result["cmd"]) + f"\n# rc={rc} timed_out={timed_out} "
            f"duration={duration}s\n\n## stdout\n{stdout}\n\n## stderr\n{stderr}\n",
            encoding="utf-8")
        return result


class TaskState:
    """任务状态（可断点续跑）。每个 project 一个 state.json。"""

    def __init__(self, path: Path, payload: dict[str, Any] | None = None):
        self.path = Path(path)
        self.data = payload or {"task_id": self.path.parent.name, "created_at": now_iso(),
                                "updated_at": now_iso(), "status": "pending", "steps": {}}
        self._lock = threading.Lock()

    @classmethod
    def load_or_new(cls, path: Path) -> "TaskState":
        if Path(path).exists():
            try:
                return cls(path, json.loads(Path(path).read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return cls(path)

    def step(self, name: str) -> dict[str, Any]:
        return self.data["steps"].get(name) or {}

    def done(self, name: str) -> bool:
        return self.step(name).get("status") == "done"

    def mark(self, name: str, status: str, **detail) -> None:
        with self._lock:
            s = self.data["steps"].setdefault(name, {})
            s.update({"status": status, "at": now_iso(), **detail})
            if status == "failed":
                self.data["status"] = "failed"
            self.data["updated_at"] = now_iso()
            self.save()

    def set_status(self, status: str, **detail) -> None:
        self.data["status"] = status
        self.data.update(detail)
        self.data["updated_at"] = now_iso()
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def backup_file(src: Path, backup_dir: Path) -> dict[str, Any]:
    """写前备份。返回记录，同一文件多次备份加时间戳，绝不覆盖旧备份。"""
    src = Path(src)
    if not src.exists():
        return {"source": str(src), "ok": False, "error": "源文件不存在"}
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / f"{src.name}.bak_{_stamp()}"
    n = 1
    while dst.exists():
        dst = backup_dir / f"{src.name}.bak_{_stamp()}_{n}"
        n += 1
    shutil.copy2(src, dst)
    return {"source": str(src), "backup": str(dst), "ok": True,
            "src_bytes": src.stat().st_size, "dst_bytes": dst.stat().st_size}
