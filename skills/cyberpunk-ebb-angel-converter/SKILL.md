---
name: cyberpunk-ebb-angel-converter
description: Diagnose Cyberpunk 2077 clothing refits to ANGEL using recorded garment cases, mesh invariants and runtime evidence. Use for choosing a refit approach or investigating clipping, material failures and mesh routing.
metadata:
  agent_created: "true"
---

# ANGEL 服装适配经验

先明确源身形是 EBB、EBBRB 还是作者已有的 ANGEL 版本，结合网格与作者说明确认。文件名和骨骼列表只能提供部分依据。选择与服装结构对应的参考案例，实测数值以案例所记录的版本和输入为范围。

工作站执行入口由同仓库的 cyberpunk-ebb-to-angel Skill 说明。先定位包含 automation/main.py 和 config/workshop.json 的工作站根目录。通过当前 --help 和对应报告确认命令，再执行。

## 当前验收证据

2026-11-18 的受控结果包括黑色 Stelle Dress v5、Chrissy，以及 DOLLY GO-GO Dress 1 v2。DOLLY v2 经用户确认静态外形正常、走路和跑步露皮消失。当前工作站的 README.md 与 docs/case-studies/ 记录版本、输入及放行范围。其他配色和未观察的动作继续标记待验证。

## 按问题读取案例

- 长靴结构、冻结区和脚踝过渡，读取 examples/chrissy.md、examples/melinda.md 或 examples/kassie.md，并对照当前工作站 docs/case-studies/Boot_Refit_CLI.md。
- 装备后无模型、材质异常或引用链问题，读取 references/common-errors.md，再核实当前实体、外观、材质及所需前置。
- 旧 Wizzo 工程的具体回写方法，读取 references/conversion-workflow.md 和 references/legacy-skill.md，并先核对该工程与工具是否实际存在。
- 制作交付报告时使用 templates/conversion-report.md，并按本次实际执行范围填写。

案例中的 wrap 参数、解剖锚点和顶点数量阈值属于相应历史输入，复用前需用当前模型验证。保留源文件、骨骼权重和材质行为，若任务确需改变这些内容，记录修改原因和核验结果。

区分结构核验、离线贴合和实机观察结果。局部新增余量可能缓解动作穿模，简化姿态检查通过时仍需用触发该问题的实机动作复测。已有试点通过的事实不能直接推广到所有服装。

安装与覆盖按用户当前授权执行，备份替换文件并核实游戏退出。素材和转换结果的分发按各自作者许可处理。
