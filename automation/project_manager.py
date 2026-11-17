"""项目管理：创建工程目录、登记来源、备份、状态。

每个工程 = projects/<slug>/ 下的一套固定子目录 + project.json + state.json。
原始素材只登记不移动；需就地改写前必须经 backup()。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .task_runner import TaskState, backup_file, now_iso

SUBDIRS = ("source", "work", "analysis", "converted", "build", "backup", "logs")


def slugify(name: str) -> str:
    s = re.sub(r"^Wizzo'?s?\s*", "", name, flags=re.I)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return (s[:48] or "project").lower()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Project:
    def __init__(self, root: Path):
        self.dir = Path(root)
        self.manifest_path = self.dir / "project.json"
        self.state = TaskState.load_or_new(self.dir / "state.json")
        self.data: dict[str, Any] = (json.loads(self.manifest_path.read_text(encoding="utf-8"))
                                     if self.manifest_path.exists() else {})

    # ------------------------------------------------------------ 创建
    @classmethod
    def create(cls, projects_dir: Path, name: str, source: Path | None = None,
               copy_source: bool = False) -> "Project":
        projects_dir = Path(projects_dir)
        slug = slugify(name)
        pdir = projects_dir / slug
        if pdir.exists() and (pdir / "project.json").exists():
            raise FileExistsError(f"工程已存在：{pdir}")
        for sub in SUBDIRS:
            (pdir / sub).mkdir(parents=True, exist_ok=True)
        proj = cls(pdir)
        proj.data = {
            "name": name,
            "slug": slug,
            "created_at": now_iso(),
            "workshop_root": str(projects_dir.parent),
            "source": None,
            "phase": "created",
            "policy": {"source_readonly": True, "backup_before_write": True},
        }
        if source:
            proj.attach_source(Path(source), copy=copy_source)
        proj.save()
        proj.state.set_status("created")
        return proj

    # ------------------------------------------------------------ 存档
    def save(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        return self.manifest_path

    def attach_source(self, source: Path, copy: bool = False) -> dict[str, Any]:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"来源不存在：{source}")
        rec: dict[str, Any] = {"origin": str(source),
                               "bytes": source.stat().st_size if source.is_file() else None,
                               "attached_at": now_iso(),
                               "sha256": sha256_of(source) if source.is_file() else None,
                               "copied": None, "readonly": True}
        if copy and source.is_file() and source.stat().st_size < 2 * 2**30:
            dst = self.dir / "source" / source.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                dst = dst.with_name(f"{dst.stem}.{datetime.now():%H%M%S}{dst.suffix}")
            shutil.copy2(source, dst)
            rec["copied"] = str(dst)
            rec["copied_sha256"] = sha256_of(dst)
        self.data["source"] = rec
        self.save()
        return rec

    # ------------------------------------------------------------ 路径
    def path(self, *parts: str) -> Path:
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def backup(self, files: list[Path]) -> list[dict[str, Any]]:
        return [backup_file(Path(f), self.dir / "backup") for f in files]

    def set_phase(self, phase: str, **detail) -> None:
        self.data["phase"] = phase
        self.data.update(detail)
        self.data["phase_at"] = now_iso()
        self.save()

    def log(self, event: str, **detail) -> None:
        entry = {"at": now_iso(), "event": event, **detail}
        path = self.dir / "logs" / "project.log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_projects(projects_dir: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(Path(projects_dir).glob("*/project.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        st = p.parent / "state.json"
        state = json.loads(st.read_text(encoding="utf-8")) if st.exists() else {}
        out.append({"slug": d.get("slug"), "name": d.get("name"),
                    "phase": d.get("phase"), "status": state.get("status"),
                    "dir": str(p.parent)})
    return out
