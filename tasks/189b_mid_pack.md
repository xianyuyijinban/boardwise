# 任务书：189B — 中危打包（intent 两句/stale 崩溃/eprj2 文案/前缀判型/skill 卫生）

- 批号：**189B**　日期：2026-10-16　来源：岳的 0.5.13 实板使用反馈 ③④⑤⑦⑧⑨

## 1. ③ intent「不存在」vs「读不了」分两句（`cli.py` intent 显示处 + `engines/checkup.py` intent_section）

- 现状：合同文件存在但 schema 校验失败时，顶层结论写「不存在」——把使用者引向路径/uuid 排查方向
- 修：`readError` 非空 → 显示「**读不了：<原因>**」（原因从 readError 取）；为空才显示「不存在」
- 测试：合法合同「存在」、不存在文件「不存在」、坏 schema 文件「读不了：…」三态

## 2. ④ checkup 崩溃不产出（`engines/checkup.py` intent_section :1986）

- 现状：`facts["stale"]` 是字符串列表（计数用），塞进 `section["stale"]` 后 `render_intent_markdown` 按字典 `entry.get("object")` → AttributeError，report 一个不产出（规则白跑几分钟）
- 修：改取 `facts["staleEntries"]`（字典列表，渲染用）；`cli.py:14092/14111` 读 `facts["stale"]` 计数是对的，**别动**
- 测试（反馈原文纪律：测试必须在被破坏时失败）：接缝测试——构造含 stale 对象的合同 + 图纸对象已消失，断言渲染产出含该行且不炸；**变异验证**：把 intent_section 改回取 `stale` → 测试必须红（不红的测试不收）
- 崩溃兜底（顺手）：写报告阶段（规则跑完后）任何异常不该让报告零产出——intent 节渲染包 try，异常降级为节内错误行（「intent 节渲染失败：<err>」），主体报告照出。这条做完问自己一遍：还有没有别的节会同样全灭？有则同款兜底（别扩到规则执行阶段）

## 3. ⑤ `.eprj2` 错误文案（`cli.py` 输入类型拒绝处）

- 现状：`unsupported input type .eprj2; expected ...`
- 修：追加指引——「本工具不读 `.eprj2`（立创 EDA 工程容器）；请在编辑器里 文件 → 导出 → 工程备份 另存 `.epro2`（取消勾选加密），或到 `<工程名>_backup\` 找已有快照」

## 4. ⑦ 位号前缀当器件类型（`rules/pcb/derating.py` 及相关判型处）

- 现状：`U` 位号的 330kΩ 电阻（`FRC1206J334TS`，立创元数据写「厚膜电阻」）被降额规则按 IC 报「串联电阻串电压分不下来」类 finding（实板 5 条无意义 finding）
- 修：判型顺序改「**元数据/MPN 优先，位号前缀兜底**」——立创元数据（`LCSC Part Name`/`Supplier Footprint`，.epro2/.enet 里读得到）或 MPN 解码能判出类型的，以它为准；判不出才退前缀
- 影响面评估：derating 之外还有谁靠前缀判型（foc 族/mcu 族/decap）——只改 derating 这处（反馈点名的），其余在证据里列清单进 190
- 测试：U 位号电阻不再被当 IC 报；真 IC 照报

## 5. ⑨ U1 去耦归因（评估先行，`rules/pcb/decap.py`/`regulator.py`）

- 案例：工程师纠正「U1 是输出 3.3V 的，没必要贴近放置电容」——规则报的是 `+12V` 轨上的距离，归因不对
- **先评估**：`pcb-regulator-cap-distance`/`pcb-decap-distance` 对「稳压器输出电容」的轨归因逻辑是什么；该案例是规则错了、还是读数对但表述归因错
- 按评估修：归因按「电容服务的轨」（输出电容→输出轨）而非「器件输入轨」；或至少 finding 文案把「按哪条轨量的」写明（披露，让使用者能当场判断）

## 6. ⑧ skill 卫生（`.kimi-code/skills/boardwise/SKILL.md` + `cli.py install-skill`）

- 文档里写死的开发态路径（`E:\boardwise\.venv\...`）改成占位/「按你的 checkout 位置」表述（岳的工作电脑在 C 盘，照抄就错）
- install-skill 备份策略：同目录 `SKILL.md.bak-*` 保留**最近 3 份**，更老的自动清理（进回收站，不直删；references 的 `.bak-*` 同理）；装完打印保留了几份

## 纪律

- 全量绿 `--basetemp=.tmp_pt_189b` `-n 4 --dist loadfile`（sources 在位）；变异验证 ≥2 组（④ 接缝 + ⑦ 判型）
- 红线：不动 git；删除走回收站；真实项目名零出现；report schema 只加不改；动了 rules/ 重钉 test_126a recursive/direct + 台账
- 证据 `outputs/189b/evidence.md`；PROGRESS.md append 一行；**不要 commit**
