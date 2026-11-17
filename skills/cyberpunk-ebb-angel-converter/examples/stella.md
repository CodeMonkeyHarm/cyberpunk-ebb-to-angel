# Stella 护腿高跟长靴（Stella_Chap_Boots_Hyst_EBBRB_8005_1_1680）

- 状态：**验收通过**（2026-11-13）
- 源包：`Wizzo's 'Stella' Chap Boots - Hyst EBBRB-8005-1-1680843458.zip`
- 网格：**3 个**，各 74683 顶点
  - `7280658345495154142`（哈希名，旧变体）
  - `s1_045_wa_boot__00chap_hyst`
  - `s1_045_wa_boot__00chap_vanl`
- 颜色：4 变体（blackgloss / blacksatin / redgloss / whitesatin）

## 结构

| 项 | 值 |
|---|---|
| archive | `wizzo_boots_00chap.archive` |
| 条目数 | 20 |
| 脚本 | `wizzo_boots_00chap.archive.xl` |
| TweakDB | `r6/tweaks/wizzo_boots_00chap.yaml` |
| 物品代码 | `Items.wizzo_boots_00chap_blackgloss` 等 4 条，3 个网格共用色系 |

## 参数

默认已验证参数，`fit_mode = wrap`，`passes = 8`。

## 结果

| 网格 | 前 | 后 | 最大位移 |
|---|---|---|---|
| 7280658345495154142 | 5209（6.97%） | 616（0.82%） | 24.8 mm |
| `.._hyst` | 5199（6.96%） | 616（0.82%） | 24.8 mm |
| `.._vanl` | 5793（7.76%） | 616（0.82%） | 24.8 mm |

冻结点 15788，零位移。写回：`max_error 0.0105mm`，`mean 0.0056mm`（本案误差最大，仍 ≤0.05 容差）。打包：20 条目、替换 **3**、其余 17 条字节完全一致。

## 特殊处理

1. **一包多网格**：三个网格必须各自转换、各自回写，`package` 一次放入全部替换项；不能只转一个。
2. **三个网格顶点数完全相同（74683）**：疑似由同一源几何派生。仍按独立网格处理——`geometryHash` 不可用于去重（多网格同值）。
3. **外部材质依赖**：网格引用了原版游戏的皮肤材质，归档内本就没有，`external_unresolved` 非空属正常，由游戏本体提供。**不要**尝试把这些也塞进包。
4. 量大（20 条目、3 替换、70MB+ 归档），打包与解包复核耗时最长；`_verify_extract` 会留下大量哈希名文件，不要手动清理到发布包里。

## 遗留问题

- 无阻塞项。三个网格残余 616 点均在 foot 冻结带，属预期。

## 证据

`analysis/refit_Stella_Chap_Boots_Hyst_EBBRB_8005_1_1680_{7280658345495154142,s1_045_wa_boot__00chap_hyst,s1_045_wa_boot__00chap_vanl}.json`、`analysis/package_Stella_Chap_Boots_Hyst_EBBRB_8005_1_1680.json`
