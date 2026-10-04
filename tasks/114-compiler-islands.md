# 114 — 编译器补课：支路串传递归属 + 第二孤岛行排

**来源**：113 反激语法揭的缺口（`outputs/113/SUMMARY.md` §四第二层，如实申报）。
113 把反激的画法关系全落成了既有词表，但编译器的「一条链 + 支路」模型
解不出来：整页 0 candidates。**本棒只动编译器求解，不动语法判断**。

## 两处缺口的机制（主代理已定位，坐标给你）

### 缺口 1：支路串的中间节点无 owner

`drawcompiler._branch_owner`（:1307）只在 `chain_ids` 里找共享网——
钳位串 R→C 串联的中间臂（110 的 R3）只与其它**支路件**共享 CLAMP_B 网，
链件一个都够不到 → 自由架 → 0 candidates。反激里至少两处处是这个形态：
钳位串（clamp-R→clamp-C）与辅助链（aux-D→aux-C，aux-C 只与 aux-D 共享
辅助轨网）。

**方向**：传递归属——支路的 owner 可以是**已归属的支路件**（不动点迭代），
串的内部顺序由串内网拓扑读出；够不到链的串保持诚实拒绝并**点名断在哪一环**
（不许静默上链）。环保护要想清楚（两支路互相成环且无链锚 = 拒绝）。

### 缺口 2：第二孤岛的 same-row 排不出来

113 的实测拒绝：副边反馈横排（分压臂/误差放大/光耦，`same-row`）差 5 单位
（栅格 5，公差 slack=grid/2）。机制：支路的摆放只看自己 owner 的节点
（`_branch_slot` :1328），同一孤岛内**支路彼此之间**的行/列关系没有人消费；
`_relation_holds`（:5573）只在事后量，量出来不符就拒。

**方向**：摆放阶段消费支路×支路的 same-row/same-column 关系——同关系的
支路组共享一条 lane（先解关系再落子，不是落完再量）。序列关系
（left-of/right-of/above/below）**不在本棒**——113 实测过链上两件的序关系
「被挂侧引脚对原点」在任何合法位姿下都不可满足，语法那边已改用 near/same-row
表达，本棒只需让支路间 same-row/same-column 可解。

## 验收（三层，全是硬数字）

1. `blocklib/specs/flyback_uc3845.{circuit,presentation,library}.json`
   **整页编译出 ≥1 个 candidate**，且该 plan 的关系/义务检查零 findings
   （编译器自己的 `_obligation_findings` / 关系复核全过）。把候选的
   预览 SVG 落 `outputs/114/`。
2. **既有五语法的编译输出逐字节不变**：重生成 053b/056/088/088b/098
   五族预览 83 张 + 15 夹具容器 review 读数，sha256 前后全同——
   这是本棒最硬的闸（你动的是公共求解器）。
3. 合成编译器单测：支路串（三件套串联支路）传递归属成功；支路串够不到链
   → 诚实拒绝点名断环；孤岛支路组 same-row 共 lane 落子成功。
   113 的 skip 测试（`test_the_offline_lint_gate_cannot_run_yet_and_says_why`）
   的 skip 理由里「编译器排不出」那一半摘掉了→更新该测试的理由文本
   （保留 live 快照那一半——真机落图归岳在场时）。

## 边界与纪律（同款）

- 语法模块（grammar/*.py）**原则上不动**；确实要微调关系集合时最小侵入
  并在 SUMMARY 单独申报。`flyback.py` 的绑定判断一字不许改。
- 113 的 CHAIN/BRANCH_ROLES 词表已经就位（sec-D/opto 在链上当副边锚点），
  本棒不增删角色。
- 红测先行；变异 ≥2（cp+sha256 还原，禁 git checkout/sed）；零移动对账
  （上面验收 2 就是）；全量 pytest `--basetemp=.tmp_pt_home`
  （基线 **3602 passed + 1 skipped**，跑期间零改动）。
- `PROGRESS.md` 单行追加（`grep -c "^- 114 "`=1）；证据落 `outputs/114/`
  （SUMMARY 含如实申报节）。
- 禁 git/真机/daemon；删除走回收站；不碰 connector/dsh-plugin。
- **这是最深的求解器手术**：拿不准的设计分叉（比如传递归属的迭代上限、
  孤岛 lane 与主轴的相对定位）选**保守、可解释、可复测**的那个，并在
  SUMMARY 写明取舍。
