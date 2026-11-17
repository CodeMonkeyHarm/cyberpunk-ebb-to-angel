# 转换流程（EBB → ANGEL）

本文件是执行手册。所有路径与命令均来自已验证的流水线工程
`<LEGACY_WORKSHOP_ROOT>`（下称 `$PROJ`）。
Windows + Git Bash，Python 3.13，Blender 5.3。

---

## 0. 最小链路（工程不存在时）

需要 5 个能力，缺一个就别开始：

1. `WolvenKit.CLI extract <archive> -o <dir>` —— 解包（**不要带 `-gp`**，会解整个 basegame）
2. `WolvenKit.CLI convert serialize <file> -o <dir>` —— 产出含 base64 顶点缓冲的 JSON
3. 自研解码器：读 JSON → 顶点/索引/骨骼/UV（先做布局解析，再按 stream 解码）
4. Blender 后台脚本：BVH 最近点求有符号间隙 → 位移场 → 平滑 → 导出 `.f32`
5. 回写 + 打包：改 JSON 顶点 → `convert deserialize` → `pack`

**不要**依赖 `WolvenKit.CLI export`：本机实测它需要完整 basegame 归档（缺则
`DirectoryNotFoundException`）与 `-gp` 参数，当前环境无法验证可用（见 common-errors A1）。

---

## 1. 盘点源 MOD

```bash
cd "$PROJ"
python pipeline.py environment_check     # 环境探测 -> reports/environment_report.*
python pipeline.py inventory             # 解包 + 类型正名 + glb 导出 + 度量
python pipeline.py body_analysis         # ANGEL 参考体度量与解剖锚点
python pipeline.py classify              # 靴型/跟高/鞋底分类
```

`inventory` 做的事（`wbx/inventory.py`）：

| 步骤 | 说明 |
|---|---|
| 复制源包 | 进 `source_mods/Wizzo/originals/` 并置**只读** |
| 解包 | `.zip` → zipfile；`.rar` → `C:\Program Files\WinRAR\UnRAR.exe` |
| 类型正名 | 归档内是哈希名 `.bin`，按 CR2W 头部 token 识别真实类型，硬链接成 `<hash>.mesh/.app/.ent/.xbm` |
| 序列化 | 对每个 `.mesh` 跑 `convert serialize` → `analysis/mesh_json/<slug>/<mesh>.mesh.json` |
| 度量 | 顶点数、包围盒、骨骼、几何签名 → `analysis/mesh_inventory.json`（唯一事实来源） |
| 预览 glb | 自研 glb 写出 → `analysis/glb/<slug>/<mesh>.glb` |

**`analysis/mesh_json/` 只增不改。** 后续所有改写都在副本上做。

每个 slug 必须可追溯：`slug → archive → raw 文件 → mesh.json → glb`。

---

## 2. 识别源/目标身形

- **源（EBB）**：看网格骨骼列表与权重分布，配合鞋筒剖面（`wbx/geometry.py: boot_profile`）。
- **目标（ANGEL）**：`reference_body/source/` 三包（主体 3.0.0 / VanillaRefit / MicrodetailPatch）。
  - 全身参考：`analysis/glb/angel_body/t0_000_pwa_base__full.glb`
  - 高跟脚参考：`analysis/glb/angel_body/l0_000_pwa_base__cs_heel.glb`

ANGEL 有独立的**高跟脚网格** `l0_000_pwa_base__cs_heel`，与 `cs_flat` 相比跟底 +7.75cm、脚底前倾 +31°，是不同网格，脚区必须用 `cs_heel` 做参考，否则脚背/脚跟判定全错。

解剖锚点从**靴子自身的 bind pose 骨骼**取（`LeftLeg` / `LeftFoot`），与 ANGEL 一致：

```
knee  = (-0.114866614,  -0.0531997308, 0.583594263)
ankle = (-0.156735942,  -0.0859771222, 0.117625847)
```

**踝 z 必须用全精度。** 曾用截断值 `0.1176`，导致冻结线 0.1276 落在源网格边界点 0.12760566 之下，踝部点漏进可变形区（症状：脚跟异常）。

---

## 3. 查案例

打开 `examples/`，按三个维度匹配：

| 维度 | 影响 |
|---|---|
| 鞋筒高度（短靴 / 过膝 / 裆高 / 护腿） | 冻结带与渐入区范围 |
| 网格数（单网格 / 多网格 / 共用几何） | 是否分网格转换、是否可复用位移 |
| 是否有独立鞋跟/鞋底几何 | 冻结策略 |

旧经验**只在结构相同**时可直接套参数；结构不同则从第 4 步重新定方案。

---

## 4. 定方案（先写再动手）

方案必须含：

1. 源包结构：archive 名、条目数、网格名、`.xl`、tweaks yaml
2. 目标身形版本与参考体路径
3. 可复用案例 + 差异点
4. 计划改动清单：只列需要替换的网格条目；**其余条目一律不动**
5. 参数选择：`fit-mode`、`passes`、冻结带高度、渐入区
6. 预期位移量级（参考：踝上 3~30mm）
7. 风险与不可验证项

未收到用户确认前，不做批量几何修改 / 导出 / 打包。

---

## 5. 执行转换

```bash
python pipeline.py refit --slug <SLUG> --fit-mode wrap
```

一包多网格时自动逐网格跑；`--mesh <name>` 只转指定网格；顶点数 <1000 自动跳过（占位件）。

