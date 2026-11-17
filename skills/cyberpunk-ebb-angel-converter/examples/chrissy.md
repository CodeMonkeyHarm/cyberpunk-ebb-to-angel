# Chrissy 绑带裆高靴（Chrissy_Crotch_High_Boots_EBBRB_8458_1_0）

- 状态：**验收通过**（2026-11-13）
- 源包：`Wizzo's 'Chrissy' Crotch-High Boots - EBBRB-8458-1-0-1685733780.zip`
- 网格：`12750523408280256843`，194567 顶点（本案顶点数最大）
- 颜色：4 变体

## 结构

| 项 | 值 |
|---|---|
| archive | `Chrissy-Laced-Crotch-High-Boots-rb.archive` |
| 条目数 | 17 |
| 脚本 | `laced_crotch_high_boots.xl` |
| TweakDB | `r6/tweaks/laced_crotch_high_boots_tweaks.yaml` |
| 物品代码 | `Items.laced_crotch_high_boots_1..4` |

## 参数

默认已验证参数（同 SKILL 第 6 节），`fit_mode = wrap`，`passes = 8`，锚点全精度，`z_cut = 0.127626`。

## 结果

| 指标 | 前 | 后 |
|---|---|---|
| 穿模点 | 20344（10.46%） | 300（0.15%） |
| 最大位移 | — | 27.0 mm |
| 冻结点 | 14902 | 0 位移 |

写回：`max_error 0.009mm`，`mean 0.0048mm`，`within_tol true`。打包：17 条目、替换 1、其余 16 条字节完全一致。

## 特殊处理

1. **源包多套一层目录**
   解压后不是直接 `archive/` + `r6/`，中间还有一层。安装树必须从"含 archive 与 r6 的那一层"起算，否则游戏读不到。
2. **大顶点数**
   19 万顶点、每轮含 14 次 Laplacian，单次 refit 耗时明显高于其他案例；不要用它在多轮里反复试参数。
3. **裆高剪裁**
   鞋筒上端接近裆部，整体最大位移 27.0 mm（四套里最高）；高位移集中在筒身上段。分带位移量未逐带拆分验证，报告里不要写成"thigh 带 27mm"。

## 遗留问题

- 无阻塞项。高位移区（thigh 带）建议后续整套批处理时优先做视觉复核。

## 证据

`analysis/refit_Chrissy_Crotch_High_Boots_EBBRB_8458_1_0.json`、`analysis/package_Chrissy_Crotch_High_Boots_EBBRB_8458_1_0.json`
