---
name: cyberpunk-ebb-to-angel
description: Operate the Cyberpunk EBBRB-to-ANGEL workshop to inspect archives, prepare local references, run controlled boot refits and verify mesh and archive changes.
metadata:
  agent_created: "true"
---

# EBBRB → ANGEL 工作站操作

先定位用户提供的仓库根目录，确认 automation/main.py、config/ 和 README.md 存在。从该目录执行命令，使用当前 Python 环境。README.md 记录公开版本的配置与素材准备步骤。

## 入口选择

- 首次配置，运行 scripts/configure.py --help，按用户实际工具和身体文件路径配置。config/workshop.json 为本机生成文件。
- 检查命令，运行 python automation/main.py --help 和相应子命令的 --help。
- 资源检查，使用 inspect glb、inspect archive、wk health、wk roundtrip 和 wk pack-check，按输入类型选择。
- 身形参考，使用 ref list 和 ref build。EBB 与 EBBRB 为不同来源，核对 config/bodies/ 中的实际输入和版本。
- 长靴转换，先核对实体和外观指向的 mesh 条目。按 README.md 准备差异场及本机配方，再使用 boot-refit。输出到新目录。
- 网格结构检查，使用 garment-audit。输入应为源网格与候选归档重新提取后序列化的网格。
- 裙装或异常诊断，结合同仓库 cyberpunk-ebb-angel-converter Skill 与 docs/case-studies/。试点脚本需要各自输入，按实际证据判断适用性。

## 执行与验收

1. 确认文件来源、版本、作者依赖及输入哈希，保留源文件。
2. 分析实际网格、材质、外观和骨骼引用，确定需要改变的条目。
3. 执行适用配方，保存命令、日志、冻结区和校验结果。
4. 比较打包后条目和字节，检查面索引、新增退化、翻面、接缝及非目标数据。
5. 对照静态外形及触发问题的实机动作。结构检查成功只证明相应检查项。
6. 按同仓库 cyberpunk-ebb-angel-converter/templates/conversion-report.md 记录输入、修改、证据和待验证范围。

写入游戏目录前备份被替换文件并确认游戏已退出。按用户当前授权执行，已有授权继续有效。对外分发遵循相关素材作者的许可。

## 已验证案例与边界

开发机确认过黑色 Stelle Dress v5、Chrissy 和 DOLLY GO-GO Dress 1 v2 的受控结果。DOLLY v2 用户反馈静态外形正常，走路和跑步露皮消失。公开版本的基础测试使用合成几何，完整转换依赖用户自己准备的参考数据、模组和第三方工具。

源码中的 audit/phase3/ 含部分历史试点辅助代码。复用参数前核对案例输入，其他配色、其他身形和未观察的动作均需独立验证。旧 Stelle v3 因胸部破皮及颜色异常被否决，历史参数记录保留其具体范围。
