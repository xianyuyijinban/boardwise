# 030 — update-connector 多窗口缺口（岳更新路上实测四坑）

> 2026-09-24 岳在（工作）机器上更新时实测踩出四个坑。1/2 是代码缺口，3/4 是文档与认知缺口。
> 朋友内测前必须修——多窗口是硬件工程师常态，更新是第一个会反复做的动作。

## 一、四坑原文（岳实测，照录）

1. 双窗口下 `update-connector --yes` 会 `WINDOW_UNSPECIFIED`——要逐窗口 `--instance`。
2. 两个窗口共用同一份 IndexedDB 记录（`User_309b46a8…_v6`），所以第二个窗口报 `0.4.19 -> 0.4.19`——
   不是出错，但它的 **verified 可能只是第一个窗口在应答**。别信那个 verified，要用 `bridge status`
   逐窗口核（岳核过，两个都是 0.4.19）。
3. 重载后 instance id 会变（`inst-100038368…` → `inst-020736655…`），旧 id 作废。
4. 重载后两个窗口都短暂匿名，约 4 分钟才自愈报出工程名——期间 `bridge status` 看不到工程名，
   但 `--project` 路由仍可用。**这不是显示 bug**（岳原话，他一开始怀疑过，是错的）。

## 二、架构决策（主代理定）

### 1. `update-connector` 多窗口三档行为

- **无寻址 + 多窗在线** → 拒绝，文案指引（沿用 issue #6 的 MULTI_WINDOW_FIX 句式）：列出窗口表，
  说明两种做法——`--instance <id>` 单窗更新，或 `--all` 全窗更新。
- **`--all`（新增）**：按**存储记录去重**写 bundle（共享同一 IndexedDB 记录的窗口只写一次，
  报告里写明"N 窗共享一份存储，写了 1 次"），然后**逐窗触发 reload、逐窗验收**（见 §二.2），
  每窗一行结果（新 instance id + 版本 + verified/unknown）。
- **`--instance` 单窗**：现行为不变。

### 2. verified 诚实性修复（坑 2 是正案）

025e 的 identity+version 判定在**共享存储**场景有盲区：第二窗的 verified 可能由第一窗应答满足。
修法：verified 只认**目标窗 reload 后那个新 instance 自己**报告的版本（绑定 reload 前的旧 instance →
reload 后的新 instance 的同一窗继承关系）；其他任何窗口的回答不计入该窗的 verified。
验收语义同步：`--all` 时每窗独立三态（verified / unverified(还在等) / unknown(预算耗尽)），
exit code 沿用 025e 的三态约定（0 全 verified / 3 有 unknown——查 025e 现码保持一致）。
**单测**：fake 双窗共享存储——A 窗已应答新版、B 窗的 verified 不得被 A 满足；B 自己 reload 回来后才算。

### 3. 文档收编（坑 3/4 + 共享存储事实）

- `SKILL.md` 坑表加一条：多窗口 update-connector 三档行为 + 共享存储 verified 盲区（修法指向 §二.2）+
  reload 后 instance id 必变（旧 id 作废，用 `bridge status` 重读）+ 匿名窗 ~4 分钟自愈是正常形态
  （`--project` 路由期间可用，因为路由吃的是 projectUuid 不是显示名）。
- `docs/getting-started.md` 的更新段落：多窗口用户推荐 `--all`；更新后用 `bridge status` 逐窗核版本
  （岳的人工核对法收编为官方步骤）。
- `docs/bridge.md` §10 相应条目补"重载后 ~4 分钟匿名期"与"共享 IndexedDB 记录"两个事实。

## 三、验收

- 三线全绿（pytest `--basetemp=.tmp_pt_home`；动 cli.py 为主，connector 不动则不跑）；
- 单测：三档行为（拒绝文案 / `--all` 去重写一次 + 逐窗验收 / `--instance` 不变）+ 共享存储 verified 盲区用例；
- 变异 ≥2（verified 被异窗满足 / `--all` 对共享存储重复写，都要有红）；
- 真机（本机三窗 test/test2/ROBOT——**注意 ROBOT 是禁地，`--all` 真机验证前问主代理**：
  可以只做 test/test2 两窗的 `--all`，ROBOT 窗全程不寻址；若 `--all` 的实现会无差别 reload 所有窗口，
  先停下来报，不许带禁地窗玩）；
- 证据 `outputs/030_*.txt`。

## 四、守卫

- 不动 025e 的三态 exit code 约定（0/1?/3——以现码为准），只把 verified 的**判定**收紧；
- `--all` 的去重键 = 存储记录标识（岳观察到的 `User_309b46a8…_v6` 形态），不是工程名；
- 文案中文跟周围 fix 文案一致；PROGRESS 由主代理更。

## 五、交卷记录

（子代理交文本，主代理 append 并复验。）
