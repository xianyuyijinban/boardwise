# 任务书：190S — 底层丝印文字延伸方向：真机定标 → 离线口径落地

- 批号：**190S**　日期：2026-10-16　来源：岳「底面位号丝印不见了」（189Cf `d01df0e` 已修画出视窗的洞）后暴露的口径问题
- 一句话：离线档没有原生文字包络，`SilkText.corners()` 对底层文字按「从锚点沿 +u（angle 方向）延伸」建模；
  6 块板统计不一致（实板A 29/29 指向 -u、毕设FOC 0/3、其余五五开）。这个方向决定 `pcb-silk-designator`
  底层位号包围盒的落点——岳 10-16 反馈第九节第 3 条「R22 丝印压 EC3」被工程师当场否掉，很可能就是它。

## 上游怎么处理的（只借鉴结论，不抄代码）

- easyeda-agent PR #217（岳提、已合并 `887e4ba`）：7 块参考板 1814/1814 条底层丝印 `mirror=false`，
  bbclaw 板又有 10 条 `mirror=true`；自家 `silk-align` 写 `mirror=(side==bottom)`——**平台底层语义没定**，
  于是 bottom mirror **不判**，只判无歧义的两条（任一层 `reverse`、顶层 `mirror`）。
- 上游 `pcb_actual_render.go`：字形 x 方向只看 `mirror` 旗（`scale(sx -1)`，`sx = mirror ? -1 : 1`），
  **包络一律用宿主原生 bbox**（`getPrimitivesBBox`），没有原生包络就在图注写「范围随浏览器字体变化」。
- 结论：上游也没定标，靠「在线拿原生 bbox」绕过。我们在线档已有同款（172/174，`cli.py` `SILK_BBOX_ACTION`）；
  **缺的是离线档**——190S 用真机把规律量出来，再固化进离线模型。

## A. 真机定标（test 工程，`--project test` 路由，instance 不许硬编码）

1. 用 `pcb.place_component`（R1-1）在 test 的 PCB1 放**同一颗**两脚阻容封装：层 {TOP, BOTTOM} × 旋转 {0, 90, 180, 270} 共 8 颗；
   底层再各补一颗 `mirror` 取反的（若 `modify` 拒绝 mirror/layer，记下拒绝原文，不硬改）。
2. 每颗读两样：
   - 原生包络：`pcb.geometry --bboxIds <位号 ATTR id>`（**逐 id 一调**，宿主多 id 只答并集盒——174 的坑）；
   - 文件记录：`sys.get_project_file` 取 `.epro2` → `parse_epro2` → 该位号 `SilkText`（x/y/angle/mirror/reverse/origin/font_size/layer_kind）。
3. 判每颗的延伸方向：原生盒中心相对锚点落在 +u 侧还是 -u 侧；竖直方向（字身在基线哪侧）也记。
4. 出表（8+ 行）：层 × 角度 × mirror → 方向。**判据要能解释 6 块夹具板的统计**（实板A 29/29、毕设 0/3 两个极端必须对上；
   对不上说明还有别的变量——查 `reverse`、`origin`、编辑器版本——**不许拟合**，如实写进 evidence）。
5. 清理复原：删光放的器件，`componentCount` 回到放之前；截图/json 落 `outputs/190s/live/`。

## B. 离线口径落地（A 过了才做）

- `core/geometry.py::SilkText.corners()`：按 A 的表决定 u 方向符号（以及竖直方向，若测出差异）；docstring 写证据来源。
- `rules/pcb/silk.py`：底层位号估算盒随之改变。跑实板A：**「R22 压 EC3」要么消失，要么给出能对上实物的解释**，写进 evidence。
- `engines/canvasrender.py::_text_transform`：渲染与 `corners()` 同口径；实物从底面看是正字，底层视窗应读成正字——A 不支持就以 A 为准并在图注写明。
  189C 图注「读起来是正是反取决于文件怎么存」改成定标后的结论。
- 改了 `rules/**` → 重钉 `tests/test_126a_pcb_review_plumbing.py` recursive/direct 两指纹 + 台账注释。

## C. A 定不下来时（规律对不上夹具统计）

走上游的路：离线底层文字**不出 ERROR/WARN 级「压焊盘」结论**，降 INFO「底层文字包络方向未定标，需在线实测（pcb.geometry）」；
渲染图底层文字画 **+u/-u 双向虚线框** 标明不确定。这条路也要有测试钉住。

## D. 测试与纪律

- 新测试 `tests/test_190s_bottom_silk_direction.py`：用 A 表读数造合成 `SilkText` 断言 `corners()` 方向；
  实板A（`.tmp_bug98b/`，在场才跑）断言底层位号框靠近自家焊盘的比例符合 A 表预测。
- 变异：方向符号翻回去 → 新测试必须红（cp + sha256 还原）。
- 全量绿：`--basetemp=.tmp_pt_190s` `-n 4 --dist loadfile`；并行前场各用各的 basetemp。
- 红线：不动 git；不 `rm`（回收站）；企业项目名/型号零出现（只写「实板A」）；真机只碰 test/test2；禁地工程不碰。
- 证据 `outputs/190s/evidence.md`（A 表、夹具统计前后对照、R22 那条的去向）；PROGRESS.md append 一行；**不要 commit**。

## E. 同一次上机顺带做（发版上机闸欠账，189A2 遗留）

- 在 test 工程原理图落一颗「镜像 + 90°」的多脚器件（`sch.place_component`），`sch.component_pins` 回读逐脚坐标，
  与 `core/geometry.transform_point` 的期望逐脚对拍（验证 189A2 写侧 `engines/draw.py::editor_pose` 的取负）。对不上即停，回报原始读数。
- 清理复原；读数落 `outputs/190s/live/editor_pose.json`。
