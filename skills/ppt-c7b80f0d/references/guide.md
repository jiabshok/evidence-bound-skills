# 论文转学术 PPT · 使用与方法说明

**本 Skill 的重点**：主线抽取、页级主张、图表定位、讲解备注分离、模板占位符真实继承。

## 1. 适用范围

输入是论文或研究材料、幻灯片工单（`artifacts/slide-workorder.json`）、目标模板，以及编辑/适配任务的起始稿。来源可以是 JSON、TXT/MD/XML/HTML、CSV/XLSX 或带文字层的 PDF（不做 OCR）。输出可编辑 PPTX、真实导出的 PDF、逐页预览、页级证据映射、变更记录和 `result.json`。不做论文写作、绘图设计和统计分析。

## 2. 调用方式

Agent 读取 `SKILL.md`，执行 `brief → show/find/table/slide → 写 deck.json 或 edits.json → build / adapt / edit → 看一次总览图 → verify`。人工使用：

```
KIT_INPUT=./input KIT_WORK=./work KIT_OUTPUT=./out python3 scripts/deckkit.py brief
```

`python3 scripts/deckkit.py selftest` 跑通 `examples/synthetic`（虚构数据，仅示意接口，不是正式案例结果），并自动做**反向测试**：故意改坏交付件（文本溢出、元素越界、空占位符、篡改图表数值），检查必须全部拦下才算通过。

### 最小调用示例（虚构数据，仅示意接口）

输入 `examples/synthetic/input`：`case.json`、`material.json`（段落编号为 P001…）、`artifacts/response.csv`、`artifacts/slide-workorder.json`（5 页、6 分钟）；模板由 `selftest` 临时生成。规格见 `examples/synthetic/deck.json`，其中一页为：

```json
{"kind":"content","role":"limits","title":"The feedback onto RX is proposed, not tested",
 "bullets":[{"text":"Authors propose that GLA may suppress RX","src":"P003"}],
 "notes":"Close by asking which control would test the feedback first.","minutes":1,"src":["P003"]}
```

调用：`python3 scripts/deckkit.py selftest`（依次执行 brief、build、verify）。示意输出为 `result.json` 的 `content_map` 一行：

```json
{"slide":5,"role":"limits","claim":"The feedback onto RX is proposed, not tested","layout":"模板中的版式名",
 "source":[{"id":"P003","file":"material.json","locator":"段落位置","quote":"原文短引"}],"notes_present":true}
```

## 3. 依赖与模板要求

Python 3.9+、python-pptx ≥ 0.6.22、lxml；Pillow 用于字宽与图片检查；LibreOffice 用于导出 PDF；poppler 用于核对导出件。模板为普通 PPTX，母版和版式任意命名：引擎主要按占位符类型和面积选版式，版式名称只作辅助；文件名需含 template（`.pptx`，不支持 `.potx`）；模板自带示例页会被移除，母版、版式、主题不改动。

## 4. 方法要点

| 环节 | 做法 | 解决的问题 |
|---|---|---|
| 来源 | 材料切成带编号段落，逐页、逐条引用；标题、要点、结论条、关键数字、手填表格和图表中的数字逐个到来源中查找（0–3 的小整数、副标题、流程步骤、图注和备注不自动查，需人工核对） | 数字搬运出错、引用张冠李戴 |
| 版式 | 按占位符结构选版式并写入真实占位符；页脚页码从版式克隆 | 看起来像模板，实际没有继承 |
| 排版 | 用真实字宽估行，先用模板字号，放不下再逐级缩小，到下限就报告而不是硬塞 | 文本溢出、字号被缩到看不清 |
| 原生对象 | 图表、表格、流程、关键数字均为可编辑原生对象；取自数据文件的柱/线/饼图数值从保存后的文件读回，与源表比对；手填图表核对数值是否出现在所引段落 | 截图式图表无法修改 |
| 备注 | 备注与页面分离，用于过渡、强调、边界和追问 | 备注重复页面文字 |
| 适配 | 逐页迁移文字层级、表格、图表数据、图片、备注，再独立重读两份文件做零丢失审计 | 套模板时丢内容 |
| 编辑 | 按原页号逐条执行操作；未触碰页面 XML 哈希一致；保留操作日志 | 改一页、动全稿 |
| 兜底 | `brief` 就写出诚实的 partial 结果，一次命令完成全部交付件 | 超时交白卷 |

