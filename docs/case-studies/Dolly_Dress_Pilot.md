# DOLLY GO-GO Mini Dress 1 ANGEL 适配

输入为作者 `FAIRYEXE DOLLY GOGO MINIDRESSES` v2。原始 RAR SHA-256 为 `bc9f24b9974de30322ebd3dc54064713cd4cee96018e96a1b44ff360c6afb818`。原始 archive 有 72 项资源。Dress 1 和 Dress 2 各自通过 `{gender}_{body}` 选择裙身，包内有 EBBRB 和基础身形网格。两个款式的外观都没有身体隐藏标签。

| 裙身输入 | 与 ANGEL 静态网格相交的裙面三角 | 胸部最深顶点穿透 |
|---|---:|---:|
| Dress 1 EBBRB | 207 | 11.84 mm |
| Dress 2 EBBRB | 190 | 10.28 mm |
| Dress 1 基础身形 | 374 | 23.09 mm |
| Dress 2 基础身形 | 373 | 23.09 mm |

选黑色 Dress 1 做实机基线。为固定源网格，在作者包中增加 `fairyexe_dollygogomini_dress1_w_angel.mesh`，内容为作者原始 Dress 1 EBBRB 网格。往返核验显示原有 72 项资源逐字节一致，唯一新增项的 SHA-256 与 EBBRB 源网格一致。这样可以在 ANGEL 存档中观察源 EBBRB 裙身，同时保留作者的物品、材质和其他身形配置。

## 基线实机结果

黑色物品为 `Items.fairyexe_dollygogomini_dress1_01`。同一 ANGEL 存档的物品栏截图 53–55 显示，基线正面双侧胸部露皮，黑色表面及高光正常。截图、启动日志和部署文件的校验值位于 `audit/phase3/dolly_dress_pilot/`。

## 候选 v1

在胸部接触区沿网格前方平滑移动局部顶点，最大位移 14.00 mm，保留腋下边缘和下裙位置。14、18、22 mm 三档离线静态相交均为零，采用位移最小的 14 mm。归档往返后复查，裙面与 ANGEL 相交的三角面从 207 降至 0，无新增翻面或退化面。基线已有 16 个退化面。修改区域的法线和切线已更新。

归档共 73 项资源，其中仅 ANGEL 版 Dress 1 的网格内容改变。材质、贴图和原作者的 .xl、.yaml 已由资源往返及部署校验确认。候选已部署到游戏目录，基线归档已备份。证据见 `audit/phase3/dolly_dress_pilot/candidate_v1/` 中的 `body_contacts.json`、`verification.json` 和 `deployment.json`。

## 候选 v1 实机复测与动态跟进

用户反馈静态正常，动态时胸下至腹部有轻微穿模。静态验收通过，动态问题保留，封测打包验收待完成。

已解析的实体和外观数据包含 entGarmentSkinnedMeshComponent 及 entSkinningBinding，没有检出独立布料模拟组件或 cloth、physics、simulation 命名属性。这项局部检查支持服装主要依靠蒙皮随动的判断，实际运行时的完整物理配置仍待确认。

候选的骨骼索引和权重与源网格完全一致。静态前躯干分带采样中，胸部区域最小余量约 1.22 mm，较低腹部区域约 14–19 mm。静态数据无法定位发生穿模的具体动作，也无法据此确认动态原因。用户随后确认走路或跑步触发该问题。证据位于 candidate_v1/dynamic_followup.json。

作者素材和本地候选限个人验证。

## 候选 v2 走跑余量试验

在静态已通过的 v1 上，对胸下至上腹前侧平滑增加最多 3.0005 mm 的余量。保留原骨骼索引及权重，几何、材质、UV 和归档往返通过核验，未新增退化面或翻面，原有重复顶点的接缝分离量为 0。相对 v1 的 73 项资源，唯一变化为 ANGEL Dress 1 网格。正面及侧面离线渲染已检查。

用归一化蒙皮权重和世界轴旋转模拟躯干前倾、扭转及迈步，v1 和 v2 在静态与四组简化动作中都未出现三角面相交。该检查没有复现实机走跑问题，因此 v2 是待实机验证的局部余量假设，实际原因仍未确定。简化姿态未包含游戏动画、运行时形变及完整第一人称模型切换。

v2 已替换游戏中的 v1，替换前的 v1 已备份。2026-11-18 用户确认同存档、同物品的走跑露皮消失，静态外形正常，本件受控验收通过。证据位于 audit/phase3/dolly_dress_pilot/candidate_v2/ 下的 geometry.json、verification.json、synthetic_motion.json、renders/ 和 deployment.json。离线结果不能作为动态验收通过的依据。

## 受控验收

2026-11-18，已核对当前安装归档与 v2 验证记录哈希一致，作者配置哈希一致。实机结果采用用户反馈，归档校验及对应启动日志见 candidate_v2/acceptance.json 与 accepted_runtime_logs/。第二件裙装的受控修正链满足进入本机封测打包的条件。其他配色和未观察的动作待验证。
