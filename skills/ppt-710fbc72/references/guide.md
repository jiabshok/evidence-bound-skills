# 学术 PPT 模板与格式适配 · 使用与方法说明

**本 Skill 的重点**：真实继承母版版式、内容零丢失审计、批量一致性、导出复核。

## 1. 适用范围

输入是论文或研究材料、幻灯片工单（`artifacts/slide-workorder.json`）、目标模板，以及编辑/适配任务的起始稿。输出可编辑 PPTX、真实导出的 PDF、逐页预览、页级证据映射、变更记录和 `result.json`。不做论文写作、绘图设计和统计分析。

## 2. 调用方式

Agent 读取 `SKILL.md`。适配任务：`brief → adapt → audit/show/find 核对 → （需要时）overrides.json → adapt → 看一次总览图 → verify`；没有起始稿用 `deck.json + build`；只改个别内容用 `edits.json + edit`。人工使用：

```
KIT_INPUT=./input KIT_WORK=./work KIT_OUTPUT=./out python3 scripts/deckkit.py brief
```

`python3 scripts/deckkit.py selftest` 跑通 `examples/synthetic`（虚构数据，仅示意接口，不是正式案例结果），并自动做**反向测试**：故意改坏交付件（文本溢出、元素越界、空占位符、篡改图表数值），检查必须全部拦下才算通过。

`overrides.json` 参数（数字键是起始稿原页号；写了哪个键就整体替换哪一部分）：

| 键 | 含义 |
|---|---|
| `title` / `notes` | 新标题 / 完整备注（含原备注） |
| `bullets` | 完整正文列表，元素必须是 `{"text","level"}` 对象 |
| `layout` | 模板版式的准确名称；写错会被忽略并自动选版式 |
| `visual_side` | `right` 或 `bottom`，图文同页时图表位置 |
| `src` | 段落编号；会在页面上印出来源行 |
| `unhide` | `true` 取消隐藏，仅在工单要求时 |
| 顶层 `footer` `unresolved` `decisions` `omitted` | 页脚、分歧清单、处理决定、移出内容 |

LEAD（起始稿里有、材料中查不到的数字）只是线索：先核对；四舍五入、换算、由源值计算得到的保留；其余列为分歧，页面不改。

## 3. 依赖与模板要求

Python 3.9+、python-pptx ≥ 0.6.22、lxml；Pillow 用于字宽与图片检查；LibreOffice 用于导出 PDF；poppler 用于核对导出件。模板为普通 PPTX，母版和版式任意命名：引擎按占位符类型和面积选版式，不依赖名称；模板自带示例页会被移除，母版、版式、主题不改动。文件名含 `template` 的 PPTX 视为模板，含 `starting` / `start-deck` / `source-deck` / `original` / `existing` 的视为起始稿。建议模板至少有封面、标题与正文、双栏、仅标题四类版式。字体沿用模板主题字体；PPTX 中不替换，PDF 因本机缺字体而替换时写入 `exceptions`。PDF 由 LibreOffice 按默认设置从保存后的 PPTX 导出，隐藏页不导出。

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

## 5. 输出说明

`presentation.pptx` · `presentation.pdf` · `contact_sheet.png` 与 `previews/` · `deck_spec.json` 或 `edits.json`（可重建）· `claim_source_map.csv` · `speaker_plan.md` · `change_record.json` · `rebuild/` · `result.json`。

逐页适配记录（整稿 `adapt` 之后运行；`SKILL.md` 的 Last step 会调用，生成 `adaptation_log.csv`；`unchanged_content` 只覆盖文字与表格，图表、图片、备注见 `change_record.json`）：

```python
#adapt-log
import json,csv
from pptx import Presentation as X
O="/app/output/"; r=json.load(open(O+"result.json")); c=r["change_record"]; p=c["preservation"]; m={x["slide"]:x for x in r["slide_audit"]}
D=json.load(open(O+"deck_spec.json"))["slides"]; A=X(c["starting_point"]["path"]).slides
with open(O+"adaptation_log.csv","w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f); w.writerow("slide,old_layout,new_layout,media,font_or_layout_notes,text_not_verbatim,unchanged_content".split(","))
    for n,(a,s) in enumerate(zip(A,D),1):
        lost=[t["text"] for t in p["text_items_not_verbatim_in_final"] if t["slide"]==n]
        w.writerow([n,a.slide_layout.name,m[n]["layout"],"+".join(s["media"]),"; ".join(str(e.get("detail")) for e in r["exceptions"] if str(e["item"]).startswith("slide %d "%n)),lost,not lost and n not in p["tables_changed_on_slides"]])
#end
```

## 6. 复核方法（不依赖本引擎的自述）

1. `sha256sum` 比对 `result.json` 里的文件哈希。
2. 用 `rebuild_command` 重建并比对内容；用过 overrides 时需保留 `/app/output/_work/overrides.json`；先 adapt 后 edit 的稿件要在同一输出目录依次运行两条命令。
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
| 占位符不足、字体缺失、图无法提取 | 用最接近的版式并记录偏差；不改母版、不补造图 |
| 页数超限 | 合并或移到备用页，并写入 `decisions` |
| PDF 加密、文件损坏 | 记入 `unresolved`，状态 partial |
| overrides.json 报错（Traceback） | 检查 JSON 和 bullets 对象格式；上一次结果仍在；仍失败则不带 overrides 运行并记录 |
| 有意缩短文字后 `content_preservation` 未过 | 属预期，状态 partial，在 `decisions` 说明 |
| 页数或顺序要变 | adapt 之后用 `edit` + `"continue":true`，`add_slide` 放在 `delete_slide` 之前 |

## 9. 复用与维护

引擎、规格格式、证据映射表、合成示例均可单独复用（MIT）。新增版式偏好在 `choose_layout` 加打分项；新增编辑操作在 `cmd_edit` 加分支并补日志。修改后先跑 `selftest`。
