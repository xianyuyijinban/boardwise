# R4 → v0.6.x：真·热更（stub + 动态载荷）——实验先行，不过实验不写代码

主题：消灭「更新 connector 要重载编辑器」这件事。当前热更（写 IndexedDB + reload）
本机实测可用，但 reload 会打断用户；目标是「daemon 换载荷、编辑器零操作」。

**前置结论（agent-302 侦察，已落账）**：
- 网络已通：扩展 realm 里原生 `new WebSocket('ws://127.0.0.1:61190/eda')` 实测 5ms
  连上（`outputs/026b_2b_p6_nativews.txt`）；daemon 只有 WS、没有 HTTP（`fetch` 不通）。
- 动态执行**未知**：编辑器 realm 能不能 `eval` / `new Function` / 动态 import，
  仓库里没有任何实测。
- 每次菜单点击宿主会重新求值 bundle（`connector/src/index.ts` + `tasks/004d` 实测）。

## 阶段一：实验清单（全部只读/最小写，test 工程窗口）

按顺序做，每步落证据（`outputs/R4/live/`），任何一步「不行」就停并如实报告：

1. **realm 能力探针**：在扩展 realm 里探 `typeof eval / Function / fetch / import`
   （借用现有 sys.probe 式动作或临时加一个只读探针动作）。
2. **`new Function` 执行字符串**：执行一段回哨兵值的代码，证明能跑。
3. **复现 165**：`update-connector` 写新 bundle → reload → 核 hello 版本，
   对照 030/031 正例——把「写≠激活」在本机的成立条件定清楚（165 是工作电脑孤例，
   本机 0.4.29→0.5.11 两次都 verified）。
4. **菜单点击不重载激活**：只点菜单不 reload，看跑的是不是新代码。
5. ①②通过才许进阶段二。

## 阶段二：stub 原型（实验全过才做）

- connector 改成「引导 stub（极小、永远不变）+ 启动/桥调用前从 daemon 拉当前载荷
  执行」。载荷版本由 daemon 管，`update-connector` 变成「daemon 换文件」，
  编辑器零操作。
- **安全面必须先写**：本地 WS 无认证，任何本机进程都能推载荷——载荷要签名校验
  （daemon 侧持有公钥/hash 白名单），stub 只执行验签通过的载荷。这段设计先在 PR
  里过审再写代码。
- 回退路径：stub 失效时用户能手动装回完整 bundle（`.eext` 永远随发布件提供）。

## 验收锚

- 阶段一五步证据齐全（含「不行」的诚实结论）；
- 阶段二：换一次载荷（版本号变）不重载编辑器，bridge status 回读新版本；
- connector npm 全绿 + 安全设计评审记录。

## 风险声明（写在脸上）

这个架构把「宿主是否重求值」的风险换成「运行时执行远端载荷」的风险。
若阶段一证明 realm 限制太死，或安全面谈不拢，**放弃是合法结论**——
现在的写+reload 通道在本机是通的，不是非换不可。
