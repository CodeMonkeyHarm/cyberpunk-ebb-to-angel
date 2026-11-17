# Lizzy 全绑带长靴（Lizzy_Full_Lace_Boots_EBBRB_8548_1_16869）

- 状态：**部分完成，归档为反例**。几何转换跑通并进入游戏，但未作为最终验收交付；测试安装已按用户要求移除。
- 源包：`Wizzo's 'Lizzy' Full Lace Boots EBBRB-8548-1-16869...`
- 网格：`17551617435099059871`，42778 顶点
- 意义：本项目**第一个**转换目标，暴露了两个后来固化成规则的关键错误。

## 当时的流程（与现行流程的差异）

早期只有 `push` 模式、无冻结区校验、无材质补链：

```
fit_mode   = push          # 只推不收
ankle_z    = 0.1176        # 截断值（错误来源）
shoe_guard = 0.010
passes     = 8
smooth     = 14
```

## 结果

| 指标 | 前 | 后 |
|---|---|---|
| 穿模点 | 1365（3.19%） | 727（1.7%） |
| 最大位移 | — | 38.2 mm |

（`analysis/refit_Lizzy_Full_Lace_Boots_EBBRB_8548_1_16869.json`，passes 8）

## 暴露的问题与后续修复

### 1. "能装备但没有模型"
首次进游戏物品能加、能装，但身上没模型。
根因：缺 **ArchiveXL**。`*.xl` 只是 ArchiveXL 描述文件，没有它工厂表不加载。
修复：装 ArchiveXL 1.28.6（官方 GitHub 发布 + sha256 校验）。**这条与身形转换无关，是运行时依赖，后来写进交付说明。**

### 2. "腿太粗"
用户反馈腿部过粗。排查结论：**源模型本身就宽**（实测大腿处比 Angel 参考体宽 2~3.5cm），`push` 模式只推不收，松量全部留在外面。
修复：新增 `wrap` 模式（`target_gap=0.008`、`max_pull=0.030`），后续 4 套全部使用。

### 3. "后脚跟不正常"
根因：冻结线用了截断的 `ankle_z=0.1176`，而源网格边界点在 `0.12760566`；固定值产生的 `z_cut=0.1276` 恰好落在边界点下方，踝部点漏进可变形区。
修复：`--ankle` 传全精度；冻结区按**原始位置一次性判定**；新增 `frozen_vertices_moved` 校验（必须 0）。另外加 `pull_blend` 渐入，踝上保留自然松量。
反向教训：用户提供的官方图证明 Angel 脚踝本身有 slouch 堆褶——**不要把原设计当缺陷拉平**。

## 为什么保留为反例

- 参数（`push` + 截断踝）已被证伪，留档防止后人照抄
- 38.2mm 位移明显偏大（后续案例 12.9~27.1mm），说明只推不收会把轮廓往外顶

## 现状

- 测试安装已移除，备份在 `backups/`（`build/lizzy_removal_manifest.json`）
- 源包仍在 `source_mods/`，如需正式交付需用现行参数重跑
- **未验证**：现行参数下 Lizzy 的最终效果

## 证据

`analysis/refit_Lizzy_Full_Lace_Boots_EBBRB_8548_1_16869.json`、`analysis/refit_lizzy.json`（最早一次）、`analysis/package_Lizzy_Full_Lace_Boots_EBBRB_8548_1_16869.json`、`reports/BOOT_REFIT_LIZZY.md`
