"""报告生成：JSON → Markdown。数字一律来自传入的结构化结果，不手写。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _v(x, empty: str = "未检测") -> str:
    return empty if x in (None, "", [], {}) else str(x)


def _yes(b) -> str:
    return "是" if b else "否"


def write(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------- 环境报告
def env_markdown(p: dict[str, Any]) -> str:
    os_ = p["os"]
    py = p["python"]
    bl = p["blender"]
    wk = p["wolvenkit"]
    gm = p["game"]
    perm = p["permissions"]

    L = ["# 环境检测报告", "",
         f"- 生成时间：{p['generated_at']}",
         f"- 工作站根目录：`{p['workshop_root']}`",
         "- 生成方式：`automation/env_probe.py` 实际执行探测，非人工填写", ""]

    L += ["## 1. 操作系统", "",
          "| 项 | 值 |", "|---|---|",
          f"| 系统 | {os_['system']} |",
          f"| 版本 | {os_['release']} (build {os_['version']}) |",
          f"| 架构 | {os_['machine']} |",
          f"| 主机名 | {os_['node']} |", ""]

    L += ["## 2. Python", "",
          "| 项 | 值 |", "|---|---|",
          f"| 版本 | {py['version']} |",
          f"| 实现 | {py['impl']} |",
          f"| 位数 | {py['bitness']} |",
          f"| 可执行文件 | `{py['executable']}` |"]
    exe_dir = Path(py["executable"]).parent.name
    if exe_dir and exe_dir not in py["version"]:
        L += [f"| 备注 | 安装目录名 `{exe_dir}` 与运行时版本 {py['version']} 不一致"
              "（实测值，按运行时为准） |"]
    L.append("")

    L += ["## 3. Blender", "",
          "| 项 | 值 |", "|---|---|",
          f"| 选中可执行文件 | `{_v(bl['exe'])}` |",
          f"| 版本 | {_v(bl['version'])} |",
          f"| 后台启动测试 | {_yes(bl['background_ok'])} |",
          f"| Blender Python API | bpy {_v(bl.get('bpy_version'))} / Python {_v(bl.get('python_version'))} |",
          f"| CP77 glTF 插件 | {_v(bl.get('cp77_addon'))} |",
          f"| 探测错误 | {_v(bl.get('error'), '无')} |", ""]
    if bl.get("candidates"):
        L += ["候选安装（按修改时间倒序）：", ""]
        L += [f"- `{c}`" for c in bl["candidates"]]
        L.append("")

    L += ["## 4. WolvenKit", "",
          "| 项 | 值 |", "|---|---|",
          f"| 选中 CLI | `{_v(wk['cli'])}` |",
          f"| 版本 | {_v(wk['version'])} |",
          f"| 子命令 | {', '.join(wk.get('subcommands') or []) or '未检测'} |",
          f"| convert 子命令 | {', '.join(wk.get('convert_subcommands') or []) or '未检测'} |",
          f"| hash 自检 | {wk.get('hash_selftest', {}).get('ok')} |",
          f"| 探测错误 | {_v(wk.get('error'), '无')} |", ""]
    if wk.get("candidates"):
        L += ["候选 CLI：", "", "| 路径 | 版本 |", "|---|---|"]
        L += [f"| `{c['path']}` | {_v(c['version'])} |" for c in wk["candidates"]]
        L.append("")

    L += ["## 5. 游戏本体", "",
          "| 项 | 值 |", "|---|---|",
          f"| 目录 | `{_v(gm.get('dir'))}` |",
          f"| 可执行文件 | `{_v(gm.get('exe'))}` |",
          f"| 判定已安装 | {_yes(gm.get('installed'))} |",
          f"| 说明 | {_v(gm.get('note'), '无')} |", ""]
    if gm.get("checked"):
        L += ["检查过的库：", "", "| 目录 | exe | appmanifest | 文件数 |", "|---|---|---|---|"]
        for c in gm["checked"]:
            L += [f"| `{c['dir']}` | {_yes(c['exe_exists'])} | {_yes(c['appmanifest'])} | "
                  f"{c['file_count']} |"]
        L.append("")

    L += ["## 6. 工作目录权限", "",
          f"磁盘可用：{perm['disk'].get('free_gb')} GB / {perm['disk'].get('total_gb')} GB", "",
          "| 目录 | 可写 | 路径 |", "|---|---|---|"]
    for name, d in perm["dirs"].items():
        L += [f"| {name} | {_yes(d.get('writable'))} | `{d['path']}` |"]
    L.append("")

    L += ["## 7. 由此得出的结论", ""]
    ok_blender = bl.get("background_ok")
    ok_wk = bool(wk.get("cli") and wk.get("version"))
    L += [f"- Blender 后台可用：{_yes(ok_blender)}"
          + ("" if ok_blender else " → 不能做 GLB 分析/几何处理"),
          f"- WolvenKit CLI 可用：{_yes(ok_wk)}"
          + ("" if ok_wk else " → 不能做归档解包/打包"),
          f"- 游戏本体可用：{_yes(gm.get('installed'))}"
          + ("" if gm.get("installed") else " → 无法安装验证、无法游戏内测试"),
          "- 未检测项一律未填写，禁止后续按默认值推断。", ""]
    return "\n".join(L)


# --------------------------------------------------------------- 检查报告
def inspect_markdown(glb_analysis: dict[str, Any] | None, validation: dict[str, Any],
                     archive: dict[str, Any] | None, title: str = "资产检查报告") -> str:
    L = [f"# {title}", ""]
    if glb_analysis:
        s = glb_analysis.get("summary") or {}
        L += [f"- GLB：`{glb_analysis.get('glb')}`",
              f"- 文件大小：{glb_analysis.get('glb_bytes')} 字节",
              f"- Blender：{glb_analysis.get('blender_version')}",
              f"- 状态：{glb_analysis.get('status')}", "",
              "## 汇总", "",
              "| 指标 | 值 |", "|---|---|",
              f"| 对象数 | {s.get('object_count')} |",
              f"| Mesh 数 | {s.get('mesh_count')} |",
              f"| 顶点总数 | {s.get('total_vertices')} |",
              f"| 三角面总数 | {s.get('total_triangles')} |",
              f"| 材质数 | {s.get('material_count')} |",
              f"| 贴图数 | {s.get('image_count')} |",
              f"| Armature 数 | {s.get('armature_count')} |",
              f"| 骨骼数 | {s.get('bone_count')} |",
              f"| 有 UV | {_yes(s.get('has_uv'))} |",
              f"| 有顶点组 | {_yes(s.get('has_vertex_groups'))} |", ""]
        meshes = glb_analysis.get("meshes") or []
        if meshes:
            L += ["## Mesh 明细", "",
                  "| 对象 | 顶点 | 面 | 三角面 | UV | 材质 | 顶点组 | 尺寸(m) |",
                  "|---|---|---|---|---|---|---|---|"]
            for m in meshes:
                dims = m.get("dimensions") or [0, 0, 0]
                L += [f"| `{m['object']}` | {m['vertices']} | {m['polygons']} | "
                      f"{m['triangles']} | {len(m['uv_layers'])} | "
                      f"{len(m.get('materials') or [])} | {m.get('vertex_group_count')} | "
                      f"{dims[0]:.3f}×{dims[1]:.3f}×{dims[2]:.3f} |"]
            L.append("")
        arms = glb_analysis.get("armatures") or []
        if arms:
            L += ["## Armature", ""]
            for a in arms:
                L += [f"- `{a['object']}`：{a['bone_count']} 骨，根骨 "
                      f"{', '.join(a.get('root_bones') or []) or '未知'}"]
            L.append("")
        mats = glb_analysis.get("materials") or []
        if mats:
            L += ["## 材质", ""]
            for m in mats[:20]:
                L += [f"- `{m['name']}`：节点 {len(m.get('nodes') or [])}，"
                      f"贴图 {', '.join(m.get('images') or []) or '无'}"]
            L.append("")

    if archive:
        L += ["## 归档", "",
              f"- 路径：`{archive.get('archive')}`",
              f"- 条目数：{archive.get('entry_count')}",
              f"- 扩展名分布：{archive.get('extension_stats')}",
              f"- 识别到的资源类型：{archive.get('resource_types') or '未解包'}", ""]
        ext = archive.get("extracted")
        if ext:
            L += [f"- 解包：{'成功' if ext.get('ok') else '失败'}，"
                  f"{ext.get('files')} 个文件 / {ext.get('bytes')} 字节", ""]

    L += ["## 校验结果", "",
          f"- 总体：{'通过' if validation.get('ok') else '未通过'}", ""]
    fs = validation.get("findings") or []
    if fs:
        L += ["| 级别 | 代码 | 说明 |", "|---|---|---|"]
        L += [f"| {f['level']} | `{f['code']}` | {f['message']} |" for f in fs]
        L.append("")
    else:
        L += ["- 无发现项", ""]
    return "\n".join(L)


# --------------------------------------------------------------- 自检报告
def selftest_markdown(steps: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    L = ["# 第一轮验收报告", "",
         f"- 时间：{meta.get('generated_at')}",
         f"- 项目：`{meta.get('project')}`",
         f"- 总体：{meta.get('overall')}", "",
         "| # | 检查项 | 结果 | 耗时(s) | 证据 |", "|---|---|---|---|---|"]
    for i, s in enumerate(steps, 1):
        L += [f"| {i} | {s['name']} | {s['result']} | {s.get('duration_sec') or '-'} | "
              f"{s.get('evidence') or '-'} |"]
    L.append("")
    L += ["## 明细", ""]
    for s in steps:
        L += [f"### {s['name']}", "", f"- 结果：{s['result']}", f"- 说明：{s.get('note', '-')}"]
        if s.get("detail"):
            L += ["```json", str(s["detail"])[:2000], "```"]
        L.append("")
    return "\n".join(L)
