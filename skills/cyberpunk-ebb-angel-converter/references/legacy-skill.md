---
name: cyberpunk-ebb-angel-converter
description: Convert Cyberpunk 2077 clothing mods authored for the EBB body to the ANGEL body (Hyst Angel BodyMod), reusing a verified local pipeline (WolvenKit serialize → CMesh decode → Blender wrap refit → CMesh write-back → archive repack). Use when asked to port, refit or convert EBB footwear/garments to ANGEL, to diagnose "item equips but no model / all-black textures / thigh clipping / ankle creases" in a converted CP77 mod, or to rebuild and verify a converted .archive + .xl + TweakXL yaml package.
agent_created: true
---

# Cyberpunk EBB → ANGEL 服装转换

## 1. 用途

把按 EBB 身形建模的 Cyberpunk 2077 服装/鞋靴模组，转换为 ANGEL（Hyst Angel BodyMod 3.0.0）身形可用版本。目标是**几何层面真的贴合**，同时保留原模组的鞋型、跟高、鞋底、材质、贴图、颜色变体、Rig 绑定、Toggle Feet 等功能。

**不是**改配置、改名、整体缩放。任何"看起来像转换但没动几何"的做法都视为失败产出。

## 2. 适用触发场景

- 转换某套 EBB 鞋/衣到 ANGEL
- 已转换模组出现：能装备但无模型 / 贴图全黑 / 大腿穿模 / 脚踝捏痕 / 物品代码无效
- 需要重建或校验 `archive/pc/mod/*.archive` + `*.xl` + `r6/tweaks/*.yaml` 三件套

## 3. 硬性约束（不可协商）

1. 原始素材（`source_mods/`、用户给的源压缩包）**只读**。所有写出到 `converted/`、`build/`、`backups/`，永不覆盖源文件。
2. 不得用整体缩放 / 改名 / 只改配置冒充身形转换。
3. **缺目标身形数据就停下来报告**，不猜参数。
4. 不修改与身形转换无关的资源（材质、实体、图标、CSV、本地化）。
5. 不伪造几何校验结果、不伪造游戏内测试结论。未验证的就写"未验证"。
6. 批量处理、安装到游戏目录、对外分发，都需要用户显式确认后才执行。

## 4. 先决条件（缺一不可）

| 项 | 要求 |
|---|---|
| 转换工程 | 已有流水线工程（本机为 `<LEGACY_WORKSHOP_ROOT>`），含 `pipeline.py`、`wbx/`、`blender/scripts/refit_boot.py`、内置 `tools/wolvenkit-cli`、`tools/Depot` |
| ANGEL 参考体 | `reference_body/source/` 中主体 + `cs_heel` 高跟脚网格；导入前必须已有解剖锚点（膝/踝） |
| WolvenKit CLI | 可用；`export` 在本机未验证可用（缺 basegame 归档），转换只走 `convert serialize` |
| Blender | 5.3.x，`-b` 后台可跑；CP77 插件 2.0.0 只吃 `.gltf/.glb/.npz/.json` |
| 游戏 | 装好 ArchiveXL（≥1.28.6）+ TweakXL + CET，否则"能装备无模型/无物品" |

**没有现成流水线时**：先说明需要移植哪几个模块，再按 `references/conversion-workflow.md` 第 0 步搭最小链路，不要凭记忆重写解码器。

## 5. 执行流程（每次任务都走完）

1. **盘点**：解包源 MOD，列 archive 条目、`.xl`、`r6/tweaks`、贴图、图标；按 CR2W 头部识别真实类型（不信扩展名）。
2. **识别身形**：从骨骼名/权重/包围盒判断源身形（EBB）与目标身形（ANGEL），确认目标参考体版本。
3. **查案例**：在 `examples/` 找同结构历史案例（靴/衣、单网格/多网格、是否共用几何），判断可复用部分。
4. **定方案**：写明改哪些文件、改什么、预期位移量级、冻结区、风险；产出计划再动手。
5. **转换**：`serialize → 解码 → glb → Blender wrap refit → 位移场(.f32) → 回写 CMesh → deserialize → pack`。
6. **校验**：几何（顶点数/包围盒/逐点误差/冻结区零位移）+ 引用链（FNV1a64 命中）+ 材质引用全解析 + 非目标条目字节不变。
7. **对照**：前后穿模点分带对比；排查肉眼级异常（捏痕、鼓包、板结、贴图错位）。
8. **交付**：产物 + 质量检查报告（`templates/conversion-report.md`）。
9. **归档经验**：更新 `examples/`；只有通过上述校验 + 用户确认的经验才能升级进通用规则。

详细命令与写回细节见 `references/conversion-workflow.md`。

## 6. 已验证参数（4 套模组实测通过）

| 参数 | 值 | 作用 |
|---|---|---|
| `--fit-mode` | `wrap` | 既推穿模也收过松；原作者按更粗身形建模时必须用 |
| `--min-clearance` | `0.004` m | 目标最小间隙 |
| `--max-push` | `0.045` m | 单轮单点最大外推 |
| `--target-gap` | `0.008` m | 过松判定与回收目标 |
| `--max-pull` | `0.030` m | 单轮最大内收 |
| `--smooth` | `14` | 位移场 Laplacian 迭代；单轮会被稀释，必须多轮 |
| `--passes` | `8` | 实测 8 轮把 7~10% 穿模率压到 0.1~0.9% |
| `--shoe-guard` | `0.010` m | 鞋区冻结带高度（踝上） |
| `--ankle` z | `0.117625847` | ANGEL 踝锚点，**必须全精度，不可截断** |
| `--knee` | `-0.114866614,-0.0531997308,0.583594263` | ANGEL 膝锚点 |

`push` 仅在"源模型明显偏细"或"只求不穿模"时用；默认 `wrap`。

## 7. 判定规则（写方案前先对照）

| 现象 | 处理 |
|---|---|
| 源模组按更粗身形建模（大腿留 2~3cm 松量） | 必须 `wrap`，否则腿显粗 |
| 鞋跟/鞋底/鞋头有独立几何、踝下有装饰 | 冻结带覆盖到踝上 1cm，且按**原始顶点位置**一次性冻结 |
| 脚踝出现横向捏痕 | 收紧量在踝上 smoothstep 渐入（`pull_blend`），踝部保留原始松量 |
| 一包多网格 | 逐网格独立转换；<1000 顶点视为占位件跳过 |
| 多网格几何签名相同 | 可能共用几何，可只算一次位移，但回写/打包仍按各自条目 |
| 材质引用的贴图路径与归档内路径不一致 | 打包时按"包内同名文件"在引用路径补条目，不移动原贴图 |

## 8. 证据纪律（最重要）

每条结论必须标来源：

- **[已验证]**：有落盘 JSON 数字或游戏内确认支撑，附文件路径。
- **[推断]**：从数据结构推出的，未在游戏内验证。
- **[未验证]**：没做过，不得写成"可行"。

新经验只有同时满足：几何校验全绿 + 引用链全解析 + 用户游戏内确认，才可升级进第 6、7 节。仅单次通过、只在一套结构上验证的，留在 `examples/` 当个案。

## 9. 参考资料

| 文件 | 何时读 |
|---|---|
| `references/conversion-workflow.md` | 执行前：完整命令、目录、写回与打包细节 |
| `references/common-errors.md` | 遇到异常：症状 → 根因 → 修复 |
| `references/quality-checklist.md` | 交付前逐项过闸 |
| `templates/conversion-report.md` | 输出报告 |
| `examples/*.md` | 找可复用案例；含参数、实测数字、遗留问题 |
