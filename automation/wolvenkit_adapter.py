"""WolvenKit CLI 适配器。

按本机实测的 CLI 行为实现（10.0.0-beta.1 / 9.1.1 通用）：
    archive <path> -l            列出条目（stdout 每行一个 depot 名）
    extract <path> -o <dir>      解包（不带 -gp，避免解 basegame）
    convert serialize <f> -o d   转 JSON
    convert deserialize <json> -o d  回写 CR2W
    pack <dir> -o <dir>          打包，产物名为 <dir名>.archive
    hash <str>                   输出 FNV1a64（带日志前缀）

注意：CLI 出错时返回码非 0（实测 160），但仍要同时检查 stderr 文本。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .task_runner import Runner

MASK64 = 0xFFFFFFFFFFFFFFFF


def fnv1a64(text: str) -> int:
    """CP77 归档条目名 / depot 路径使用的 FNV1a64。输入统一转小写并规范化分隔符。"""
    norm = text.replace("/", "\\").lower()
    h = 0xCBF29CE484222325
    for ch in norm.encode("utf-8"):
        h ^= ch
        h = (h * 0x100000001B3) & MASK64
    return h


class WolvenKit:
    def __init__(self, cli: Path | str, logs_dir: Path, timeout: int = 3600):
        self.cli = Path(cli)
        self.runner = Runner(Path(logs_dir))
        self.timeout = int(timeout)

    # ------------------------------------------------------------- 基础
    def available(self) -> bool:
        return self.cli.is_file()

    def version(self) -> str | None:
        r = self.runner.run([self.cli, "--version"], timeout=120, label="wk_version")
        return r["stdout"].splitlines()[0].strip() if r["ok"] and r["stdout"] else None

    @staticmethod
    def _require(path: Path, kind: str = "file") -> None:
        if not path.exists():
            raise FileNotFoundError(f"{kind}不存在：{path}")

    # ------------------------------------------------------------- 查询
    def list_entries(self, archive: Path) -> dict[str, Any]:
        """列出归档条目。不落盘，直接读 stdout。"""
        archive = Path(archive)
        self._require(archive)
        r = self.runner.run([self.cli, "archive", archive, "-l"], timeout=900,
                            label="wk_list")
        entries = [ln.strip() for ln in r["stdout"].splitlines() if ln.strip()]
        entries = [e for e in entries if not e.startswith("[")]
        return {"ok": r["ok"], "entries": entries, "count": len(entries),
                "rc": r["rc"], "stderr": r["stderr"], "log": r["log"]}

    @staticmethod
    def entry_stats(entries: list[str]) -> dict[str, int]:
        stats: dict[str, int] = {}
        for e in entries:
            ext = Path(e.replace("\\", "/")).suffix.lower().lstrip(".") or "_noext"
            stats[ext] = stats.get(ext, 0) + 1
        return dict(sorted(stats.items(), key=lambda kv: -kv[1]))

    def hash_text(self, text: str) -> int | None:
        r = self.runner.run([self.cli, "hash", text], timeout=120, label="wk_hash")
        m = re.search(r"(\d{10,})", r["stdout"])
        return int(m.group(1)) if m else None

    # ------------------------------------------------------------- 操作
    def extract(self, archive: Path, outdir: Path, pattern: str | None = None) -> dict[str, Any]:
        archive, outdir = Path(archive), Path(outdir)
        self._require(archive)
        outdir.mkdir(parents=True, exist_ok=True)
        cmd = [self.cli, "extract", archive, "-o", outdir]
        if pattern:
            cmd += ["-w", pattern]
        r = self.runner.run(cmd, timeout=self.timeout, label="wk_extract")
        files = [p for p in outdir.rglob("*") if p.is_file()]
        return {**r, "outdir": str(outdir), "files": len(files),
                "bytes": sum(p.stat().st_size for p in files)}

    def serialize(self, src: Path, outdir: Path) -> dict[str, Any]:
        src, outdir = Path(src), Path(outdir)
        self._require(src)
        outdir.mkdir(parents=True, exist_ok=True)
        r = self.runner.run([self.cli, "convert", "serialize", src, "-o", outdir],
                            timeout=self.timeout, label="wk_serialize")
        produced = sorted(outdir.glob(src.name + ".json")) or sorted(outdir.glob("*.json"))
        return {**r, "json": str(produced[0]) if produced else None}

    def deserialize(self, json_path: Path, outdir: Path) -> dict[str, Any]:
        json_path, outdir = Path(json_path), Path(outdir)
        self._require(json_path)
        outdir.mkdir(parents=True, exist_ok=True)
        r = self.runner.run([self.cli, "convert", "deserialize", json_path, "-o", outdir],
                            timeout=self.timeout, label="wk_deserialize")
        stem = json_path.name
        for suffix in (".json",):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        produced = sorted(outdir.glob(stem)) or sorted(outdir.glob("*.mesh"))
        return {**r, "cr2w": str(produced[0]) if produced else None}

    def pack(self, srcdir: Path, outdir: Path) -> dict[str, Any]:
        srcdir, outdir = Path(srcdir), Path(outdir)
        if not srcdir.is_dir():
            raise NotADirectoryError(f"待打包目录不存在：{srcdir}")
        outdir.mkdir(parents=True, exist_ok=True)
        r = self.runner.run([self.cli, "pack", srcdir, "-o", outdir],
                            timeout=self.timeout, label="wk_pack")
        produced = sorted(outdir.glob(f"{srcdir.name}.archive"))
        return {**r, "archive": str(produced[0]) if produced else None}

    # ------------------------------------------------------------- 体检
    def health(self, sample_archive: Path | None = None) -> dict[str, Any]:
        """不依赖游戏的可用性体检：版本 / hash / 可选归档列举。"""
        checks: dict[str, Any] = {}
        checks["cli_exists"] = self.available()
        checks["version"] = self.version()
        got = self.hash_text("base\\characters\\test.mesh")
        checks["hash_selftest"] = {
            "cli": got, "local": fnv1a64("base\\characters\\test.mesh"),
            "match": got == fnv1a64("base\\characters\\test.mesh"),
        }
        if sample_archive:
            lst = self.list_entries(Path(sample_archive))
            checks["archive_list"] = {"ok": lst["ok"], "count": lst["count"],
                                       "sample": lst["entries"][:5]}
        checks["ok"] = bool(checks["cli_exists"] and checks["version"]
                            and checks["hash_selftest"]["match"])
        return checks

    # --------------------------------------------------- 往返与打包自检
    def roundtrip(self, mesh: Path, workdir: Path) -> dict[str, Any]:
        """serialize → deserialize，逐字节比对源文件。证明 JSON 是安全改写入口。"""
        mesh, workdir = Path(mesh), Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        ser_dir, des_dir = workdir / "ser", workdir / "deser"
        s = self.serialize(mesh, ser_dir)
        if not s.get("json"):
            return {"ok": False, "stage": "serialize", "detail": s}
        d = self.deserialize(Path(s["json"]), des_dir)
        if not d.get("cr2w"):
            return {"ok": False, "stage": "deserialize", "detail": d}
        src_bytes = mesh.read_bytes()
        new_bytes = Path(d["cr2w"]).read_bytes()
        same = src_bytes == new_bytes
        return {"ok": same, "source": str(mesh), "json": s["json"], "cr2w": d["cr2w"],
                "src_bytes": len(src_bytes), "new_bytes": len(new_bytes),
                "identical": same,
                "src_sha256": hashlib.sha256(src_bytes).hexdigest(),
                "new_sha256": hashlib.sha256(new_bytes).hexdigest(),
                "serialize_sec": s.get("duration_sec"), "deserialize_sec": d.get("duration_sec")}

    def pack_check(self, archive: Path, workdir: Path) -> dict[str, Any]:
        """列举 → 解包 → 重打包 → 再列举，比对条目集合。验证打包链路闭环。"""
        archive, workdir = Path(archive), Path(workdir)
        # 每个归档独立工作目录，避免上一次残留文件混入重打包结果（实测会多出条目）
        tag = hashlib.sha1(str(archive).encode("utf-8")).hexdigest()[:8]
        workdir = workdir / f"{archive.stem[:32]}_{tag}"
        workdir.mkdir(parents=True, exist_ok=True)
        before = self.list_entries(archive)
        if not before["ok"]:
            return {"ok": False, "stage": "list", "detail": before}
        ex_dir = workdir / "extract"
        ex = self.extract(archive, ex_dir)
        if not ex["ok"]:
            return {"ok": False, "stage": "extract", "detail": ex}
        # 解包根目录即打包根：pack 按「目录内相对路径」写条目名，
        # 若下钻一层会丢失路径前缀（实测：selftest\xxx.mesh 变成 xxx）
        pack_src = ex_dir
        out_dir = workdir / "repack"
        pk = self.pack(pack_src, out_dir)
        if not pk.get("archive") or not pk["ok"]:
            return {"ok": False, "stage": "pack", "detail": pk, "pack_src": str(pack_src)}
        after = self.list_entries(Path(pk["archive"]))
        set_before = {e.replace("/", "\\").lower() for e in before["entries"]}
        set_after = {e.replace("/", "\\").lower() for e in after["entries"]}
        return {"ok": set_before == set_after,
                "entries_before": len(set_before), "entries_after": len(set_after),
                "missing_after": sorted(set_before - set_after)[:20],
                "extra_after": sorted(set_after - set_before)[:20],
                "archive": str(pk["archive"]),
                "src_bytes": archive.stat().st_size,
                "new_bytes": Path(pk["archive"]).stat().st_size,
                "extract_sec": ex.get("duration_sec"), "pack_sec": pk.get("duration_sec")}

    def mutation_check(self, mesh: Path, workdir: Path, delta: float = 0.001) -> dict[str, Any]:
        """改动 JSON → deserialize → 再 serialize，验证修改真正写入 CR2W。

        只改 boundingBox（非几何字段），用于证明「改 JSON 能回导」这条链路，
        不改变任何顶点数据，也不会写回原始文件。
        """
        mesh, workdir = Path(mesh), Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        ser_dir, des_dir, reser_dir = workdir / "ser", workdir / "deser", workdir / "reser"
        s = self.serialize(mesh, ser_dir)
        if not s.get("json"):
            return {"ok": False, "stage": "serialize", "detail": s}

        src_json = Path(s["json"])
        data = json.loads(src_json.read_text(encoding="utf-8"))
        try:
            box = data["Data"]["RootChunk"]["boundingBox"]
        except KeyError as exc:
            return {"ok": False, "stage": "read_bbox", "error": f"字段缺失: {exc}"}
        before_val = float(box["Max"]["X"])
        box["Max"]["X"] = round(before_val + delta, 6)
        mod_json = workdir / f"mod_{src_json.name}"
        mod_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        d = self.deserialize(mod_json, des_dir)
        if not d.get("cr2w"):
            return {"ok": False, "stage": "deserialize", "detail": d}

        r = self.serialize(Path(d["cr2w"]), reser_dir)
        after_val = None
        if r.get("json"):
            back = json.loads(Path(r["json"]).read_text(encoding="utf-8"))
            after_val = float(back["Data"]["RootChunk"]["boundingBox"]["Max"]["X"])

        src_bytes = mesh.read_bytes()
        new_bytes = Path(d["cr2w"]).read_bytes()
        persisted = after_val is not None and abs(after_val - (before_val + delta)) < 1e-5
        return {"ok": bool(persisted and src_bytes != new_bytes),
                "stage": "done",
                "field": "boundingBox.Max.X",
                "before": before_val, "expected": round(before_val + delta, 6),
                "after": after_val, "persisted": persisted,
                "bytes_changed": src_bytes != new_bytes,
                "src_bytes": len(src_bytes), "new_bytes": len(new_bytes),
                "cr2w": d["cr2w"]}

    def diagnose_export(self, mesh: Path, outdir: Path,
                        gamepath: Path | None = None) -> dict[str, Any]:
        """探测 CLI export 是否可用，并把真实失败原因分类（不做假设）。"""
        mesh, outdir = Path(mesh), Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        cmd = [self.cli, "export", mesh, "-o", outdir]
        if gamepath:
            cmd += ["-gp", gamepath]
        r = self.runner.run(cmd, timeout=600, label="wk_export_probe")
        text = (r.get("stdout") or "") + "\n" + (r.get("stderr") or "")
        produced = [p for p in outdir.rglob("*") if p.is_file()]
        category = "unknown"
        if "gamepath" in text and "requires" in text:
            category = "missing_gamepath_argument"
        elif "DirectoryNotFoundException" in text or "Could not find a part of the path" in text:
            category = "missing_game_archives"
        elif "Depot" in text:
            category = "depot_not_set"
        elif produced:
            category = "ok"
        return {"ok": bool(produced), "category": category, "rc": r["rc"],
                "files": [str(p) for p in produced][:10],
                "message": text.strip().splitlines()[:6], "log": r.get("log")}
