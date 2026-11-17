# 转换报告：<模组名>（<slug>）

- 日期：YYYY-MM-DD
- 源包：`<文件名>`（只读，位于 `source_mods/`）
- 源身形：EBB（作者 <作者>）
- 目标身形：Hyst Angel BodyMod 3.0.0
- 阶段：分析 / 单款转换 / 批处理
- 状态：OK / PARTIAL / FAILED
- 复用案例：`examples/xxx.md`（若无则写"无同结构案例"）

## 1. 源包结构

| 项 | 内容 |
|---|---|
| archive | `<名>.archive`（<字节数>） |
| 条目数 | N（网格 M 个，其余为材质/贴图/实体/图标） |
| 网格 | `<mesh1>`（<顶点数>）、… |
| 脚本 | `<mod>.xl` |
| TweakDB | `r6/tweaks/<mod>_tweaks.yaml` |
| 颜色变体 | N 个（列出物品代码） |

## 2. 方案与差异

- 与复用案例的相同点：
- 与复用案例的差异（必须逐条列，差异决定参数是否可套）：
- 冻结策略：
- 预期位移量级：

## 3. 参数

```
fit_mode    = wrap
passes      = 8
min_clearance = 0.004 m
max_push    = 0.045 m
target_gap  = 0.008 m
max_pull    = 0.030 m
smooth      = 14
shoe_guard  = 0.010 m
ankle       = (x, y, z)   # 全精度
knee        = (x, y, z)
```
偏离默认值的项与理由：

## 4. 几何结果

| 网格 | 顶点 | 穿模前 | 穿模后 | 最大位移 | 冻结点 | 冻结点位移 |
|---|---|---|---|---|---|---|
| | | n (%) | n (%) | mm | n | 0 |

分带明细（foot / ankle / calf / knee / thigh）：

## 5. 写回校验

| 网格 | 顶点匹配 | max_err | mean_err | within_tol | bbox 重算 |
|---|---|---|---|---|---|
| | true | mm | mm | true | 一致 |

## 6. 打包校验

| 检查 | 值 |
|---|---|
| 目标哈希在位 | true |
| 替换条目数 | N |
| 其余条目字节不变 | differ=[] missing=[] |
| 材质引用全解析 | true（补链 N 条） |
| 外部依赖 | 列出 |
| 包内逐点复核 | max_err mm |

## 7. 引用链

- 本包缺失：无 / 列表
- 外部依赖：列表 + 提供方
- 物品代码：N 条，已用 `Items\.[\w\-]+` 提取

## 8. 遗留问题与未验证项

| 项 | 状态 | 说明 |
|---|---|---|
| 游戏内装备/模型/贴图 | 已验证 / 未验证 | |
| 行走穿模 | | |
| 脚踝过渡 | | |
| Toggle Feet | | |

## 9. 证据文件

- `analysis/refit_<slug>.json`
- `analysis/package_<slug>.json`
- `analysis/chain_<slug>.json`
- `build/<slug>_angel/archive/<名>.archive`

## 10. 经验沉淀

- 本次新增可复用经验：
- 是否值得升级为通用规则：是/否 + 理由（需满足：几何全绿 + 引用链全解 + 用户游戏内确认）
- 仅适用于本案例的经验：
