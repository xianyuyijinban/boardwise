# 113 — 反激语法（flyback）：毕设语法谱系首块砖

**来源**：岳 2026-10-04 工具线裁定（112 避障布线的姊妹棒）。目标：让
「隔离反激变换器核心」有一个可执行的画法语法——模型说「这是反激」，
工具负责画出一眼能认出拓扑的图，而不是 110 那种「电气对但东一块西一块」。

## 必读素材（全部在仓库内，按序读）

1. 语法框架契约：`src/boardwise/engines/grammar/base.py`（roles / RoleBinding /
   RelativeConstraint / GrammarObligation / 失败类别 / 证据纪律）。
2. 范式模块（从短到长）：`grammar/rc_lowpass.py`（498 行，绑定判断写法）、
   `grammar/ldo.py`、`grammar/power_entry.py`（1364 行——分支序 + intent
   消费 + 大模块组织）、`grammar/ic_periphery.py`（1433 行——控制器外围
   已归它管，**你的语法不许重复造它**）。
3. `grammar/__init__.py`（注册表 / grammar_for / bind 调度）。
4. **110 的画法经验**（本语法的规则来源，逐条要吃进）：
   - `outputs/110/PLAN.md`（M1–M7 模块分解、拓扑决断表）；
   - `outputs/110/c/REVIEW.md` §四（规则盲区 5 条——本语法不负责补规则
     盲区，但绑定判断要能给「方向语义/环路闭合」留出角色证据）；
   - 岳在 110 全程的画法裁决（已归纳，逐条照办）：
     a. **T1 居中，原边朝输入侧、副边朝输出侧**（隔离界竖直）；
     b. **RCD 钳位贴原边上方**——尖峰就近泄放，钳位环路最短；
     c. **Q1 竖放**于原边下端（主开关环路 C4+→Np→Q1→Rsense→C4− 面积最小）；
     d. **sense 电阻在 Q1 source 与 PGND 之间直连**（采样环路贴地）；
     e. **反馈副边成链**：VOUT→分压→TL431→光耦 LED 在副边侧水平成链，
        **光耦是唯一允许竖直跨越隔离带的器件**（Y 电容若有，是第二个）；
     f. **双地分族**：PGND（原边）/ SEC_GND（副边）两族各自统一、绝不连通；
     g. E1 裁决：电源脚引出打电源网络标识；同属性远脚不互连、引出打标签。
5. 编译器怎么消费语法：`engines/drawcompiler.py` 里 grammar 绑定→约束求解
   的调用点（自己搜 `bind(` / `grammar`）；098 多模块整页的合成方式。
6. CircuitSpec 能不能说清三绕组变压器与光耦：`core/circuitspec.py`。
   **若合同表达不了，先停下来如实申报最小扩展方案，不许硬编码绕过。**

## 范围裁定（主代理已定）

- **本语法覆盖**：反激核心（110 的 M3 功率级 + M4 采样 + M6 输出整流滤波 +
  M7 反馈）+ 辅助供电链（aux D/C）。一个模块 `grammar/flyback.py`。
- **明确不覆盖**：交流入口与整流母线（M1/M2，power_entry 已有）、控制器
  本体的外围归属（M5，ic_periphery 已有）——flyback 语法与这两个语法
  **组合**使用，绑定判断里引用它们的角色证据，不复制其逻辑。
- 约束优先用既有 CONSTRAINT_KINDS 词表（base.py 全表）。确实需要新词
  （如「跨隔离带」）时：必须有编译器求解语义 + 测试，且在 SUMMARY 里
  单独申报给我复核。拿不准就用既有词组合表达。

## 角色表（绑定判断的结构化裁决，不读位号/值/符号名）

transformer（三绕组 Np/Naux/Ns，按「脚上的网类」判：Np 在 HVDC 与开关节点
之间、Ns 在整流二极管与副边地之间、Naux 在 aux 二极管与原边地之间）/
clamp-R/C/D（跨在 Np 两端的 R+C 串 + D 的链，结构判）/ switch（开关节点
与 sense 之间的 NMOS）/ sense（source 与 PGND 间的低阻）/ aux-D/C
（Naux→D→C→VCC 网链）/ sec-D（Ns 与 VOUT 间的二极管，方向=整流相位）/
output-caps（VOUT↔SEC_GND）/ feedback-divider（VOUT 分压）/ error-amp
（TL431 类）/ opto（一脚跨双地族的器件=隔离判据本身）/ compensation
（COMP 节点 RC）。每角色 binding 必须带 evidence 从句（base.py 的纪律）。

## 验收（三层）

1. **合成 CircuitSpec 单测**：全角色绑定成功；缺环路/双地连通/光耦缺失/
   方向不明等 → 正确类别的诚实拒绝（circuit-invalid / facts-missing）。
2. **真实 spec 端到端**：按 `outputs/110/plan.corrected.json` 的电路写
   `blocklib/specs/flyback_uc3845.circuit.json`（+presentation+library
   三件套，照 ch340_serial 的文件格式）→ `draw compile`（或 propose）
   → 预览 SVG → **用 `draw lint --snapshot … --render …` 离线闸**：
   0 ERROR 才算过；WARN/INFO 逐条申报。这是 111 的机器闸第一次当验收。
3. 与 110 手绘页对照：同一电路，语法预览 vs `outputs/111/geo_P1_live.json`
   的 lint 读数（48E/20W/21I）——把对照写进 SUMMARY。

## 交付纪律（111/112 同款）

红测先行；变异 ≥2（cp+sha256 还原）；零移动对账（83 预览 + 15 板）；
全量 pytest `--basetemp=.tmp_pt_home`（基线 **3560 passed**，跑期间零改动）；
证据落 `outputs/113/`（SUMMARY 含如实申报节）；`PROGRESS.md` 单行追加
（`grep -c "^- 113 "`=1）；禁 git/真机/daemon；删除走回收站；**不画真机**
（live 重跑归岳在场时）；不碰 router.py/addcomponent.py/drawlint.py 的
既有行为（grammar 组合需要动 drawcompiler 时最小侵入并申报）。
