"""身形相关 Markdown 报告：截面报告、差异场报告。

只做排版，不做测量；所有数字都来自 `body_morphology` / `body_diff` 的 JSON。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATUS_ICON = {"HIGH": "✅", "MEDIUM": "⚠", "LOW": "❌", "N/A": "—"}


def morphology_report(morph: dict[str, Any], path: Path) -> Path:
    dims = morph["overall"]["dimensions"]
    geo = morph["overall"]["geometry"]
    lm = morph["overall"]["landmarks"]
    body = morph["body_id"]
    L: list[str] = [f"# {body} 身体截面与形态报告", "",
                    f"- 分析器：`{morph['analyzer']}`（schema `{morph['schema']}`）",
                    f"- 生成时间：{morph['generated_at']}",
                    f"- 坐标系：{morph['coordinate_system']['space']}，"
                    f"{morph['coordinate_system']['up_axis']}-up，米制",
                    f"- 标准化高度：`{morph['normalization']['height_norm_formula']}`", ""]

    L += ["## 1. 整体尺寸", "", "| 项 | 值 |", "|---|---|",
          f"| 身高 | {dims['height_m']} m |",
          f"| 最宽（X） | {dims['width_m']} m |",
          f"| 最厚（Y） | {dims['depth_m']} m |",
          f"| 包围盒 | {dims['bbox_min']} → {dims['bbox_max']} |",
          f"| 表面积 | {geo['surface_area_m2']} m² |",
          f"| 体积（绝对） | {geo['volume_abs_m3']} m³ |",
          f"| 闭合（watertight） | {geo['watertight']}（边界边 {geo['boundary_edges']}） |",
          f"| 顶点 / 三角 | {morph['overall']['vertices']:,} / {morph['overall']['triangles']:,} |",
          ""]

    L += ["## 2. 地标（来自骨骼，非估计）", "", "| 地标 | 骨骼 | z (m) | 标准化高度 |",
          "|---|---|---|---|"]
    for key, info in lm.items():
        if key.startswith("_"):
            continue
        L.append(f"| {key} | `{info['bone']}` | {info['z']} | {info['height_norm']} |")
    L += ["", f"> z_min={lm['_reference']['z_min']}，z_max={lm['_reference']['z_max']}，"
          f"身高 {lm['_reference']['height_m']} m", ""]

    L += ["## 3. 区域测量", "",
          "| 区域 | 标准化高度带 | 带内宽 (m) | 带内厚 (m) | 截面面积 (m²) | 面积方法 | 环路 | 可靠性 |",
          "|---|---|---|---|---|---|---|---|"]
    for name in morph["region_order"]:
        reg = morph["regions"][name]
        sil = reg.get("silhouette") or {}
        sec = reg["section"]
        area = sec.get("area_m2_mean")
        icon = STATUS_ICON.get(reg["status"], "")
        L.append(f"| {name}（{reg['label']}） | {reg['band']['height_norm']:.3f}"
                 f"（{reg['band']['z_lo']:.3f}–{reg['band']['z_hi']:.3f}） | "
                 f"{sil.get('width_m', 0):.4f} | {sil.get('thickness_m', 0):.4f} | "
                 f"{'—' if area is None else f'{area:.5f}'} | {sec.get('area_method')} | "
                 f"{sec.get('loops_max')} | {icon} {reg['status']} |")
    L += ["", "**可靠性判据**：截面全部闭合且平移 0.5mm 面积变化 <5% → HIGH；"
          "出现开放折线 / 多环路 → LOW 或 MEDIUM（该高度表面接近水平，或网格在此断开）。", ""]

    problems = [(n, r) for n, r in morph["regions"].items() if r["reliability"]["reasons"]]
    if problems:
        L += ["### 需要复核的区域", ""]
        for name, reg in problems:
            L.append(f"- **{name}**（{reg['status']}）：" + "；".join(reg["reliability"]["reasons"]))
        L.append("")

    if not all(r["applicable"] for r in morph["regions"].values()):
        na = [n for n, r in morph["regions"].items() if not r["applicable"]]
        L += [f"### 不适用的区域：{', '.join(na)}", "",
              "本文档所用网格不包含对应部位（如手臂是独立网格 `a0_000_pwa_base_hq__l/r`），"
              "这些区域不会给出数值，也不参与差异对比。", ""]

    f = morph["silhouette"]["front"]
    s = morph["silhouette"]["side"]
    L += ["## 4. 轮廓（按高度分带）", "",
          f"- 正面：{f['bands']} 带，最大宽度 {f['max_extent_m']} m"
          f"（z={f['max_extent_at_z']}，标准化高度 {f['max_extent_height_norm']}）",
          f"- 侧面：{s['bands']} 带，最大厚度 {s['max_extent_m']} m"
          f"（z={s['max_extent_at_z']}，标准化高度 {s['max_extent_height_norm']}）", "",
          "抽样（每 10% 身高）：", "",
          "| 标准化高度 | 正面宽 (m) | 侧面厚 (m) |", "|---|---|---|"]
    prof_f = {round(r["height_norm"], 2): r for r in f["profile"]}
    prof_s = {round(r["height_norm"], 2): r for r in s["profile"]}
    for t in [i / 10 for i in range(11)]:
        k = min(prof_f, key=lambda x: abs(x - t)) if prof_f else None
        if k is None:
            continue
        L.append(f"| {k:.2f} | {prof_f[k]['extent_m']:.4f} | "
                 f"{prof_s.get(k, {}).get('extent_m', 0):.4f} |")
    L += ["", "> 正面宽 = 该高度带内顶点 X 跨度；侧面厚 = Y 跨度。"
          "含手臂的网格在这些高度会明显变宽。", ""]

    L += ["## 5. 截面轮廓数据", "",
          f"每个区域中心高度的截面环路已存进 `{body}_Morphology.json` 的 "
          "`sections_detail.<region>.loop_data[].contour`（最多 64 点/环，XY 平面，米）。",
          "可直接画图核对形状，不需要重新解码网格。", ""]

    L += ["## 6. 复现", "", "```bash",
          f'cd "{Path(__file__).resolve().parent.parent}"',
          f"python automation/main.py ref morph --body {body}",
          "```", ""]
    atomic_write_text("\n".join(L), path)
    return path


def diff_report(field: dict[str, Any], path: Path) -> Path:
    src, dst = field["source_body"], field["target_body"]
    L: list[str] = [f"# {src} → {dst} 身形差异场", "",
                    f"- 生成器：`{field['generator']}`（schema `{field['schema']}`）",
                    f"- 生成时间：{field['generated_at']}",
                    f"- 状态：**{field['status']}**", ""]

    if field["status"] != "READY":
        L += ["## 未就绪原因", ""]
        for r in field.get("reasons") or []:
            L.append(f"- {r}")
        L += ["", "差异场处于 PENDING：**这不代表两个身形没有差异**，而是缺少计算所必需的数据。",
              "拿到缺失身形后执行 `python automation/main.py ref diff --source "
              f"{src} --target {dst}` 即可生成完整差异场。", ""]
        atomic_write_text("\n".join(L), path)
        return path

    m = field["measurements"]
    s = field["surface"]
    conf = field["confidence"]
    L += ["## 1. 身高", "", "| 项 | 源 | 目标 | 差异 | 比例 |", "|---|---|---|---|---|",
          f"| 身高 (m) | {m['height']['source_m']} | {m['height']['target_m']} | "
          f"{m['height']['delta_m']:+.4f} | {m['height']['delta_ratio']:+.2%} |", ""]

    L += ["## 2. 区域差异", "",
          "| 源区域 → 目标区域 | 带宽 Δ (m) | 带厚 Δ (m) | 截面面积 Δ (m²) | 可比 |",
          "|---|---|---|---|---|"]
    for name, r in m["regions"].items():
        w, t, a = r["width_m"]["delta"], r["thickness_m"]["delta"], r["area_m2"]["delta"]
        fmt = lambda v: "—" if v is None else f"{v:+.4f}"
        L.append(f"| {name} → {r['target_region']}{'' if r['same_name'] else '（改名）'} | "
                 f"{fmt(w)} | {fmt(t)} | {'—' if a is None else f'{a:+.5f}'} | "
                 f"{'✓' if r['comparable'] else '✗ ' + str(r['not_comparable_reason'] or '')} |")
    L += ["", "> 带宽/带厚取带内顶点包围差值；面积为水平截面差。**这些都是标量测量，"
          "不是逐顶点三维位移。**", ""]

    L += ["## 3. 表面对应（源顶点 → 目标表面最近点）", "",
          "| 指标 | 值 |", "|---|---|",
          f"| 参与顶点 | {s['correspondence_summary']['vertices']:,} |",
          f"| 覆盖率 | {s['correspondence_summary']['coverage']:.2%} |",
          f"| 距离 中位 / p95 / 最大 | {s['distance_m']['median']} / {s['distance_m']['p95']} / "
          f"{s['distance_m']['max']} m |",
          f"| 距离容差 | {s['correspondence_summary']['distance_tol_m']} m |",
          f"| 法向夹角 均值 / p95 | {s['correspondence_summary']['angle_deg']['mean']} / "
          f"{s['correspondence_summary']['angle_deg']['p95']} ° |",
          f"| 有符号法向位移 中位 / p05 / p95 | {s['signed_normal_delta_m']['median']} / "
          f"{s['signed_normal_delta_m']['p05']} / {s['signed_normal_delta_m']['p95']} m |",
          f"| 状态 OK / NEEDS_REVIEW | {s['correspondence_summary']['status']['OK']:,} / "
          f"{s['correspondence_summary']['status']['NEEDS_REVIEW']:,} |", ""]

    L += ["## 4. 置信度", "",
          f"- 等级：**{conf['level']}**（{conf['criteria']}）",
          f"- OK 比例 {conf['ok_ratio']:.2%}，NEEDS_REVIEW {conf['needs_review']:,}，"
          f"距离 p95 {conf['distance_p95_m']} m", ""]

    L += ["## 5. 必须区分的两件事", "",
          "1. **截面差异**（第 2 节）：标量、按高度切片，回答“这个高度粗了多少”。",
          "2. **表面位移场**（第 3 节）：逐顶点到目标表面的距离与方向，"
          "回答“这个点要往哪挪多少”。",
          "",
          "两者不能互相替代：截面差 1cm 不代表每个顶点都挪 1cm，"
          "也不能把截面数据积分回三维位移。", ""]

    L += ["## 6. 区域对应关系", "", "| 源区域 | 目标区域 | 高度差 | 同名 |", "|---|---|---|---|"]
    for name, r in m["region_map"].items():
        L.append(f"| {name} | {r['target_region']} | {r['delta_height_norm']:+.4f} | "
                 f"{'是' if r['same_name'] else '否'} |")
    first = next(iter(m["region_map"].values()), None)
    if first:
        L += ["", f"> {first['method']}", ""]

    atomic_write_text("\n".join(L), path)
    return path


def atomic_write_text(text: str, path: Path) -> Path:
    """原子写入：先写同目录临时文件，再 os.replace 覆盖。

    目的：任何中途失败都不会留下半截文件；同时避免其他进程读到写了一半的 JSON。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def write_json(obj: Any, path: Path) -> Path:
    return atomic_write_text(json.dumps(obj, ensure_ascii=False, indent=2), path)


def append_ledger(path: Path, record: dict[str, Any]) -> Path:
    """追加式生成台账（JSONL）。只追加，不覆盖，便于事后审计谁写了什么。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
