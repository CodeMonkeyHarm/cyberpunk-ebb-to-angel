# Cyberpunk EBBRB → ANGEL Workshop

用于 Cyberpunk 2077 服装适配的 AI Skills 和 Python 工作站。提供资源检查、参考身形分析、受控长靴转换、网格结构核验及 WolvenKit 打包往返。自主代码与 Skill 采用 GPL-3.0。

当前为公开源码测试版，优先支持 Windows 与 Python 3.13。开发环境验证过黑色 Stelle Dress v5、Chrissy 和 DOLLY GO-GO Dress 1 v2。DOLLY 的用户实机反馈包括静态外形正常、走路和跑步露皮消失。其他服装与动作需要逐件验证。

## 获取和基础测试

```powershell
git clone https://github.com/CodeMonkeyHarm/cyberpunk-ebb-to-angel.git
cd cyberpunk-ebb-to-angel
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe automation/main.py --help
```

基础测试使用合成几何。参考身形历史回归测试在用户尚未准备相应资产时会跳过。NumPy 2.5.4 为开发机验证版本，CI 会记录实际安装版本和运行结果。

## 使用两个 Skill

- skills/cyberpunk-ebb-to-angel 负责定位工作站、调用工具、管理项目及核验。
- skills/cyberpunk-ebb-angel-converter 提供适配经验、错误诊断、历史案例和报告模板。

将对应完整目录加入所用 AI 客户端支持的 Skill 安装位置，向代理提供本仓库路径。可使用如下请求开始。

> 使用 cyberpunk-ebb-to-angel 检查这个工作站。我将提供 WolvenKit、Blender、ANGEL 和 EBBRB 参考身形及一件待转换服装，先核对数据版本与引用，再制定适配方案。

## 配置本机工具

自行安装 WolvenKit CLI 和 Blender。Blender GLB 检查还需要可用的导入支持，相关流程使用 Cyberpunk Blender 插件时应按其安装说明准备。开发机使用 WolvenKit CLI 10.0.0-beta.1、Blender 5.3.0。

```powershell
.\.venv\Scripts\python.exe scripts/configure.py --wolvenkit 'C:\Tools\WolvenKit\WolvenKit.CLI.exe' --blender 'C:\Tools\Blender\blender.exe'
```

本机配置生成在 config/workshop.json。可追加 --game 指定游戏安装目录。config/bodies/ 提供身形档案，使用前核对实际源资产及版本。EBB 与 EBBRB 为不同输入。

## 准备参考身形和长靴配方

用户自行取得 ANGEL、EBBRB 与服装原包。用 WolvenKit 提取完整身体 .mesh 并序列化为 .mesh.json，保留对应原始网格。将路径交给配置程序。

```powershell
.\.venv\Scripts\python.exe scripts/configure.py --wolvenkit 'C:\Tools\WolvenKit\WolvenKit.CLI.exe' --blender 'C:\Tools\Blender\blender.exe' --angel-mesh 'C:\Assets\ANGEL\body.mesh' --angel-json 'C:\Assets\ANGEL\body.mesh.json' --ebbrb-mesh 'C:\Assets\EBBRB\body.mesh' --ebbrb-json 'C:\Assets\EBBRB\body.mesh.json'
.\.venv\Scripts\python.exe automation/main.py ref build --body ANGEL
.\.venv\Scripts\python.exe automation/main.py ref build --body EBBRB
.\.venv\Scripts\python.exe -m audit.phase2.morph_surface
.\.venv\Scripts\python.exe -m audit.phase2.diff_field_v2
.\.venv\Scripts\python.exe scripts/prepare_boot_recipe.py
```

差异场生成可能耗时。配方准备检查报告、字段哈希、参考版本、源顶点对应及使用区域的置信度。检查通过后保存本机配方，转换入口继续核对该配方的输入哈希。身形数据缺失或不匹配时请根据报错处理。

## 运行受控长靴转换

先检查服装实体和外观资源，确认实际网格条目，再执行。

```powershell
.\.venv\Scripts\python.exe automation/main.py boot-refit 'C:\Assets\boots.archive' --mesh-entry 'base\path\to\boots.mesh' --out 'projects/boots-trial'
```

输出包括候选归档、日志、冻结区掩码及 report.json。退出码 0 表示结构与归档核验通过。之后还需检查材质、静态外形和动作表现。备份后按原作者文件名安装，并使用作者配套配置。写入游戏归档前退出游戏。

## 裙装试点与当前范围

audit/phase3/ 中保留了部分裙装研究代码及当前入口所需辅助模块。DOLLY 和 Stelle 的裙装脚本依赖各自试点输入，当前需要逐件准备。历史案例见 docs/case-studies/，其中的 audit 路径用于描述开发机证据。

游戏、模组、身体参考、预生成差异场及本机日志由用户单独准备。源码发布时的基础测试与开发机实机验收分别记录，跨机器完整转换仍需实际测试。提交问题时附工具版本、错误信息、服装结构和可分享的最小复现步骤。

第三方工具及素材许可见 NOTICE.md。