与通用 PPT 生成工具相比，新增的是：占位符级模板继承证明（母版、版式、主题哈希前后一致）、数字溯源、零丢失审计、未触碰页一致性证明。边界：不还原动画和 SmartArt；散点图迁移需人工复核；图表不画误差棒，误差须写在表格或要点中；每页只放一个主视觉对象；渲染字体缺失时 PDF 用替代字体并如实披露。

已知的弱模型失败方式与对策：单次回复超过 16384 token 会中止整个运行，所以规格可以拆成 `deck.json` 加 `slides_2.json`…`slides_9.json`，构建时按文件名顺序合并；反复打磨会耗尽时间，所以引擎在重复无进展时明确叫停；材料内部矛盾容易漏记，所以先跑 `audit`。

## 5. 输出说明

| 必交内容 | 文件 | `result.json` 字段 |
|---|---|---|
| 可编辑演示文件 | `presentation.pptx`、`deck_spec.json`、`speaker_plan.md` | `case_id`、`status`、`editable_source`、`narrative`、`time_plan` |
| 页级证据映射 | `claim_source_map.csv` | `content_map`（逐页、逐条：来源编号、文件、位置、引文）；不确定性在 `exceptions` |
| 渲染与版本记录 | `presentation.pdf`、`previews/`、`change_record.json`、`rebuild/` | `export_artifact`（渲染器版本、主题字体）、`compliance_checks`（PDF 实际字体、模板哈希一致）、`provenance`（输入哈希、引擎版本） |

全部文件：`presentation.pptx` · `presentation.pdf` · `contact_sheet.png` 与 `previews/` · `deck_spec.json` 或 `edits.json`（可重建）· `claim_source_map.csv` · `speaker_plan.md` · `change_record.json` · `rebuild/` · `result.json`。

## 6. 复核方法（不依赖本引擎的自述）

1. `sha256sum` 比对 `result.json` 里的文件哈希。
2. 用 `rebuild_command` 从规格重建，比对输出。
3. 随机抽 `claim_source_map.csv` 若干行，回到原材料对应位置核对引文。
4. 跑 `selftest` 看反向测试。

## 7. 自查表

页数是否与工单一致；每页标题是否是一句主张；数字是否带单位与 n；结论强度是否与来源一致；备注是否不重复页面；`exceptions` 是否写明冲突和缺失；`verify` 是否 OK。

## 8. 失败处理

| 现象 | 处理 |
|---|---|
| 规格报错 | 不覆盖已有结果，按提示修改条目 |
| 文本、表格放不下 | 精简、拆页、移到备注，不硬缩 |
| 数字查不到出处 | 改引用或改数字；计算值写明公式 |
| 占位符不足、字体缺失 | 用最接近的版式并记录偏差；PPTX 保留主题字体，PDF 用替代字体并披露；不改母版 |
| 图未单独提供或无法提取 | 先从论文 PDF 裁图（`pdftoppm`），仍不行则记入 `unresolved`，只用文字或表格给出的数值；不凭眼睛重画 |
| 公式为图片 | 裁图引用或只标「Eq. N，第 X 页」并记录；不凭记忆重写 |
| 页数超限 | 合并或移到备用页，并写入 `decisions` |
| PDF 加密、扫描件、文件损坏 | 引擎读不到文字时不会中断，也不会自动降级：不破解密码，用可读材料制作，缺口记入 `unresolved` 和限制页，并按 SKILL.md 的命令把状态改为 partial |

## 9. 复用与维护

引擎版本 1.9.0（`deckkit.py` 中 `VERSION`）。引擎、规格格式、证据映射表、合成示例均可单独复用（MIT）。新增版式偏好在 `choose_layout` 加打分项；新增编辑操作在 `cmd_edit` 加分支并补日志。修改后先跑 `selftest`。
