# 学术 PPT 生成与编辑 · 使用与方法说明

**本 Skill 的重点**：按指令逐条编辑、未触碰页面逐字节一致、图表与文字同步、可回退。

## 1. 适用范围

输入是论文或研究材料、幻灯片工单（`artifacts/slide-workorder.json`）、目标模板，以及编辑/适配任务的起始稿。输出可编辑 PPTX、真实导出的 PDF、逐页预览、页级证据映射、变更记录和 `result.json`。不做论文写作、绘图设计和统计分析。

## 2. 调用方式

Agent 读取 `SKILL.md`，执行 `brief → show/find/table/slide → 写 deck.json 或 edits.json → build / adapt / edit → 看一次总览图 → verify`。人工使用：

```
KIT_INPUT=./input KIT_WORK=./work KIT_OUTPUT=./out python3 scripts/deckkit.py brief
```

`python3 scripts/deckkit.py selftest` 跑通 `examples/synthetic`（虚构数据，仅示意接口，不是正式案例结果），并自动做**反向测试**：故意改坏交付件（文本溢出、元素越界、空占位符、篡改图表数值），检查必须全部拦下才算通过。

## 3. 依赖与模板要求

Python 3.9+、python-pptx ≥ 0.6.22、lxml；Pillow 用于字宽与图片检查；LibreOffice 用于导出 PDF；poppler 用于核对导出件。模板为普通 PPTX，母版和版式任意命名：引擎按占位符类型和面积选版式，不依赖名称；模板自带示例页会被移除，母版、版式、主题不改动。

## 4. 方法要点

| 环节 | 做法 | 解决的问题 |
|---|---|---|
| 来源 | 材料切成带编号段落，逐页、逐条引用；页面上的数字逐个到来源中查找 | 数字搬运出错、引用张冠李戴 |
| 版式 | 按占位符结构选版式并写入真实占位符；页脚页码从版式克隆 | 看起来像模板，实际没有继承 |
| 排版 | 用真实字宽估行，先用模板字号，放不下再逐级缩小，到下限就报告而不是硬塞 | 文本溢出、字号被缩到看不清 |
| 原生对象 | 图表、表格、流程、关键数字均为可编辑原生对象；图表数值从保存后的文件读回，与源表比对 | 截图式图表无法修改 |
| 备注 | 备注与页面分离，用于过渡、强调、边界和追问 | 备注重复页面文字 |
| 适配 | 逐页迁移文字层级、表格、图表数据、图片、备注，再独立重读两份文件做零丢失审计 | 套模板时丢内容 |
| 编辑 | 按原页号逐条执行操作；未触碰页面 XML 哈希一致；保留操作日志 | 改一页、动全稿 |
| 兜底 | `brief` 就写出诚实的 partial 结果，一次命令完成全部交付件 | 超时交白卷 |

与通用 PPT 生成工具相比，新增的是：占位符级模板继承证明（母版、版式、主题哈希前后一致）、数字溯源、零丢失审计、未触碰页一致性证明。边界：不还原动画和 SmartArt；散点图迁移需人工复核；渲染字体缺失时 PDF 用替代字体并如实披露。

已知的弱模型失败方式与对策：单次回复超过 16384 token 会中止整个运行，所以规格可以分小文件、逐行追加；反复打磨会耗尽时间，所以引擎在重复无进展时明确叫停；材料内部矛盾容易漏记，所以先跑 `audit`。

### 编辑示例（虚构数据，仅示意接口，不是正式案例结果）

`SKILL.md` 中的 edits.json 以合成示例为底稿。复现：把 `examples/synthetic/deck.json` 第 1 页副标题改为含 24.3 的句子（造出与新值冲突的保护页），执行 `build`，把得到的 `presentation.pptx` 复制为 `input/artifacts/starting-deck.pptx`；另存一份数据表 `rev.csv`，把 60 min、INH-7 一行改为 26.1；工单写明 `"total_slides":7` 与 `"keep_unchanged":{"original_slide_numbers":[1,2]}`；依次执行 `brief`、`edit`、`verify`。SKILL 内的图表类别为节省篇幅只写了两点，实际须写全 0、10、30、60 四点；`...` 需换成真实内容。

示意输出（字段含义）：

| 位置 | 内容 |
|---|---|
| 终端 | `EDIT 已执行数 applied, 失败数 failed`；失败操作逐条给出原因；`LEAD` 为材料中查不到的数字，用于人工核对，不等于错误 |
| `edit_operations.json`、`change_record.operations` | 每条操作原样记录（含 `edit` 指令号、`before`、`reason`）；单元格与图表自动记录改前值 |
| `change_record.preservation` | `slides_xml_identical` 给出未改动页的原页号与新页号；`charts_before/after` 为图表改前改后数据 |
| `compliance_checks.untouched_slides_identical` | 未被任何操作点名的页以及工单保护页是否一致 |
| `exceptions` | `unresolved` 条目，例如被保护页仍写旧值 24.3 的冲突 |

编辑的边界：不支持改字体、字号、颜色、版式、切换动画；局部字体按 SKILL 中的片段生成 `base.pptx` 后再编辑，此时一致性检查以该 base 为参照，必须写入 `decisions`，重建时需把它放回 `KIT_WORK`。编辑模式不自动排时间，时间安排写入 `decisions`。`set_table` 改变行列数会重建表格并失去原表格样式。`replace_text` 不写 `slide` 会改动全部页面。回退：删去对应操作后重跑 `edit`，起始稿始终不变。

## 5. 输出说明

`presentation.pptx` · `presentation.pdf` · `contact_sheet.png` 与 `previews/` · `deck_spec.json` 或 `edits.json`（可重建）· `claim_source_map.csv` · `speaker_plan.md` · `change_record.json` · `rebuild/` · `result.json`。

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
| 编辑操作 failed | 按提示改形状编号、列名或原文后重跑；无法执行的指令写入 `unresolved`，该页保持原样 |
| 保护页被检查报告问题或与新值矛盾 | 不改该页，写入 `unresolved` 并列出两个值 |
| 数字查不到出处 | 改引用或改数字；计算值写明公式 |
| 占位符不足、字体缺失、图无法提取 | 用最接近的版式并记录偏差；不改母版、不补造图 |
| 页数超限 | 合并或移到备用页，并写入 `decisions` |
| PDF 加密、文件损坏 | 记入 `unresolved`，状态 partial |

## 9. 复用与维护

引擎、规格格式、证据映射表、合成示例均可单独复用（MIT）。新增版式偏好在 `choose_layout` 加打分项；新增编辑操作在 `cmd_edit` 加分支并补日志。修改后先跑 `selftest`。
