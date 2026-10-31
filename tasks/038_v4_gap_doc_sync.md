# 任务书：V4 O1–O3 文档与声明钉同步（2026-10-31）

> 在线行为已验证，收尾只改文档与对应声明测试，不改生产行为。

## 必须同步

1. `docs/pits.md` #23：不再写“PCB render 60s 是历史报告、本批未复现”。写入2026-10-31
   V4.1.93 实测：已激活仍整60s不返回，schematic-only API；停止调用、pcbImage=not-applicable，
   livePcb走readback+geometry，归档/离线SVG不冒充live PNG。保留激活/焦点一般性教训。
2. `docs/pits.md` #27：V3主机ERC只有聚合计数是历史实测；V4.1.93已返回逐条
   `{type,rule,primitives}`，不能再写所有版本都没有逐项条目。保留V3面板证据边界。
3. `docs/review-sop.md`：去掉仅为旧钉子保留的“本批没有复现”套话，直接写O2实测与当前
   not-applicable；如ERC描述存在“只有聚合”同步V4逐条。
4. `tests/test_doc_claims.py`：把过期硬断言改成当前机器可验声明，必须钉住O2的
   `not-applicable`/禁止render调用/60s实测和O3的per-item/host-wide去重（如文档有述）。
   不得通过删测试或只搜旧套话掩盖。
5. `outputs/review/v4-o3b-python-drc.md`、`v4-o3a-connector-drc.md` 的“剩余项”可补记这些文档已同步，
   不改历史实测计数。`outputs/review/v4-online-acceptance.md` 可补主代理最终状态。

## 验证与边界

- 实跑 `tests/test_doc_claims.py` 与必要的相邻合同测试，独立basetemp。
- 只做 docs/上述测试/证据，不做git写、真机、生产代码变更。
- 交真实改动和计数，最多20步或15分钟。
