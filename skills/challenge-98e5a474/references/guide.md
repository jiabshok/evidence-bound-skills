# 科研示意图生成与编辑 · 使用与方法说明

**本 Skill 的重点**：实体—关系—层级的可核对表达，以及只改指定元素的编辑。

## 1. 适用范围

输入是论文、实验记录、数据表或已有 SVG，加一份绘图工单（`artifacts/figure-workorder.json`）。输出可编辑 SVG、300 dpi PNG、单页 PDF、逐元素来源表、编辑记录和 `result.json`。不做统计分析、实验设计和论文写作；不从图像像素反推精确数值。

## 2. 调用方式

Agent 读取 `SKILL.md`，依次执行 `brief → show/find/table → 写 spec.json 与 A.groups/A.nodes/A.edges → build → 看一次预览图 → build --revise 或 edit → verify`。人工使用时设置三个环境变量即可脱离评测环境：

```
KIT_INPUT=./input KIT_WORK=./work KIT_OUTPUT=./out python3 scripts/figkit.py brief
```

`python3 scripts/figkit.py selftest` 跑通 `examples/synthetic`（虚构数据，仅示意接口，不是正式案例结果），并自动做**反向测试**：故意改坏交付件（移动数据点、删除数据点、拉长误差线、翻转抑制/激活、反转方向），检查必须全部拦下才算通过。

## 3. 依赖

Python 3.9+ 标准库即可生成 SVG 和 `result.json`。Pillow 用于真实字宽和像素检查。导出按顺序尝试 Playwright Chromium、CairoSVG、rsvg-convert、Inkscape、LibreOffice，任一可用即可，失败原因写入 `exceptions`。`pdftotext/pdfinfo/pdffonts`（poppler）用于读 PDF 和核对导出件。图标与配色为本项目自绘；色板取自 Okabe–Ito 公开色盲安全色。

## 4. 方法要点

| 环节 | 做法 | 解决的问题 |
|---|---|---|
| 来源 | 输入切成带编号段落 `P###`，规格里逐元素引用；引文逐字核对 | 箭头、数字说不清来自哪里 |
| 语义 | 30 类节点、26 类关系各有固定形状、线型、端点；未证实关系自动虚线 | 激活/抑制/关联混用同一种箭头 |
| 布局 | 确定性分层布局、正交避障布线、标签避让；同一规格结果一致 | 每次版式不同、线穿过节点 |
| 图表 | 每个图元带 `文件#行号`，坐标系参数写入 SVG | 图与数据对不上 |
| 回读 | 从导出的 SVG 几何反算数值，与源表逐点比对；从 SVG 重新解析节点和边，与规格做集合比对 | 检查器只检查自己记的账 |
| 编辑 | 修改前后按 id 逐元素比对，其余元素逐字节一致；支持对外来 SVG 做局部补丁 | 改一处、动全身 |
| 兜底 | `brief` 就写出诚实的 partial 结果，`build` 一次完成全部交付件 | 超时交白卷 |

与通用绘图代码（matplotlib、Graphviz、直接手写 SVG）相比，新增的是：逐元素来源、几何反算校验、语义端点约束、保源编辑记录。边界：编辑保源的前提是页面尺寸不变（见第 10 节）。布局器面向 6–25 个节点的科研示意图，超大网络请用专用网络软件；不画写实插画。

已知的弱模型失败方式与对策：单次回复超过 16384 token 会中止整个运行，所以规格可以分小文件、逐行追加；反复打磨会耗尽时间，所以引擎在重复无进展时明确叫停；材料内部矛盾容易漏记，所以先跑 `audit`。

## 5. 输出说明

`figure.svg`（分层、文字可编辑、稳定 id）· `figure.png` · `figure.pdf` · `figure_grayscale_preview.png` · `figure_spec.json`（可重建）· `element_source_map.csv` · `figure_caption.md` · `figure_before_edit.*` 与 `edit_record.json`（有编辑时）· `rebuild/`（引擎副本）· `result.json`。

`result.json`：`content_map` 每个元素的含义与来源；`compliance_checks` 每项检查的结果、证据和方法；`exceptions` 冲突、缺失、未通过项；`provenance` 输入哈希与版本。

## 6. 复核方法（不依赖本引擎的自述）

1. `sha256sum` 比对 `result.json` 里的文件哈希。
2. 用 `rebuild_command` 从规格重建，比对输出。
3. 随机抽 `element_source_map.csv` 若干行，回到原材料对应位置核对引文。
4. 跑 `selftest` 看反向测试。

## 7. 自查表

must-show 是否都在图上；每个箭头能否指到一句原文；单位、n、误差含义是否写清；虚线是否只用于未证实关系；`exceptions` 是否说清缺什么；`verify` 是否 OK。

## 8. 失败处理

