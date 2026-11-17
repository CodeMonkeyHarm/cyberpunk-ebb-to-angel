# Kassie 过膝靴（Kassie_Over_Knee_Boots_7936_1_1680293480）

- 状态：**验收通过**（2026-11-13）
- 源包：`Wizzo's 'Kassie' Over-Knee Boots-7936-1-1680293480.rar`
- 网格：`10303820480370732832`，131384 顶点
- 颜色：**7 变体**（本案变体最多）

## 结构

| 项 | 值 |
|---|---|
| archive | `wizzo_boots_othknee.archive` |
| 条目数 | 19 |
| 脚本 | `wizzo_boots_othknee.archive.xl`（双扩展命名） |
| TweakDB | `r6/tweaks/wizzo_boots_othknee.yaml` |
| 物品代码 | `_blackgloss / _blacksatin / _ltbluegloss / _pinkgloss / _redgloss / _whitegloss / _whitesatin` |

**注意 `.archive.xl` 双扩展**：这是原作者的命名，不是错误。安装时文件名必须原样保留，否则 ArchiveXL 找不到对应归档。

## 参数

默认已验证参数，`fit_mode = wrap`，`passes = 8`。

## 结果

| 指标 | 前 | 后 |
|---|---|---|
| 穿模点 | 10070（7.66%） | 138（0.11%） |
| 最大位移 | — | 27.1 mm |
| 冻结点 | 16110 | 0 位移 |

写回：`max_error 0.0072mm`，`mean 0.004mm`，`within_tol true`。打包：19 条目、替换 1、其余 18 条字节完全一致。

## 特殊处理

1. **过膝覆盖**：鞋筒跨过膝盖，knee 带顶点占比大，贴合后膝盖弯曲处的过渡需要靠 Laplacian 平滑保证，不要降低 `smooth`。
2. **7 色变体**：变体只影响材质/贴图，几何完全共用一套，不需按颜色重复转换。
3. `.archive.xl` 与 `.yaml` 命名都以 `wizzo_boots_othknee` 为 stem，替换时按题目白名单避免误伤。

## 遗留问题

- 无阻塞项。

## 证据

`analysis/refit_Kassie_Over_Knee_Boots_7936_1_1680293480.json`、`analysis/package_Kassie_Over_Knee_Boots_7936_1_1680293480.json`
