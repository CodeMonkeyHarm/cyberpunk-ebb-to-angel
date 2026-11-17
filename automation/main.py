"""Cyberpunk 2077 智能服装转换工作站 —— 主控 CLI。

用法：
    python automation/main.py env                     环境探测 → config + reports/environment-report.md
    python automation/main.py project new <名称> [--source <路径>] [--copy-source]
    python automation/main.py project list
    python automation/main.py inspect glb <file.glb> [--project <slug>]
    python automation/main.py inspect archive <file.archive> [--project <slug>] [--extract]
    python automation/main.py wk health [--archive <file.archive>]
    python automation/main.py garment-audit <source.mesh.json> <candidate.mesh.json> --out <report.json>
    python automation/main.py boot-refit <source.archive> --mesh-entry <path> --out <new_directory>
    python automation/main.py selftest [--glb <file.glb>]
    python automation/main.py status
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # 允许直接 python automation/main.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "automation"

from automation import asset_inspector, config as cfgmod, env_probe, project_manager, \
    reference_builder, reference_report, report_generator, validator
from automation.blender_adapter import Blender
from automation.task_runner import Runner, now_iso
from automation.wolvenkit_adapter import WolvenKit

ROOT = Path(__file__).resolve().parent.parent


def out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def get_cfg() -> dict:
    return cfgmod.load()


def make_wk(cfg: dict) -> WolvenKit:
    return WolvenKit(cfgmod.require_path(cfg, "wolvenkit.cli"),
                     cfgmod.dir_of(cfg, "logs", create=True),
                     timeout=int(cfgmod.get(cfg, "wolvenkit.timeout_sec", 3600)))


def make_blender(cfg: dict) -> Blender:
    return Blender(cfgmod.require_path(cfg, "blender.exe"),
                   cfgmod.root(cfg) / cfgmod.get(cfg, "blender.script_dir", "blender/scripts"),
                   cfgmod.dir_of(cfg, "logs", create=True),
                   timeout=int(cfgmod.get(cfg, "blender.timeout_sec", 1800)))


# ------------------------------------------------------------------ env
def cmd_env(args) -> int:
    print("探测环境（实际执行，不猜）…", file=sys.stderr)
    probe = env_probe.probe_all(ROOT)
    cfg = probe["config_candidate"]
    cfgmod.save(cfg)

    rep_dir = cfgmod.dir_of(cfg, "reports", create=True)
    md_path = report_generator.write(rep_dir / "environment-report.md",
                                     report_generator.env_markdown(probe))
    json_path = rep_dir / "environment-report.json"
    json_path.write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")

    blockers = []
    if not probe["blender"]["background_ok"]:
        blockers.append("Blender 后台不可用")
    if not probe["wolvenkit"].get("cli"):
        blockers.append("WolvenKit CLI 不可用")
    if not probe["game"]["installed"]:
        blockers.append("游戏本体不可用（无法安装/游戏内验证）")

    out({"config": str(cfgmod.CONFIG_PATH),
         "report_md": str(md_path), "report_json": str(json_path),
         "blender": probe["blender"]["version"],
         "blender_background_ok": probe["blender"]["background_ok"],
         "wolvenkit": probe["wolvenkit"]["version"],
         "game_installed": probe["game"]["installed"],
         "blockers": blockers})
    # 核心工具链齐备即算通过；游戏本体缺失只记录，不阻断（它影响的是验证阶段）
    core_ok = probe["blender"]["background_ok"] and bool(probe["wolvenkit"].get("cli"))
    return 0 if core_ok else 1


# -------------------------------------------------------------- project
def cmd_project(args) -> int:
    cfg = get_cfg()
    pdir = cfgmod.dir_of(cfg, "projects", create=True)
    if args.action == "new":
        proj = project_manager.Project.create(
            pdir, args.name, Path(args.source) if args.source else None,
            copy_source=bool(args.copy_source))
        out({"project": str(proj.dir), "slug": proj.data["slug"],
             "source": proj.data.get("source"),
             "dirs": sorted(p.name for p in proj.dir.iterdir() if p.is_dir())})
        return 0
    if args.action == "list":
        out(project_manager.list_projects(pdir))
        return 0
    if args.action == "show":
        proj_dir = pdir / project_manager.slugify(args.name)
        if not (proj_dir / "project.json").exists():
            print(f"工程不存在：{proj_dir}", file=sys.stderr)
            return 2
        out(json.loads((proj_dir / "project.json").read_text(encoding="utf-8")))
        return 0
    return 2


# -------------------------------------------------------------- inspect
def _resolve_project(cfg: dict, slug: str | None):
    if not slug:
        return None
    pdir = cfgmod.dir_of(cfg, "projects") / project_manager.slugify(slug)
    if not (pdir / "project.json").exists():
        raise FileNotFoundError(f"工程不存在：{pdir}")
    return project_manager.Project(pdir)


def cmd_inspect(args) -> int:
    cfg = get_cfg()
    proj = _resolve_project(cfg, args.project)
    target = Path(args.target).resolve()
    if not target.exists():
        print(f"输入不存在：{target}", file=sys.stderr)
        return 2

    if args.kind == "glb":
        blender = make_blender(cfg)
        outdir = (proj.dir / "analysis") if proj else cfgmod.dir_of(cfg, "reports", create=True)
        json_path = outdir / f"glb_{target.stem}.json"
        analysis = asset_inspector.inspect_glb(blender, target, json_path)
        val = validator.validate_glb_analysis(analysis)
        md = report_generator.inspect_markdown(analysis, val, None,
                                              title=f"GLB 分析：{target.name}")
        md_path = outdir / f"glb_{target.stem}.md"
        report_generator.write(md_path, md)
        if proj:
            proj.log("inspect_glb", target=str(target), ok=val["ok"])
        out({"analysis_json": str(json_path), "report_md": str(md_path),
             "ok": val["ok"], "findings": val["findings"],
             "summary": analysis.get("summary")})
        return 0 if val["ok"] else 1

    wk = make_wk(cfg)
    workdir = (proj.dir / "work") if proj else cfgmod.dir_of(cfg, "projects", create=True) / "_inspect"
    result = asset_inspector.inspect_archive(wk, target, workdir, do_extract=bool(args.extract))
    val = validator.validate_archive_inspection(result)
    outdir = (proj.dir / "analysis") if proj else cfgmod.dir_of(cfg, "reports", create=True)
    json_path = outdir / f"archive_{target.stem}.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md = report_generator.inspect_markdown(None, val, result,
                                           title=f"归档检查：{target.name}")
    md_path = outdir / f"archive_{target.stem}.md"
    report_generator.write(md_path, md)
    if proj:
        proj.log("inspect_archive", target=str(target), ok=val["ok"])
    out({"analysis_json": str(json_path), "report_md": str(md_path),
         "ok": val["ok"], "entry_count": result.get("entry_count"),
         "findings": val["findings"]})
    return 0 if val["ok"] else 1


# ------------------------------------------------------------ wolvenkit
def cmd_wk(args) -> int:
    cfg = get_cfg()
    wk = make_wk(cfg)
    workdir = Path(args.workdir) if args.workdir else \
        cfgmod.dir_of(cfg, "projects", create=True) / "_wk_work" / args.action
    if args.action == "health":
        h = wk.health(Path(args.archive) if args.archive else None)
        out(h)
        return 0 if h["ok"] else 1
    if args.action == "roundtrip":
        if not args.mesh:
            print("需要 --mesh <file.mesh>", file=sys.stderr)
            return 2
        r = wk.roundtrip(Path(args.mesh), workdir)
        out(r)
        return 0 if r["ok"] else 1
    if args.action == "pack-check":
        if not args.archive:
            print("需要 --archive <file.archive>", file=sys.stderr)
            return 2
        r = wk.pack_check(Path(args.archive), workdir)
        out(r)
        return 0 if r["ok"] else 1
    if args.action == "mutation-check":
        if not args.mesh:
            print("需要 --mesh <file.mesh>", file=sys.stderr)
            return 2
        r = wk.mutation_check(Path(args.mesh), workdir)
        out(r)
        return 0 if r["ok"] else 1
    if args.action == "export-probe":
        if not args.mesh:
            print("需要 --mesh <file.mesh>", file=sys.stderr)
            return 2
        gp = Path(args.gamepath) if args.gamepath else (
            Path(cfgmod.get(cfg, "game.dir")) if cfgmod.get(cfg, "game.dir") else None)
        r = wk.diagnose_export(Path(args.mesh), workdir, gp)
        r["gamepath_used"] = str(gp) if gp else None
        out(r)
        return 0 if r["ok"] else 1
    return 2


# ------------------------------------------------------------- selftest
def cmd_selftest(args) -> int:
    cfg = get_cfg()
    steps: list[dict] = []
    runner = Runner(cfgmod.dir_of(cfg, "logs", create=True))

    def step(name, result, note="", detail=None, duration=None, evidence=None):
        steps.append({"name": name, "result": result, "note": note,
                      "detail": detail, "duration_sec": duration,
                      "evidence": evidence})
        if proj is not None:
            proj.state.mark(name, "done" if result == "PASS" else
                            ("skipped" if result == "SKIP" else "failed"),
                            note=note, evidence=evidence)
        print(f"[{result}] {name} — {note}", file=sys.stderr)

    # 1) 创建工程
    pdir = cfgmod.dir_of(cfg, "projects", create=True)
    name = f"selftest {args.stamp}"
    try:
        proj = project_manager.Project.create(pdir, name)
        step("创建工程", "PASS", f"slug={proj.data['slug']}", evidence=str(proj.dir))
    except Exception as exc:  # noqa: BLE001
        step("创建工程", "FAIL", str(exc))
        proj = None

    # 2) 备份
    if proj:
        try:
            f = proj.dir / "work" / "backup_probe.txt"
            f.write_text("original", encoding="utf-8")
            rec = proj.backup([f])[0]
            same = Path(rec["backup"]).read_text(encoding="utf-8") == "original"
            f.write_text("modified", encoding="utf-8")
            step("备份文件", "PASS" if rec["ok"] and same else "FAIL",
                 f"{rec['backup']}", evidence=rec["backup"])
        except Exception as exc:  # noqa: BLE001
            step("备份文件", "FAIL", str(exc))

    # 3) Blender 运行 + GLB 分析
    glb = Path(args.glb) if args.glb else None
    if glb and glb.exists():
        try:
            blender = make_blender(cfg)
            ajson = proj.dir / "analysis" / f"glb_{glb.stem}.json" if proj else None
            a = asset_inspector.inspect_glb(blender, glb, ajson)
            ok = a.get("status") == "OK" and (a.get("summary") or {}).get("mesh_count", 0) > 0
            step("Blender 运行 + GLB 分析", "PASS" if ok else "FAIL",
                 f"mesh={(a.get('summary') or {}).get('mesh_count')} "
                 f"verts={(a.get('summary') or {}).get('total_vertices')} "
                 f"{round(a['_runner']['duration_sec'], 1)}s",
                 detail=a.get("summary"), duration=a.get("_runner", {}).get("duration_sec"),
                 evidence=str(ajson))
        except Exception as exc:  # noqa: BLE001
            step("Blender 运行 + GLB 分析", "FAIL", str(exc))
    else:
        step("Blender 运行 + GLB 分析", "SKIP", "未提供 --glb 且 inbox 无样本")

    # 4) WolvenKit 环境检查
    try:
        wk = make_wk(cfg)
        h = wk.health(Path(args.archive) if args.archive else None)
        step("WolvenKit 环境检查", "PASS" if h["ok"] else "FAIL",
             f"v{h['version']} hash_match={h['hash_selftest']['match']}", detail=h,
             evidence=cfgmod.get(cfg, "wolvenkit.cli"))
        wk_cli = cfgmod.get(cfg, "wolvenkit.cli")
    except Exception as exc:  # noqa: BLE001
        step("WolvenKit 环境检查", "FAIL", str(exc))

    # 4.1) 归档列举 + 解包重打包闭环（有样本才做）
    if args.archive and Path(args.archive).exists():
        try:
            wk = make_wk(cfg)
            lst = wk.list_entries(Path(args.archive))
            step("归档条目列举", "PASS" if lst["ok"] and lst["count"] else "FAIL",
                 f"{lst['count']} 条", detail={"sample": lst["entries"][:5]},
                 evidence=str(args.archive))
        except Exception as exc:  # noqa: BLE001
            step("归档条目列举", "FAIL", str(exc))
        try:
            wk = make_wk(cfg)
            pc = wk.pack_check(Path(args.archive),
                               cfgmod.dir_of(cfg, "projects", create=True) / "_selftest_wk")
            step("解包→重打包闭环", "PASS" if pc["ok"] else "FAIL",
                 f"{pc.get('entries_before')}→{pc.get('entries_after')} 条",
                 detail={k: pc.get(k) for k in ("ok", "missing_after", "extra_after",
                                                "src_bytes", "new_bytes")},
                 duration=round((pc.get("extract_sec") or 0) + (pc.get("pack_sec") or 0), 1),
                 evidence=pc.get("archive"))
        except Exception as exc:  # noqa: BLE001
            step("解包→重打包闭环", "FAIL", str(exc))
    else:
        step("归档条目列举", "SKIP", "未提供 --archive")
        step("解包→重打包闭环", "SKIP", "未提供 --archive")

    # 5) 报告生成
    try:
        rep = report_generator.selftest_markdown(
            steps, {"generated_at": now_iso(), "project": str(proj.dir) if proj else "-",
                    "overall": "见下"})
        path = report_generator.write(
            cfgmod.dir_of(cfg, "reports", create=True) / f"round1-selftest-{args.stamp}.md", rep)
        step("生成报告", "PASS", str(path), evidence=str(path))
    except Exception as exc:  # noqa: BLE001
        step("生成报告", "FAIL", str(exc))

    # 6) 失败处理（故意给错误输入，验证不崩、留证据）
    try:
        blender = make_blender(cfg)
        bad = blender.run_script("analyze_glb.py",
                                 ["--glb", str(ROOT / "no_such.glb"),
                                  "--out", str(ROOT / "logs" / "never.json")],
                                 report_path=ROOT / "logs" / "never.json", timeout=120,
                                 label="selftest_bad_glb")
        handled = (not bad["ok"]) and bad["rc"] not in (0, None)
        step("失败处理：不存在的 GLB", "PASS" if handled else "FAIL",
             f"rc={bad['rc']} 未崩溃且返回非 0",
             detail={"rc": bad["rc"], "stdout_tail": bad["stdout"][-200:]})
    except Exception as exc:  # noqa: BLE001
        step("失败处理：不存在的 GLB", "FAIL", f"抛出未捕获异常: {exc}")

    try:
        wk = make_wk(cfg)
        r = wk.list_entries(ROOT / "no_such.archive")
        step("失败处理：不存在的归档", "SKIP", f"前置校验直接拒绝：{r}")
    except FileNotFoundError as exc:
        step("失败处理：不存在的归档", "PASS", f"前置校验拦截：{exc}")
    except Exception as exc:  # noqa: BLE001
        step("失败处理：不存在的归档", "FAIL", f"异常类型不符：{exc}")

    fails = [s for s in steps if s["result"] == "FAIL"]
    overall = "PASS" if not fails else "FAIL"
    meta = {"generated_at": now_iso(), "project": str(proj.dir) if proj else "-",
            "overall": overall}
    path = report_generator.write(
        cfgmod.dir_of(cfg, "reports", create=True) / f"round1-selftest-{args.stamp}.md",
        report_generator.selftest_markdown(steps, meta))
    if proj:
        proj.set_phase("selftest_done", selftest=overall)
        proj.state.set_status(overall.lower())
    out({"overall": overall, "report": str(path),
         "steps": [{"name": s["name"], "result": s["result"], "note": s["note"]} for s in steps]})
    return 0 if overall == "PASS" else 1


# ------------------------------------------------------------- reference
def _profile(body_id: str):
    from automation import body_profiles as bp
    return bp.load(body_id)


def prof_output_prev(prof) -> Path:
    """默认回归基线：同身形目录下的冻结版本（v1.1.0）。"""
    from automation import body_profiles as bp
    base = bp.output_dir(prof).parent
    frozen = base / "v1.1.0"
    return frozen if frozen.is_dir() else base


def cmd_ref(args) -> int:
    from automation import body_diff, body_model, body_morphology, body_profiles as bp
    from automation import body_reports
    body_id = (args.body or "ANGEL").upper()

    if args.action == "rig":
        from automation import rig_fetch
        out(rig_fetch.fetch(get_cfg(), force=args.force))
        return 0
    if args.action == "list":
        out({"profiles": bp.status_table()})
        return 0

    prof = _profile(body_id)
    if args.version:
        prof["asset_version"] = args.version
    paths = bp.output_paths(prof, override=args.outdir)

    if args.action == "morph":
        model = body_model.load(prof)
        morph = body_morphology.BodyMorphologyAnalyzer(model).analyze()
        paths["dir"].mkdir(parents=True, exist_ok=True)
        body_reports.write_json(morph, paths["morphology"])
        md = body_reports.morphology_report(morph, paths["dir"] / f"{body_id}_Body_Sections.md")
        out({"body_id": body_id, "morphology": str(paths["morphology"]), "report": str(md),
             "regions": {n: r["status"] for n, r in morph["regions"].items()}})
        return 0

    if args.action == "diff":
        from automation.body_model import sha256_file
        src = (args.source or "EBB").upper()
        fld = body_diff.field(src, body_id)
        ddir = paths["dir"]
        jpath = ddir / f"BodyDifference_{src}_to_{body_id}.json"
        mpath = ddir / f"BodyDifference_{src}_to_{body_id}.md"

        # 只读模式：只计算不落盘。测试与审计走这条路径，避免污染生产目录。
        if getattr(args, "no_write", False):
            out({"status": fld["status"], "reasons": fld.get("reasons"),
                 "dry_run": True, "json": None, "report": None,
                 "would_write": [str(jpath), str(mpath)]})
            return 0 if fld["status"] == "READY" else 3

        # 覆盖保护：已存在且 status=READY 的有效差异场，必须显式 --force 才允许覆盖。
        if jpath.is_file() and not args.force:
            try:
                prev = json.loads(jpath.read_text(encoding="utf-8"))
            except Exception:
                prev = {}
            if prev.get("status") == "READY":
                out({"status": "REFUSED", "existing": str(jpath),
                     "existing_status": prev.get("status"),
                     "existing_generated_at": prev.get("generated_at"),
                     "hint": "已存在有效差异场；确需覆盖请加 --force，或用 --outdir 输出到独立目录"})
                return 4

        ddir.mkdir(parents=True, exist_ok=True)
        jp = body_reports.write_json(fld, jpath)
        md = body_reports.diff_report(fld, mpath)
        jsha, msha = sha256_file(jp), sha256_file(md)
        ledger = body_reports.append_ledger(ddir / "diff_ledger.jsonl", {
            "ts": now_iso(), "argv": sys.argv[1:],
            "source": src, "target": body_id, "status": fld["status"],
            "inputs": fld.get("identity"),
            "json": {"path": str(jp), "sha256": jsha},
            "report": {"path": str(md), "sha256": msha},
        })
        out({"status": fld["status"], "reasons": fld.get("reasons"),
             "json": str(jp), "json_sha256": jsha, "report": str(md),
             "report_sha256": msha, "ledger": str(ledger)})
        return 0 if fld["status"] == "READY" else 3

    if args.action in ("build", "all"):
        r = reference_builder.build_for(
            prof, outdir=args.outdir,
            export_static=not args.no_static, export_skinned=not args.no_skinned)
        out({"body_id": body_id, "outdir": r["outdir"],
             "asset_version": prof.get("asset_version"),
             "outputs": {k: {"path": v.get("path"), "bytes": v.get("bytes"),
                             "sha256": (v.get("sha256") or "")[:16]}
                         for k, v in r["manifest"]["outputs"].items()},
             "gates": r["manifest"]["source_checks"]["quality_gates"]})

    if args.action in ("verify", "all"):
        cfg = get_cfg()
        blender = make_blender(cfg)
        base = paths["dir"]
        report = base / "blender_validation.json"
        r = blender.run_script("validate_skinned_glb.py",
                               ["--static", str(paths["static"]),
                                "--skinned", str(paths["skinned"]),
                                "--out", str(report),
                                "--blend", str(base / f"{body_id}_Body_Skinned.blend"),
                                "--skeleton", str(paths["skeleton"])],
                               report_path=report, label="validate_skinned_glb")
        payload = r.get("result") or {"status": "FAILED", "error": "Blender 未产出 JSON",
                                      "stdout_tail": (r.get("stdout") or "")[-600:]}
        out(payload)
        md = reference_report.report(base, body_id=body_id)
        print(f"报告：{md}", file=sys.stderr)
        return 0 if payload.get("status") == "OK" and payload.get("ok") else 1

    if args.action == "check":
        from automation import regression
        against = args.against or str(prof_output_prev(prof))
        r = regression.run(against, paths["dir"])
        outp = paths["dir"] / "regression.json"
        outp.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        out({"against": against, "verdict": r["verdict"], "report": str(outp)})
        return 0 if r["verdict"]["pass"] else 1

    if args.action == "report":
        md = reference_report.report(paths["dir"], body_id=body_id)
        out({"report": str(md)})
        return 0
    return 0


# --------------------------------------------------------------- status
def cmd_status(args) -> int:
    cfg = get_cfg()
    projects = project_manager.list_projects(cfgmod.dir_of(cfg, "projects"))
    reports = sorted(p.name for p in cfgmod.dir_of(cfg, "reports").glob("*")) if \
        cfgmod.dir_of(cfg, "reports").exists() else []
    out({"workshop_root": str(cfgmod.root(cfg)),
         "blender": cfgmod.get(cfg, "blender.version"),
         "wolvenkit": cfgmod.get(cfg, "wolvenkit.version"),
         "game_installed": cfgmod.get(cfg, "game.installed"),
         "detected_at": cfgmod.get(cfg, "detected_at"),
         "projects": projects, "reports": reports})
    return 0


def cmd_garment_audit(args) -> int:
    import numpy as np

    from audit.phase3.audit_garment_clearance import audit_clearance
    from audit.phase3.boots_pilot.verify_streams import audit_streams
    from audit.phase3.validate_v2 import sha256

    if args.out.exists():
        print(f"[输入错误] 报告路径已存在：{args.out}", file=sys.stderr)
        return 2
    try:
        mask = np.load(args.frozen_mask, allow_pickle=False) if args.frozen_mask else None
        if mask is not None and not isinstance(mask, np.ndarray):
            mask.close()
            raise ValueError("冻结区掩码必须为单个布尔型 .npy 数组")
        streams = audit_streams(args.source, args.candidate)
        report = audit_clearance(args.source, args.candidate, mask)
    except (ValueError, KeyError) as exc:
        print(f"[输入错误] {exc}", file=sys.stderr)
        return 2
    report["streams"] = streams
    geometry = report["geometry"]
    geometry_ok = (geometry["new_degenerate_indexed_triangles"] == 0
                   and geometry["reversed_indexed_triangles"] == 0)
    frozen_ok = None
    if mask is not None:
        region = report["frozen_region"]
        region.update(mask_sha256=sha256(args.frozen_mask), tolerance_mm=0.05)
        frozen_ok = region["max_mm"] <= region["tolerance_mm"]
    checks_ok = streams["pass"] and geometry_ok and frozen_ok is not False
    report["structural_checks"] = {
        "status": "PASS" if checks_ok else "FAIL",
        "topology": "PASS" if geometry_ok else "FAIL",
        "geometry_only_stream_change": "PASS" if streams["pass"] else "FAIL",
        "frozen_region": "NOT_CHECKED" if frozen_ok is None else "PASS" if frozen_ok else "FAIL",
        "visual_and_game_acceptance": "NOT_CHECKED",
    }
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    out({"report": str(args.out), **report["structural_checks"]})
    return 0 if checks_ok else 1


def cmd_boot_refit(args) -> int:
    from automation.boot_refit import run

    try:
        result = run(make_wk(get_cfg()), args.archive, args.mesh_entry, args.out)
    except (ValueError, KeyError, FileExistsError) as exc:
        print(f"[输入错误] {exc}", file=sys.stderr)
        return 2
    out({"archive": result["candidate_archive"], "report": str(args.out.resolve() / "report.json"),
         "structural_checks": result["structural_checks"],
         "visual_and_game_acceptance": result["visual_and_game_acceptance"]})
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Cyberpunk 2077 智能服装转换工作站")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("env", help="环境探测")
    p.set_defaults(func=cmd_env)

    p = sub.add_parser("project", help="工程管理")
    p.add_argument("action", choices=["new", "list", "show"])
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("--source")
    p.add_argument("--copy-source", action="store_true")
    p.set_defaults(func=cmd_project)

    p = sub.add_parser("inspect", help="资产检查")
    p.add_argument("kind", choices=["glb", "archive"])
    p.add_argument("target")
    p.add_argument("--project")
    p.add_argument("--extract", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("wk", help="WolvenKit 操作")
    p.add_argument("action", choices=["health", "roundtrip", "pack-check", "mutation-check", "export-probe"])
    p.add_argument("--archive")
    p.add_argument("--mesh")
    p.add_argument("--workdir")
    p.add_argument("--gamepath")
    p.set_defaults(func=cmd_wk)

    p = sub.add_parser("garment-audit", help="核对 EBBRB → ANGEL 位置转换后的网格")
    p.add_argument("source", type=Path, help="WolvenKit 导出的原网格 .mesh.json")
    p.add_argument("candidate", type=Path, help="从候选归档解包后导出的 .mesh.json")
    p.add_argument("--out", required=True, type=Path, help="新建 JSON 报告")
    p.add_argument("--frozen-mask", type=Path, help="按源顶点排序的冻结区布尔型 .npy 掩码")
    p.set_defaults(func=cmd_garment_audit)

    p = sub.add_parser("boot-refit", help="从原始归档生成 EBBRB → ANGEL 长靴单网格测试候选")
    p.add_argument("archive", type=Path, help="作者原始 EBBRB .archive")
    p.add_argument("--mesh-entry", required=True, help="已确认由靴子外观引用的解包网格路径或数字 .bin 条目")
    p.add_argument("--out", required=True, type=Path, help="新的输出目录")
    p.set_defaults(func=cmd_boot_refit)

    p = sub.add_parser("selftest", help="第一轮验收自检")
    p.add_argument("--glb")
    p.add_argument("--archive")
    p.add_argument("--stamp", default=now_iso().replace(":", "").replace("-", "")[:15])
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("ref", help="身形基准资产（参数化）")
    p.add_argument("action", choices=["list", "rig", "build", "verify", "all",
                                      "report", "morph", "diff", "check"])
    p.add_argument("--body", default="ANGEL", help="身形 ID（config/bodies/<ID>.json）")
    p.add_argument("--source", help="diff 的源身形（默认 EBB）")
    p.add_argument("--against", help="check 的基线目录（默认 references/bodies/<ID>/v1.1.0）")
    p.add_argument("--version", help="覆盖产物目录用的资产版本（默认取档案）")
    p.add_argument("--outdir")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-write", dest="no_write", action="store_true",
                   help="只读模式：diff 只计算不落盘（测试/审计用）")
    p.add_argument("--no-static", action="store_true", help="不导出静态 GLB")
    p.add_argument("--no-skinned", action="store_true", help="不导出蒙皮 GLB")
    p.set_defaults(func=cmd_ref)

    p = sub.add_parser("status", help="工作站状态")
    p.set_defaults(func=cmd_status)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"[输入错误] {exc}", file=sys.stderr)
        return 2
    except NotADirectoryError as exc:
        print(f"[输入错误] {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"[执行失败] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
