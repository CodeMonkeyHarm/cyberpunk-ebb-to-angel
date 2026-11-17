"""Blender 后台适配器。

Blender 只做分析与几何处理，不负责文件管理。脚本通过 -- 之后的参数接收输入，
结果写 JSON 文件（结构化交换），stdout 只用于人读日志。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .task_runner import Runner

OK_MARK = "WBX_SCRIPT_OK"


class Blender:
    def __init__(self, exe: Path | str, scripts_dir: Path, logs_dir: Path,
                 timeout: int = 1800):
        self.exe = Path(exe)
        self.scripts_dir = Path(scripts_dir)
        self.runner = Runner(Path(logs_dir))
        self.timeout = int(timeout)

    def available(self) -> bool:
        return self.exe.is_file()

    def version(self) -> str | None:
        r = self.runner.run([self.exe, "--version"], timeout=120, label="blender_version")
        return r["stdout"].splitlines()[0].replace("Blender", "").strip() if r["ok"] else None

    def run_script(self, script: str, args: list[str], *, report_path: Path | None = None,
                   timeout: int | None = None, label: str | None = None) -> dict[str, Any]:
        """后台执行 blender/scripts/<script>，参数放在 -- 之后。

        返回 {ok, result(读取 report_path 的 JSON 或 None), stdout, stderr, ...}
        """
        script_path = self.scripts_dir / script
        if not script_path.is_file():
            raise FileNotFoundError(f"脚本不存在：{script_path}")
        if not self.available():
            raise FileNotFoundError(f"Blender 不可用：{self.exe}")
        cmd = [self.exe, "-b", "--factory-startup", "--python", script_path, "--", *args]
        r = self.runner.run(cmd, timeout=timeout or self.timeout,
                            label=label or script.replace(".py", ""))
        payload = None
        if report_path is not None and Path(report_path).exists():
            try:
                payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                r["parse_error"] = str(exc)
        r["result"] = payload
        r["script_ok"] = OK_MARK in (r.get("stdout") or "")
        return r

    def analyze_glb(self, glb: Path, out_json: Path, *, detail: bool = True) -> dict[str, Any]:
        glb, out_json = Path(glb), Path(out_json)
        if not glb.is_file():
            raise FileNotFoundError(f"glb 不存在：{glb}")
        out_json.parent.mkdir(parents=True, exist_ok=True)
        args = ["--glb", str(glb), "--out", str(out_json)]
        if detail:
            args.append("--detail")
        return self.run_script("analyze_glb.py", args, report_path=out_json,
                               label="glb_analyze")
