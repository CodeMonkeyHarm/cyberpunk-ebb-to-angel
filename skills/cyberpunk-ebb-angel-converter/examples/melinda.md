# Melinda 裤缝高筒靴（Melinda_Full_Zip_Boots_CLIP_EBBRB_8514_1）

- 状态：**验收通过**（2026-11-13，用户游戏内确认"基本确认可过测"）
- 源包：`Wizzo's 'Melinda' Full-Zip Boots -CLIP- EBBRB-8514-1-0.rar`
- 网格：`melinda_crotch_high_boots-clip`，71131 顶点
- 颜色：3 变体

## 结构

| 项 | 值 |
|---|---|
| archive | `melinda_crotch_high_boots-clip.archive`（70,488,064 字节） |
| 条目数 | 14 |
| 脚本 | `melinda_crotch_high_boots-clip.xl` |
| TweakDB | `r6/tweaks/melinda_crotch_high_boots-clip_tweaks.yaml` |
| 物品代码 | `Items.melinda_crotch_high_boots-clip_1/_2/_3` |

## 参数

```
fit_mode = wrap, passes = 8, min_clearance = 0.004, max_push = 0.045,
target_gap = 0.008, max_pull = 0.030, smooth = 14, shoe_guard = 0.010,
pull_blend = 0.12, ankle_z = 0.117625847, z_cut = 0.127626
```

## 结果

| 指标 | 前 | 后 |
|---|---|---|
| 穿模点 | 7403（10.41%） | 676（0.95%） |
| foot 带 | 617 | 617（冻结区，设计上不动） |
| ankle 带 | 737 | 59 |
| calf / knee / thigh | 2535 / 3418 / 96 | 0 / 0 / 0 |
| 最大位移 | — | 12.9 mm |
| 冻结点 | 9817 | 0 位移 |

写回：`max_error 0.009mm`，`mean 0.0049mm`，`within_tol true`。

## 特殊处理（本案最有价值的部分）

1. **贴图全黑 → 材质引用补链**
   网格引用了 7 条 depot 路径，其中 6 条在源归档内不存在：材质指向 `base\melinda_crotch_high_boots\textures\...`，实际贴图在 `base\melinda_crotch_high_boots-clip\textures\...`。
   处理：`resolve_ref_aliases` 用**包内同名文件**在引用路径处补 6 个条目，不动原贴图、不改材质。
   校验：`material_refs.all_resolved == true`，`external_unresolved == []`。
2. **CSV 被误替换**
   `xl_stuff/melinda_crotch_high_boots-clip.csv` 与网格同 stem，早期替换逻辑把 CSV 换成了 `.mesh`，工厂表直接坏掉。
   修复：替换白名单限定 `.mesh` / `.bin`。
3. **物品代码含连字符**
   正则 `Items\.[\w]+` 会截断成 `Items.melinda_crotch_high_boots`，表现为"代码添加失败"。必须 `Items\.[\w\-]+`。

## 遗留问题

- 残余 676 个穿模点全部落在 foot 带（踝下冻结区），属预期：鞋跟/鞋底刚性不参与贴合。
- 用户曾反馈脚跟形态异常，经对照官方图确认 Angel 脚踝本身有 slouch 堆褶，非转换缺陷；`pull_blend` 渐入已保证踝部不被压平。

## 证据

`analysis/refit_Melinda_Full_Zip_Boots_CLIP_EBBRB_8514_1.json`、`analysis/package_Melinda_Full_Zip_Boots_CLIP_EBBRB_8514_1.json`、`analysis/chain_Melinda_Full_Zip_Boots_CLIP_EBBRB_8514_1.json`
