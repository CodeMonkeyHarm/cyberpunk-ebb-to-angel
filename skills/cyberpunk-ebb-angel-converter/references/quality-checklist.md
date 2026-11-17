# 质量检查清单

交付前逐项过闸。每项必须给出**实测值 + 来源文件**，不接受"看起来正常"。

---

## G1 输入完整性

| 检查 | 通过条件 | 证据 |
|---|---|---|
| 源包可解包 | 条目数 > 0，无 CRC 错 | `analysis/file_inventory.json` |
| 网格已序列化 | 每个目标网格都有 `analysis/mesh_json/<slug>/<name>.mesh.json` | 文件存在 |
| 网格可解码 | 解码成功，顶点>0，包围盒与声明一致 | `mesh_inventory.json` |
| 目标身形参考体齐全 | `angel_body/t0_000_pwa_base__full.glb` + `l0_000_pwa_base__cs_heel.glb` | 文件存在 |
| 锚点精度 | 膝/踝为全精度（≥6 位小数），非截断值 | `refit_*.json: anchors` |

---

## G2 几何转换

| 检查 | 通过条件 | 参考实测值 |
|---|---|---|
| 顶点数不变 | 转换后 = 转换前 | Chrissy 194567 / Kassie 131384 / Melinda 71131 / Stella 74683 |
| 冻结区零位移 | `frozen_vertices_moved == 0` 且 `max_frozen_displacement_m == 0.0` | 4 套全 0 |
| 穿模率显著下降 | 后 ≤ 1%，且腿部（calf/knee/thigh）分带应为 0 | 10.46→0.15 / 7.66→0.11 / 10.41→0.95 / 6.97→0.82 |
| 残余穿模位置合理 | 残余必须集中在 foot 带（冻结区，设计上不动） | Melinda 676 点全在 foot |
| 位移量级合理 | 最大位移 ≤ 30mm | 27.0 / 27.1 / 12.9 / 24.8 mm |
| 无位移尖峰 | 位移场平滑，无单点孤立大位移 | 看图 + 位移分布 |
| 鞋跟/鞋底刚性 | 与源网格逐点一致 | 冻结区校验 |
| 轮廓未被压平 | 鞋筒截面仍有原始松量（slouch 保留） | 前后截面对照 |

**无法完成时**：明确写"未检查 + 原因"，不得默认通过。

---

## G3 写回 CMesh

| 检查 | 通过条件 | 参考值 |
|---|---|---|
| 顶点数匹配 | `vertex_count_match == true`，写入数 = 位移数 | 71131 = 71131 |
| 逐点误差 | `max_error_mm ≤ 0.05` | 0.0072 ~ 0.0105 mm |
| 平均误差 | `mean_error_mm ≤ 0.02` | 0.004 ~ 0.0056 mm |
| 包围盒重算 | 声明 bbox = 重算 bbox | 一致 |
| 量化未截断 | `quant_step_mm` 落在精度上限内（≤0.011mm） | 0.0043~0.0073 mm |
| 序列化无损 | serialize→deserialize 往返字节一致（源文件验证） | 832635 字节 sha256 相同 |

---

## G4 打包

| 检查 | 通过条件 | 参考值 |
|---|---|---|
| 目标哈希在位 | `archive_has_name_hash == true`，每网格 `hash_checks` 全 true | 全 true |
| 只替换目标条目 | `entries_replaced` = 网格数 | 1 / 1 / 1 / 3 |
| 其余条目字节不变 | `compare.differ == []` 且 `compare.missing == []` | 全空 |
| 材质引用全解析 | `material_refs.all_resolved == true` | Melinda 补链 6 条后 true |
| 外部依赖已分类 | `external_unresolved` 明确列出并说明由谁提供 | Stella 引用原版皮肤材质 |
| 包内网格逐点复核 | 从成品归档解出的网格再验一次，误差同上 | 全 `within_tol` |
| 三件套齐全 | archive + `.xl` + `r6/tweaks/*.yaml` 同名对应 | 4 套齐全 |

---

## G5 引用链

| 检查 | 通过条件 |
|---|---|
| `verify_chain` 无本包缺失 | `missing_in_package == []` |
| 外部依赖已列明 | 每条注明由游戏本体或其他 MOD 提供 |
| 物品代码正确 | 正则 `Items\.[\w\-]+`，连字符不丢 |
| 物品数 = 颜色变体数 | Chrissy 4 / Kassie 7 / Melinda 3 / Stella 4（3 网格共用色系） |

---

## G6 游戏内（用户执行，Agent 不代填）

必须由用户在游戏里确认，Agent 只能记录用户反馈原文：

1. 物品能刷出、能装备
2. **有模型**（不是透明/无网格）
3. 贴图正常（不黑、不糊、颜色对应变体）
4. 站姿/行走无大腿穿模
5. 脚踝过渡自然（无横向捏痕、无板结）
6. 鞋跟高度/角度与原版一致
7. Toggle Feet / 其他原功能可用
8. 多颜色变体切换正常

未获得用户确认的项写 **"未验证"**，不得写"通过"。

---

## G7 交付物

- [ ] `build/<slug>_angel/archive/<原名>.archive`
- [ ] 安装树（archive + r6 对齐游戏根目录）
- [ ] `analysis/refit_<slug>*.json`
- [ ] `analysis/package_<slug>.json`
- [ ] `analysis/chain_<slug>.json`
- [ ] `reports/BOOT_REFIT_<slug>.md`（用 `templates/conversion-report.md`）
- [ ] sha256 清单（分发时）