`refit` 内部：

1. 从 `mesh_inventory.json` 取 glb（不存在则先跑 inventory）
2. 读 `mesh.json` 取 `LeftLeg` / `LeftFoot` 骨骼位置作锚点
3. 调 Blender：`blender -b --factory-startup --python blender/scripts/refit_boot.py`
4. 输出三样：
   - `converted/<slug>/<mesh>_angel.glb`（仅供看图，**不是**交付几何）
   - `converted/<slug>/<mesh>_disp.f32`（float32 每顶点 XYZ 位移，真正的产物）
   - `analysis/refit_<slug>[_<mesh>].json`
5. 再跑 `clearance_probe.py` 前后各一次独立复核 → `analysis/clearance_*.json`

### refit 算法要点（`refit_boot.py`，[已验证]）

| 环节 | 实现 |
|---|---|
| 有符号间隙 | `(顶点 - 最近点)·法线`，脚区（z < ankle_z）用 `cs_heel`，其余用全身 |
| 法线朝向自检 | glTF 导入后法线可能全朝内。用骨骼轴线判内外，抽样 1200 点投票，一致率 <0.4 则翻符号 |
| 冻结区 | 踝上 `shoe_guard`(10mm) 以下**按原始位置一次性判定**，鞋跟/鞋底/鞋头刚性 |
| 外推 | `d < min_clearance` → 沿法线推 `min(min_clearance-d, max_push)` |
| 内收（wrap） | `d > target_gap` → 收回 `min(d-target_gap, max_pull) × ease`，`ease` 从踝上 `pull_blend` 处 smoothstep 渐入 |
| 平滑 | 每轮外推后做 14 次 Laplacian（`cur*0.35 + avg*0.65`），冻结点锚 0 |
| 多轮 | 平滑会稀释位移，固定 8 轮，实测 1 轮不足 |
| 导出 | 只选靴子对象 + `use_smooth=True`，否则拆点导致拓扑校验失真 |

---

## 6. 写回 CMesh 并打包

```bash
python pipeline.py package --slug <SLUG> --reuse          # 只打包
python pipeline.py package --slug <SLUG> --reuse --install # 同时装进游戏目录
```

| 步骤 | 关键点 |
|---|---|
| 位移写回 JSON | 加到位图的 int16 量化位置；`quantizationScale/Offset` 基准是**网格自身包围盒**，外推必被 int16 截断 → 必须同步重定 scale/offset 并重算 `boundingBox` |
| 反序列化 | `convert deserialize <json> -o <dir>` 产出 `.mesh`（Oodle 压缩，不能就地改字节） |
| 逐点复核 | 重新解码新 `.mesh`，与「原位置+位移」比对，`max_error_mm` 应 ≤0.05 |
| 铺目录树 | 按**原条目名**重建（纯数字名 = NameHash，`pack` 会直接当 uint64 写入） |
| 替换 | 只替换目标 `<mesh>.mesh` / `<mesh>.bin`，**stem 匹配不得扩展到 `.csv`** |
| 材质补链 | 网格引用的 depot 路径哈希不在源归档内时，用包内同名文件在引用路径补条目 |
| 打包 | `pack <stage> -o <out>` → `build/<slug>_angel/archive/<原名>.archive` |
| 校验 | 哈希在位 + 除目标网格外所有条目字节不变 + 包内网格逐点复核 |

### 三件套（少一个就废）

```
archive/pc/mod/<mod>.archive        # 几何 + 材质 + 实体
archive/pc/mod/<mod>.xl             # ArchiveXL 工厂表引用
r6/tweaks/<mod>_tweaks.yaml         # TweakDB 物品定义
```

安装树从"含 `archive/` 与 `r6/` 的那一层"算起（有些作者多套一层目录，如 Chrissy）。

---

## 7. 引用链校验

```bash
python pipeline.py verify_chain --slug <SLUG>
```

逐条检查 depot 路径的 `FNV1a64` 哈希是否命中归档，输出：

- `missing_in_package`：本包真缺（必须修）
- `external`：游戏本体/其他 MOD 提供（正常）

运行链路：`TweakDB yaml → 工厂表 CSV → rootentity.ent → app.app → meshentity.ent → mesh`，任一环缺失症状都是**装备后无模型**，不会报错。

`WolvenKit.CLI hash` 即 FNV1A，可用于反查哈希对应路径。

---

## 8. 安装与分发

- `--install` 会先备份同名文件到 `backups/`；游戏运行时会锁 archive（WinError 32），必须等 `Cyberpunk2077.exe` 退出。
- 分包交付按 Nexus 原包风格：只含 `archive/pc/mod/*` + `r6/tweaks/*`；前置（ArchiveXL/TweakXL/CET）由目标机自备。
- 未获授权不得公开再分发。

---

## 9. 目录约定

| 目录 | 内容 | 可写 |
|---|---|---|
| `source_mods/` | 原始压缩包（只读） | ❌ |
| `extracted/<slug>/` | 解包结果 + `raw/` + `typed/` | ✅ |
| `analysis/` | 度量、refit、package、chain 的 JSON 与 md | ✅ |
| `converted/<slug>/` | `_angel.glb` + `_disp.f32` | ✅ |
| `build/<slug>_angel/` | 成包、安装树、`_verify_extract` | ✅ |
| `reports/` | 人读报告 | ✅ |
| `backups/` | 覆盖前备份 | ✅ |
