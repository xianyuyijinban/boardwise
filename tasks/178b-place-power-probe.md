# 178b placement 探针：`sch.place_power` 到底给地网挑哪个宿主字形

任务编号 178b。类型：真机**写**探针（test 工程限定）+ 清理。178 的唯一未决问题，
是「各挂各旗」在画布字形层面成立与否的裁决证据。

## 要回答的问题

`sch.place_power(kind=Ground, net=X)` 时，宿主按 net 名挑哪个地旗符号？

- `net=GND`（对照组，029d 实测是 `Ground-GND`）；
- `net=PGND`（宿主库**有** `Ground-PGND`，178 的 libprobe 已证）；
- `net=SEC_GND`（宿主库**没有** `Ground-SEC_GND`——回落到通用 `Ground-GND`？还是
  报错？还是造一个无名件？）。

178 的库侧工作（`PWR-PGND`/`PWR-SEC_GND` profile）只保证**计划/网表**层面各挂各旗；
本探针钉**画布字形**层面。

## 安全框（逐条有效，R1-R3）

- 只碰 **test 工程**（`--project test` 路由）。动手前 `bridge status` +
  `bridge call doc.list --project test` 对身份：焦点工程名逐字是 `test` 才继续。
- 页面选择：从 `doc.list` 的 documents 里挑一个**现有空 SCH 页**（060 留下的 P21、
  或 121d 用过的 P1 优先；用 `sys.get_document_source` 确认无 COMPONENT/无 WIRE）。
  不新建页、不删页。
- 写操作只许三笔：在空页放三颗地旗（间距 ≥100 单位，互不粘连）。放完立刻读回，
  然后**按 uuid 逐颗删掉**（060/121d 的清场手法），删完再读一次确认页面回到零件。
- 其余窗口（反激辅助电源、毕设FOC驱动板×2）**禁地**，任何动作不许路由过去。

## 方法提示（可复用的既有证据）

- `sch.place_power` 的参数形态看 `connector/src/actions.ts` 与 060 的探针记录
  （`outputs/064_railflag/`，四姿态×两族，8/8 的全套做法：放置→读回→按 uuid 清场）。
- 读回路径二选一（都做了最好，互证）：① `sys.get_document_source` 拉文档源，
  按放置返回的 uuid 找 SYMBOL/ATTR 记录，读出符号名（`Ground-?`）与 Global Net
  Name；② 060 的 SVG netflag 组解法（c_partid="netflag"）。
- 宿主对「没有 `Ground-SEC_GND`」的行为是**未知的三种可能之一**，如实记录，不许编。

## 验收与交卷

- 三颗旗各回答：放置成功/失败 + 宿主实际选的符号名（带 uuid 级证据）+ 清理确认。
- 证据落 `outputs/178b/evidence.md`（append + grep -c 防双写），原始读数
  （doc.list / 文档源片段 / 放置响应 / 删除响应）落 `outputs/178b/live/`。
- 结论一句话：「各挂各旗」在字形层面【成立 / 仅 PGND 成立、SEC_GND 回落通用字形 /
  不成立】，以及对 178 库 profile 的含义（无需改 / 需要补什么）。
- 页面终态必须零件零线（清理证据），探针动作之外零写。
- 禁 git、禁 rm。pytest 不用跑（纯真机探针），但若你顺手改了任何仓内文件：
  停下来报告——本任务书不含仓内改动。