| 现象 | 处理 |
|---|---|
| 规格报错 | 不覆盖已有结果，按提示修改条目 |
| 数字查不到出处 | 改引用或改数字；计算值写明公式 |
| 字体未嵌入、文字未导出为文本 | `pdf_export` 会列出；换掉特殊符号一次，仍有则如实留在 `exceptions` |
| 无工单文件 | 以 `task.md`、`case.json` 为要求，来源写 `task` |
| 描述与数据/图例矛盾 | 用数据表值，两个值及段落记入 `unresolved` |
| 需人工判断的科学问题 | `unresolved`，state 写 `needs human confirmation` |
| 标签/节点冲突 | 缩短标签、改方向、拆面板 |
| 数据缺失或列含义不明 | 不补值，记入 `unresolved` |
| 导出器不可用 | 保留 SVG 与 partial 状态，写明原因 |

## 9. 复用与维护

引擎版本 1.10.0（`figkit.py` 的 `VERSION`，写入 `result.json.provenance`）。
引擎、规格格式、图标集、合成示例均可单独复用（MIT）。新增节点或关系类型在 `fk_draw.py` 的 `KINDS`/`EDGES` 各加一行即可；新增图表类型在 `fk_chart.py` 实现绘制，并在 `read_back` 补对应的反算。修改后先跑 `selftest`。

## 10. 最小示例：表格全部连边 → 删边编辑（虚构数据，仅示意接口）

输入（虚构 `links.csv`，3 行）：

```
from,to,estimate,p
A,B,0.42,0.010
B,C,-0.31,0.080
A,C,0.12,0.450
```

工单要求“p<0.1 的连边全部画出，线宽表示估计值”。N=3，入选 2 行，第 3 行进 `omitted`。

`A.nodes`（8 列，空列写 `-`，附加字段放在第 8 列之后）：

```
A | Variable A | concept | - | links.csv#1 | - | stated | - | rank=1
B | Variable B | concept | - | links.csv#1 | - | stated | - | rank=2
C | Variable C | concept | - | links.csv#2 | - | stated | - | rank=3
```

`A.edges`（7 列，附加字段放在第 7 列之后；减号用 ASCII `-`）：

```
A | B | path | 0.42 | stated | links.csv#1 | row 1 | value=0.42
B | C | path | -0.31 | stated | links.csv#2 | row 2 | value=-0.31 | dash=dashed
```

`spec.json`（只列本例要点）：

```json
{"title":"Fitted links among three variables (example)","title_src":"workorder","canvas":{"width_mm":180},
 "panels":[{"id":"A","type":"diagram","title":"Fitted links","direction":"LR","src":"links.csv",
            "edge_width":{"field":"value","label":"|estimate|","max":0.42}}],
 "legend_extra":[{"text":"p < 0.05","dash":"solid"},{"text":"0.05 < p < 0.1","dash":"dashed"}],
 "caption":"Example only. Line width: |estimate|; colour: sign; associations, not causes. Not to scale.",
 "omitted":[{"item":"A-C (row 3)","reason":"p = 0.450, outside the inclusion rule"}],
 "decisions":["3 rows read, 2 drawn, 1 omitted by p < 0.1"]}
```

步骤：`build` → 计数命令列出 2 条边，2+1=N → 按 `BUILT` 打印的 W×H 写 `"size_mm":[W,H+15]` 再 `build` 一次 → 加 `"edit_scope":["A-edge-B-path-C","A-edges","A-edge-labels"]`，追加 `B | C | path | delete` → `build --revise "remove B-C (E1)"` → `verify`。

预期形态：`edit_record.json` 的 `removed` 为 `A-edge-B-path-C` 及其标签，其余节点和连边逐字节一致，`page_coordinate_system` 为 identical；`figure_before_edit.*` 与 `figure.*` 并存。

要点：改标签要先 `delete` 再写新行；`delete` 的类型必须与原行一致；`--revise` 之后不要再用不带 `--revise` 的 `build`；`edge_width.max` 固定后，删掉最强的边不会改变其余线宽。

## 11. 图标（glyph）全表

cell bacteria virus dna protein antibody mouse human group brain heart lung plant leaf beaker flask tube dish syringe pill microscope laser lens mirror detector camera furnace heater pump valve cylinder vessel column electrode battery chip computer database document network chart curve gear clock thermometer magnet wave crystal molecule droplet globe satellite robot check question target warning

## 1.8 版新增命令（图类通用）

| 命令 | 作用 |
|---|---|
| `start pathway/apparatus/schematic/abstract` | 索引材料、按工单起草 spec（画布、面板、分组），并给出第 1 条要求及其最相关段落 |
| `next` | 逐条走查要求：每次只给一条要求和对应段落，避免一次性规划整张图；最后追加“仅被提出或引自他人”的关系 |
| `fromtable "Table 2" --where "p<0.1" --dash "p>=0.05"` | 把结果表逐行变成关系（数值、符号、p、行级来源），不经人工转抄 |
| `prune "p>=0.05" --title "..."` | 按条件删除关系并以灰色插页列出，自动写好编辑范围 |
| `set title/caption/subtitle/unresolved/omitted/decision` | 不改 JSON 即可补元数据 |
| `review` | 论断与引文逐条并排；列出图面缺失的要求词、要求段落中未出现的数值 |
| `audit` | 材料一致性扫描：畸形数字、同值不同单位、百分比与计数不符、表文 p 值不一致 |

面板类型新增 `timeline`（按时间刻度绘制的日程）；文本条目支持 `key`、`label:名称`、`box:标题`、`ns`、`grid`（交叉设计方格图）。
