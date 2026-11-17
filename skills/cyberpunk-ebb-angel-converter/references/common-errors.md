# 常见问题（症状 → 根因 → 修复）

标注含义：**[已验证]** 本机实测踩到并修复；**[推断]** 由数据结构推得，未单独复现。

---

## A. 工具链

### A1. `export` 无法产出 glb（本机未验证可用）[2026-11-15 更正]
实测（CLI 10.0.0-beta.1）：
- 不带 `-gp`：rc=160，`Exporting mesh files with materials requires "--gamepath" to be set`
- 带 `-gp <游戏目录>`：rc=1，`DirectoryNotFoundException: ...\archive\pc\content`

根因：export 需要读取 basegame 归档来解析材质；游戏本体缺失时必然失败。
旧记录写的"任何配置下都不可用 / Depot bug"**证据不足**，已降级为"本机未验证可用"。
当前策略：转换走 `convert serialize` + 自研解码（`wbx/cp77mesh.py`），不依赖 export。
若日后游戏本体恢复，可用 `wk export-probe`（工作站）复测，再决定是否启用 export 路线。

### A2. `convert serialize` 报 `Found 0 files` [已验证]
根因：归档内条目是哈希名 `.bin`，serialize 只认已知扩展名。
修复：按 CR2W 头部 token 识别真实类型，硬链接成正名 `.mesh/.app/.ent/.xbm` 再序列化（`wbx/inventory.py: sniff_type / _typed_mirror`）。

### A3. `extract` 产生十万级文件、耗时失控 [已验证]
根因：带了 `-gp`，解包整个 basegame。
修复：**一律不带 `-gp`**。

### A4. `.ent` 序列化 RTTI 报错（`castShadows` 期望枚举得到 Bool）[已验证]
修复：跳过该 `.ent`，不参与几何转换；实体原样保留在归档里。症状不影响成品。

### A5. Blender 渲染 / 脚本产出为空 [已验证]
根因：`render.filepath` 用相对路径会静默不产出。
修复：写绝对路径（`Path.resolve()`）。

---

## B. 几何转换

### B1. 转换后"全身都穿模"，位移量巨大 [已验证]
根因：glTF 导入后身体面法线全部朝内，`(v-nearest)·n` 符号反了。
修复：先用骨骼轴线做朝向自检（抽样 1200 点，一致率 <0.4 翻符号）。实测一致率 0.0~0.112 → `sign=-1`。

### B2. 成品 glb 里混进 Angel 身体 [已验证]
根因：Blender glTF 导出默认导出整个场景。
修复：`use_selection=True` 且只选靴子对象。

### B3. 顶点数暴涨 42778 → 190412，拓扑校验全废 [已验证]
根因：硬边法线导致导出时按法线拆点。
修复：导出前 `poly.use_smooth = True`。boundary_edges 会等于全部边数即为该症状。

### B4. 转换后仍大量穿模 / 位移像"没生效" [已验证]
根因：单轮推挤被 14 次 Laplacian 平滑稀释。
修复：多轮迭代（`passes=8`）。实测 4 轮 664→26，8 轮可压到 0.1~0.9%。

### B5. 腿显粗 / 大腿处仍鼓 [已验证]
根因：源模组本来就按更粗身形建模（大腿留 2~3cm 松量），`push` 模式只推不收。
修复：`--fit-mode wrap`（`target_gap=0.008`、`max_pull=0.030`）。注意这会改变轮廓，必须用户确认。

### B6. 脚踝处出现横向捏痕 / 褶皱板结 [已验证]
根因：内收在全高统一施加，踝部原始松量被压掉。
修复：`pull_blend=0.12`，从踝上 12cm 内 smoothstep 渐入，踝部几乎不收。
反向注意：如果原设计本身就是 slouch 堆褶（Angel 官方图如此），**不要**试图拉平——先和官方图对照再动手。

### B7. 脚跟/鞋底被改形、鞋跟高度变了 [已验证]
根因一：冻结线用了截断的 `ankle_z=0.1176`，而源网格边界点在 `0.12760566`，冻结带漏点。
根因二：冻结判定用迭代中的实时坐标，边界点会漂进可变形区。
修复：`--ankle` 传全精度第 3 分量；冻结区**按原始位置一次性判定**；校验 `frozen_vertices_moved == 0`。

### B8. 高跟脚参考完全没生效 [已验证]
根因：`--body-foot` 未把 `-` 归一化成 `_`，`args.get("body_foot")` 取到 None，静默降级用全身网格。
修复：`parse_args` 统一把 `-` → `_`；并在报告里回显 `body_foot` 路径确认非空。

