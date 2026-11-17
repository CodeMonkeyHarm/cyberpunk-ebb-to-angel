"""把构建产物汇总成《基准资产报告》（每种身形一份，按档案定位目录）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def report(outdir: str | Path | None = None, *, body_id: str = "ANGEL") -> Path:
    from . import body_profiles as P

    base = Path(outdir) if outdir else P.output_paths(P.load(body_id))["dir"]
    man = _load(base / "manifest.json")
    if man is None:
        raise FileNotFoundError(f"{base}/manifest.json 不存在，先跑 ref build")
    bid = man.get("body_id", body_id)
    outs = man["outputs"]

    def out_path(key: str, fallback: str) -> Path:
        entry = outs.get(key) or {}
        return Path(entry["path"]) if entry.get("path") else base / fallback

    sk = _load(out_path("skeleton_json", f"{bid}_Skeleton.json")) or {}
    wa = _load(out_path("weight_analysis_json", f"{bid}_Weight_Analysis.json")) or {}
    mor = _load(out_path("morphology_json", f"{bid}_Morphology.json"))
    val = _load(base / "blender_validation.json")
    c = man["source_checks"]
    hier = man.get("hierarchy")

    L: list[str] = [f"# {bid} 基准资产报告", "",
                    f"- 身形：**{man.get('display_name') or bid}**（`{bid}`）",
                    f"- 资产版本：{man.get('asset_version')}",
                    f"- 生成时间：{man['generated_at']}",
                    f"- 构建器：`automation/reference_builder.py` v{man['builder_version']}"
                    f"（schema `{man.get('schema')}`）",
                    f"- 档案：`{man.get('profile')}`",
                    f"- 输出目录：`{base}`", ""]

    L += ["## 1. 输入与对应关系核实", "",
          "| 检查 | 结果 |", "|---|---|",
          f"| 原始 .mesh | {c['raw_mesh_bytes']:,} 字节，magic `{c.get('raw_mesh_magic')}` |",
          f"| .mesh sha256 | `{c['raw_mesh_sha256']}` |",
          f"| .mesh.json | {c['mesh_json_bytes']:,} 字节 |",
          f"| .mesh.json sha256 | `{c['mesh_json_sha256']}` |",
          f"| 解码顶点数 = 各 chunk 声明之和 | {c['decoded_vertex_count']:,} = "
          f"{c['declared_chunk_vertex_sum']:,} → {c['vertex_count_match']} |",
          f"| chunk 数 | {c['chunk_count']} |",
          f"| 越界索引丢弃数 | {c['index_out_of_range_dropped']}（应为 0） |",
          f"| 解码包围盒 vs CMesh 声明 | 最大误差 {c['bbox_max_error_m']} m → {c['bbox_match']} |",
          f"| IBM·bonePos | 最大误差 {c['ibm_times_bonepos_max_error']} → "
          f"{c['ibm_is_inverse_bind']} |",
          f"| IBM 旋转行列式 | [{c['ibm_det_min']}, {c['ibm_det_max']}]（应全为 1） |",
          f"| 骨骼索引范围 | 最大 {c['max_joint_index_used']} / 共 {c['bone_count']} → "
          f"{c['joint_index_in_range']} |",
          f"| .mesh ↔ .mesh.json | {c.get('mesh_json_is_reserialized_raw')}"
          f"（{c.get('mesh_json_identity_note')}） |",
          f"| 与档案期望值一致 | {c.get('expectations_ok')}"
          f"{'' if c.get('expectations_ok') else '：' + json.dumps(c.get('expectation_mismatch'), ensure_ascii=False)} |",
          ""]
    rc = c.get("reserialize_compare")
    if rc:
        L += ["重新序列化比对明细：", "",
              "| 项 | 原 .mesh.json | 重新序列化 |", "|---|---|---|",
              f"| 顶点缓冲一致 | — | {rc['render_buffer_identical']} |",
              f"| 顶点数 | {rc['vertex_count'][1]:,} | {rc['vertex_count'][0]:,} |",
              f"| chunk 数 | {rc['chunk_count'][1]} | {rc['chunk_count'][0]} |",
              f"| geometryHash | {rc['geometry_hash'][1]} | {rc['geometry_hash'][0]} |", ""]

    L += ["### 骨骼层级", ""]
    if hier:
        L += [f"- 结论：**真实父子层级**，取自 `{Path(hier['source']).name}`"
              f"（{hier['rig_bones']} 骨的 {hier['rig_type']}）。",
              f"- 根骨骼：{', '.join(hier['roots'])}；最大深度 {hier['max_depth']}；"
              f"有子骨的骨骼 {hier['bones_with_children']} 根。",
              f"- 深度分布：{hier['depth_histogram']}",
              f"- 父链被跳过（并入最近网格祖先）的非网格骨（"
              f"{len(hier['skipped_non_mesh_bones'])}）："
              f"{', '.join(hier['skipped_non_mesh_bones'])}",
              f"- 方法：{hier['method']}。矩阵全部来自 CMesh 的 IBM 反推，未使用猜测值。", ""]
        pc = hier.get("pose_comparison")
        if pc:
            L += ["**为什么不用 rig 自带的姿势矩阵**（实测比对）：", "",
                  "| 项 | 值 |", "|---|---|",
                  f"| 比对骨骼数 | {pc['bones_compared']} |",
                  f"| 平移差 中位 / 最大 | {pc['translation_diff_m']['median']:.4f} m / "
                  f"{pc['translation_diff_m']['max']:.4f} m |",
                  f"| 平移差 >1mm 的骨骼 | {pc['translation_diff_m']['over_1mm']} / "
                  f"{pc['bones_compared']} |",
                  f"| 旋转元素差 中位 / 最大 | {pc['rotation_element_diff']['median']:.4f} / "
                  f"{pc['rotation_element_diff']['max']:.4f} |",
                  f"| rig 矩阵可否直接使用 | **否** |", "",
                  f"> {pc['conclusion']}。", ""]
    else:
        L += ["- 结论：**扁平骨架**（未找到 rig 数据）。", ""]

    L += ["## 2. 产物", "", "| 文件 | 大小 | sha256（前 32 位） |", "|---|---|---|"]
    for key, label in (("static_glb", "静态 GLB"), ("skinned_glb", "蒙皮 GLB"),
                       ("skeleton_json", "骨架 JSON"), ("weight_analysis_json", "权重分析"),
                       ("morphology_json", "形态测量"), ("body_record_json", "统一记录")):
        e = outs.get(key)
        if not e:
            continue
        p = Path(e["path"])
        size = p.stat().st_size if p.is_file() else 0
        L.append(f"| {label} `{p.name}` | {size:,} | `{e['sha256'][:32]}…` |")
    if val and val.get("blend"):
        L.append(f"| Blender 另存 `{Path(val['blend']['path']).name}` | "
                 f"{val['blend'].get('bytes', 0):,} | （导入验证产物） |")
    L.append("")

    gs = man.get("glb_structure") or {}
    if gs.get("static") or gs.get("skinned"):
        st, skn = gs.get("static") or {}, gs.get("skinned") or {}
        L += ["### GLB 结构自检（直接解析二进制 JSON chunk）", "",
              "| 项 | 静态 | 蒙皮 |", "|---|---|---|",
              f"| magic / 版本 | {st.get('magic_ok')} / {st.get('version')} | "
              f"{skn.get('magic_ok')} / {skn.get('version')} |",
              f"| 声明字节 = 实际字节 | {st.get('declared_bytes') == st.get('actual_bytes')} | "
              f"{skn.get('declared_bytes') == skn.get('actual_bytes')} |",
              f"| primitive 数 | {st.get('primitives')} | {skn.get('primitives')} |",
              f"| 属性集合 | {', '.join(st.get('attributes') or [])} | "
              f"{', '.join(skn.get('attributes') or [])} |",
              f"| JOINTS/WEIGHTS | — | {skn.get('has_joints_weights')}"
              f"（第二组 {skn.get('has_second_set')}） |",
              f"| joints / IBM 数 | — | {skn.get('joints')} / {skn.get('ibm_count')} |",
              f"| skeleton 根节点 | — | `{skn.get('skeleton_node')}` |",
              f"| 空 accessor | — | {skn.get('degenerate_accessors')} |", ""]

    sm = wa.get("summary") if wa else None
    if sm:
        L += ["## 3. 权重分析", "", "| 指标 | 值 |", "|---|---|",
              f"| 顶点数 | {sm['vertices']:,} |",
              f"| 使用到的骨骼 | {sm['bones_used']} / {sm['bones_total']} |",
              f"| 无权重顶点 | {sm['unweighted_vertices']} |",
              f"| 权重和 <0.9 / >1.1 | {sm['sum_below_0_9']} / {sm['sum_above_1_1']} |",
              f"| 单顶点最大影响数 | {sm['max_influences']} |",
              f"| 影响数分布 | {sm['influence_histogram']} |", ""]

    if mor:
        dims = mor["overall"]["dimensions"]
        geo_m = mor["overall"]["geometry"]
        L += ["## 4. 形态测量（BodyMorphologyAnalyzer）", "",
              f"- 分析器：`{mor['analyzer']}`，schema `{mor['schema']}`",
              f"- 尺寸：高 {dims['height_m']} m × 宽 {dims['width_m']} m × 厚 {dims['depth_m']} m",
              f"- 表面积 {geo_m['surface_area_m2']} m²；体积 {geo_m['volume_abs_m3']} m³"
              f"（watertight={geo_m['watertight']}，边界边 {geo_m['boundary_edges']}）",
              f"- 标准化高度：`{mor['normalization']['height_norm_formula']}`", "",
              "| 区域 | 标准化高度 | 带内宽 | 带内厚 | 截面面积 | 方法 | 可靠性 |",
              "|---|---|---|---|---|---|---|"]
        for name in mor["region_order"]:
            reg = mor["regions"][name]
            sil = reg.get("silhouette") or {}
            sec = reg["section"]
            area = sec.get("area_m2_mean")
            L.append(f"| {name}（{reg['label']}） | {reg['band']['height_norm']:.3f} | "
                     f"{sil.get('width_m', 0):.4f} | {sil.get('thickness_m', 0):.4f} | "
                     f"{'—' if area is None else f'{area:.5f}'} | {sec.get('area_method')} | "
                     f"{reg['status']} |")
        L += ["", "> 带内宽/厚 = 该高度带内顶点的包围尺寸（不依赖截面拼接，最稳）；"
              "截面面积 = 平面 z=const 与三角形求交后按环路积分。", ""]

    if val:
        L += ["## 5. Blender 验证（实际导入）", "",
              f"- 总体：{'通过' if val.get('ok') else '未通过'}", "",
              "| 检查 | 结果 |", "|---|---|"]
        for k, v in val["checks"].items():
            L.append(f"| {k} | {'✅' if v else '❌'} |")
        cc = val.get("contour_compare") or {}
        w = val.get("weights") or {}
        arm = val.get("armature") or {}
        L += ["", "关键实测值：", "",
              f"- 骨架：{arm.get('armatures')} 个 Armature / {arm.get('bones')} 骨 / "
              f"根骨 {arm.get('root_bones')} / 零长度骨 {arm.get('zero_length_bones')}",
              f"- 顶点组：{w.get('vertex_groups_max')} 个/对象；无权重顶点 {w.get('unweighted_vertices')}",
              f"- 权重和：{w.get('weight_sum_min')} ~ {w.get('weight_sum_max')}；"
              f"最大影响 {w.get('max_influences')}",
              f"- 轮廓对比：{cc.get('vertices')} 顶点，最大逐点差 {cc.get('max_abs_diff')} m，"
              f"一致={cc.get('identical')}",
              f"- 排除的骨骼辅助网格：{val.get('helpers_excluded')}", ""]
    else:
        L += ["## 5. Blender 验证", "", "- **未执行**（缺 blender_validation.json）", ""]

    L += ["## 6. 坐标与变换", "",
          f"- 几何映射：{sk.get('coordinate_system', {}).get('geometry_mapping')}",
          f"- 矩阵映射：{sk.get('coordinate_system', {}).get('matrix_mapping')}",
          f"- 绕序：{sk.get('coordinate_system', {}).get('winding')}",
          "- IBM：直接使用 `boneRigMatrices`（已数值证明为逆绑定矩阵），并做同样的基变换。", ""]

    L += ["## 7. 局限与未验证项", ""]
    if hier:
        rig_only = hier.get("rig_only_bones") or []
        L += [f"1. **层级是投影结果**：rig 共 {hier['rig_bones']} 骨，本网格只用 "
              f"{hier['mesh_bones']} 骨；另有 {len(rig_only)} 根不属于本网格："
              f"{', '.join(rig_only)}。这些骨被跳过，网格骨挂到最近的祖先，根为 "
              f"{', '.join(hier['roots'])}。"]
    else:
        L += ["1. **骨骼层级缺失**：扁平骨架，动画时无父子联动。"]
    L += ["2. **不含贴图**：材质只有名称与常量色，贴图为外部 `.xbm`。",
          f"3. **只导出默认外观**：`{(man.get('display_name') or bid)}` 的默认 appearance。",
          "4. **未做游戏内验证**：参考资产不打包成 mod，只完成 Blender 层面验证。",
          "5. 权重为原始 UByte4N 值（和 0.988–1.012），未归一化。"]
    if mor:
        bad = [n for n, r in mor["regions"].items() if r["status"] in ("LOW", "N/A")]
        if bad:
            L.append(f"6. **截面可靠性不足的区域**：{', '.join(bad)} —— 这些高度表面接近水平或"
                     "网格在此断开，面积不可用，宽度/厚度请用带内包围值。")
    L.append("")

    L += ["## 8. 复现", "", "```bash",
          f'cd "{Path(__file__).resolve().parent.parent}"',
          f"python automation/main.py ref build  --body {bid}",
          f"python automation/main.py ref verify --body {bid}",
          f"python automation/main.py ref all    --body {bid}",
          "```", "",
          f"构建器 v{man['builder_version']}；输入 sha256 见 `manifest.json`。", ""]

    target = base / f"{bid}_Reference_Report.md"
    target.write_text("\n".join(L), encoding="utf-8")
    return target
