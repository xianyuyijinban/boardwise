# 528A 真机证据（2026-10-19 深夜，`test` 窗）

环境：立创 EDA Pro 3.2.149 · connector 0.5.18 · daemon 127.0.0.1:61190 · 3 窗在线
（反激辅助电源 / test2 / test）。只碰 `test` 窗，禁地未动。

## 一、结论：`--no-reload` 在真机上成立

| 断言 | 结果 | 证据 |
| --- | --- | --- |
| `--no-reload` exit 0 | ✅ | `EXIT=0` |
| **不派发 reload** | ✅ | instance id 前后都是 `inst-124815447-jjcl4qpr` |
| 无 `--yes` 也不问确认 | ✅ | 命令未传 `--yes`，无 [y/N] 提示 |
| 写记录与默认路径同字节 | ✅ | `ok: 0.5.18-nrl -> 0.5.18 (297513 bytes written to User_08be6a96fc064a03b488fd9d5a25ccea_v6)` |
| 打印激活方式 | ✅ | 见下方原文 |
| 默认路径仍 reload | ✅ | 阶段 1 reload 后 id `inst-110123909-kn69l57t` → `inst-124815447-jjcl4qpr` |

`--no-reload` 输出原文：

```
boardwise bridge update-connector: E:\boardwise\connector\dist\index.js (297513 bytes, 396684 as base64) -> version 0.5.18 -> window inst-124815447-jjcl4qpr -> 只写存储、不派发 reload
  ok: 0.5.18-nrl -> 0.5.18 (297513 bytes written to User_08be6a96fc064a03b488fd9d5a25ccea_v6)
  written, NOT activated: 0.5.18 is now stored in User_08be6a96fc064a03b488fd9d5a25ccea_v6, but no reload was dispatched — the editor keeps running the build it already evaluated (exit 0 means written, not running; nothing was read back)
  激活方式：在编辑器里点一次 boardwise 扩展菜单即生效 —— 不需要重载编辑器，未保存的编辑不会丢（宿主在菜单点击时重新求值扩展包）
```

**这条同时反证了新 build 正在跑**：若跑的是旧 build（不认 `reload:false`），缺省的 reload 会执行，
instance id 必变。id 没变 ⇒ 执行写入的是新 connector。

## 二、副产物：阶段 1 的 reload **确实激活了新 build**

阶段 1 用 `--version 0.5.18-nrl --yes` 走默认路径，reload 后新实例报 `0.5.18` → CLI 判 FAILED。
但随后的 `--no-reload` 证明新代码在跑。所以那次 FAILED 是**误报**：bundle 已被宿主重新求值，
只是 connector 自报的是 **bundle 内嵌版本**（build 时从 `connector/extension.json` 内联的常量），
不是存储记录里的 `--version` 串。

## 三、新洞（528A-a，建议同批修）：`--version` 与 bundle 内嵌版本不一致 → 必然假 FAILED

`--version 0.5.18-nrl` 只改存储记录的 version 字段；connector 回报的永远是 bundle 内嵌版本。
两者不等时，`update-connector` 的验收判据（「连接回来的窗是否报刚存的版本」）**永远不可能满足**，
于是把一次成功的更新报成：

```
FAILED — the write stored 0.5.18-nrl but a connector that (re)connected after the write announces 0.5.18
… 要生效只能手动走一遍：在立创 EDA 里卸载该扩展 → 重新导入 .eext → 重启编辑器 …
```

这段「卸载重装」的结论在实测中是**错的**——新代码已经在跑。代价是用户会去做一次完全不必要的
卸载重装（还会丢掉 connector 的配对状态）。修法建议（按最小改动排序）：

1. **首选**：`--version` 显式给出且 ≠ `connector/extension.json` 的版本时直接 exit 2，
   文案说明「`--version` 只写存储记录，connector 上报的是 bundle 内嵌版本；要区分版本请改
   `extension.json` 后再 build 一份 bundle」。禁止写出一个永远验收不过的记录。
2. 次选：保留写入，但把 FAILED 文案改成分诊——先问「存储版本与 connector 上报版本不一致」，
   再问「是不是宿主没重新求值」；「卸载重装」只在两者版本相同、且 reload 后仍是旧实例时才给。

## 四、未验（留给用户或下批）

- **点一次扩展菜单激活**：需要人在编辑器里点，自动化不了。可真机窗口当时跑的就是新 build，
  这条不影响 528A 的结论。
- `--all --no-reload` 多窗逐窗一行：单元测试已覆盖逐窗路由；真机未跑，因为 `--all` 会写
  反激辅助电源窗的存储记录（禁地），不值得为一条已在离线覆盖的行为去碰它。
- **首次引导**（`docs/bridge.md` §8 已写）：编辑器里正跑旧 build 时，第一次 `--no-reload`
  会因为执行写入的是旧代码而照样 reload。本窗户已在阶段 1 落地新 build，不再复现。