### B9. glb 回写成 CMesh 后模型错乱 [已验证]
根因：glb 导出必然重排/拆点，索引顺序不再对应原 CMesh。
修复：glb 只用来肉眼检查。**唯一交付几何是 `_disp.f32`**（每顶点 XYZ 位移），按索引加到原 CMesh 顶点上。

### B10. 回写后模型被"压平"/几何畸变 [已验证]
根因：位置是 int16，量化范围恰好等于网格自身包围盒（`q/32767*scale+offset`）。外推撞 int16 边界被截断（实测 7 个分量、最坏 0.93mm），且不再匹配声明的包围盒。
修复：写回时同步重定 `quantizationScale/Offset` 并重算 `boundingBox`；复核 `max_error_mm ≤ 0.05`。

### B11. 无法就地改 `.mesh` 字节 [已验证]
根因：顶点缓冲是 Oodle 压缩（2.26MB → 832KB）。
修复：`serialize → 改 JSON → deserialize`。往返字节级无损（832635 字节 sha256 相同）。

### B12. 多网格去重误判 [已验证]
根因：`geometryHash` 被多个不同网格复用，不能当唯一键。
修复：用实测几何签名（`wbx/geometry.py: geometry_signature`）。

---

## C. 打包与运行时

### C1. 物品能刷出、能装备，但**没有模型** [已验证]
根因一：缺 **ArchiveXL**。`*.xl` 是 ArchiveXL 描述文件，指向归档内 `base\xl_stuff\<mod>.csv` 工厂表。
根因二：工厂表 → rootentity → app → meshentity → mesh 任一环哈希缺失，症状同样是无模型且不报错。
修复：装 ArchiveXL（≥1.28.6）；跑 `verify_chain` 定位缺的是本包还是外部依赖。

### C2. 包打好但游戏里**刷不出物品** [已验证]
根因：只装了 archive，漏了 `archive/pc/mod/*.xl` 与 `r6/tweaks/*_tweaks.yaml`。
修复：三件套必须一起装。

### C3. 物品代码"添加失败" [已验证]
根因：提取正则写成 `Items\.[\w]+`，`\w` 不含连字符，`Items.melinda_crotch_high_boots-clip_1` 被截断。
修复：用 `Items\.[\w\-]+`。

### C4. 转换后**贴图全黑** [已验证]
根因：作者打包时路径错位。网格材质引用 `base\<mod>\textures\...`，实际贴图在 `base\<mod>-clip\textures\...`，哈希命不中。
修复：打包阶段扫描网格引用的 depot 路径，缺失项用**包内同名文件**在引用路径补条目；`package_*.json` 的 `material_refs.all_resolved` 必须 true。
无法解析的（如 Stella 引用的原版皮肤材质）属正常外部依赖，由游戏本体提供。

### C5. 打包后 CSV 被网格覆盖 [已验证]
根因：替换时 stem 匹配不分扩展名。Melinda 等包存在 `xl_stuff/<mesh>.csv` 与 `<mesh>.mesh` 同 stem。
修复：替换白名单只允许 `.mesh` / `.bin`。

### C6. `pack` 后的归档条目名变了 [已验证]
根因：`pack` 对纯数字文件名直接当 NameHash 写入（FNV1a64）。这其实正是原包行为。
修复：无需还原 depot 路径——按原条目名重建目录树再 pack 即可；用 `hash_hits()` 确认目标哈希在位。

### C7. 安装时 `WinError 32`（文件被占用）[已验证]
根因：游戏运行中锁住 archive。
修复：等 `Cyberpunk2077.exe` 退出后 `--install`。

---

## D. 流程与协作

### D1. 批量删除目录触发安全拦截 [已验证]
根因：一次 `rm -rf` 多个目录触发护栏，整条命令链中断。
修复：改为改名保留（`<dir>.bak_<时间戳>`），或用"排除目录"而不是删除。产物回滚靠改名，不靠删除。

### D2. `E:\` / 工程外路径中途消失 [已验证]
根因：外部目录被清理，脚本还引用绝对路径。
修复：工程自包含（工具、参考体、Depot 全在工程内）；只允许引用 Blender 安装目录与游戏目录。

### D3. 用户反馈"腿粗"被判为转换缺陷 [已验证]
排查顺序：先量原始网格宽度（`boot_profile`），确认是否源模型本身宽 2~3.5cm；是则属设计，需用 `wrap` 而不是继续加推挤。
不要在没有对照原始模型的情况下加大位移。

### D4. 失败被静默跳过
禁止。每个失败必须落盘 `status: "FAILED"` + 原因 + 证据路径。
