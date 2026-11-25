# 最小调用示例：装置 + 技术路线（虚构数据，仅示意接口，不是正式案例结果）

## 输入

`input/case.json`

```json
{"case_id":"SYN-APP","mode":"apparatus_and_technical_route","output_contract":["case_id","status","editable_source","export_artifact","content_map","compliance_checks","exceptions"]}
```

`input/material.json`（`brief` 切出 P002–P006）

```json
{"title":"Synthetic loop reactor note","sections":[
{"heading":"Feed","text":"CO2 from the cylinder passes the flow controller (20 mL/min) into the reactor."},
{"heading":"Loop","text":"Gas leaving the reactor passes the condenser and is returned to the reactor by the pump. Condensate drains from the condenser to the trap."},
{"heading":"Detection","text":"A xenon lamp illuminates the reactor. A gas chromatograph samples the gas after the condenser."},
{"heading":"Route","text":"Load 50 mg catalyst, then purge for 30 min. Purging is repeated until O2 is below 0.1%."},
{"heading":"Runs","text":"The runs are then split into light (n = 3) and dark (n = 3), 4 h each. Gas is sampled at 4 h."}]}
```

`input/artifacts/figure-workorder.json`：`{"mode":"apparatus_and_technical_route","canvas_mm":[180,140]}`

## 工作文件（KIT_WORK 目录）

`spec.json`

```json
{"title":"Closed-loop reactor and test route","title_src":"P001",
 "canvas":{"size_mm":[180,140],"font_pt":8,"dpi":300},"layout":[["A"],["B"]],
 "panels":[{"id":"A","type":"diagram","title":"Apparatus"},{"id":"B","type":"diagram","title":"Route"}],
 "caption":"(A) Reactor loop. (B) Numbered route. Schematic, not to scale.",
 "footnotes":[{"text":"Schematic, not to scale.","src":"workorder"}],
 "unresolved":[{"item":"outlet of the gas chromatograph","state":"not reported","detail":"the source names the sampling point only","src":["P004"]}]}
```

`A.groups`

```
feed | Gas supply | - | P002
loop | Gas loop | - | P003
det | Detection | - | P004
```

`A.nodes`（每个节点都有 group）

```
cyl | CO_{2} cylinder | equipment | feed | P002 | - | stated | cylinder
mfc | Flow controller | equipment | feed | P002 | 20 mL/min | stated | valve
rx | Reactor | equipment | loop | P002,P003 | - | stated | vessel
cond | Condenser | equipment | loop | P003 | - | stated | column
pump | Pump | equipment | loop | P003 | - | stated | pump
trap | Trap | equipment | loop | P003 | - | stated | flask
lamp | Xe lamp | equipment | loop | P004 | - | stated | lens
gc | Gas chromatograph | instrument | det | P004 | - | stated | chart
```

`A.edges`（先把句子写成链，再逐段落边；不得越过中间单元）

```
# P002: cylinder > flow controller > reactor
cyl | mfc | gas | CO_{2} | stated | P002
mfc | rx | gas | - | stated | P002
# P003: reactor > condenser > pump > reactor; condenser > trap
rx | cond | gas | - | stated | P003
cond | pump | gas | - | stated | P003
pump | rx | return | recirculated | stated | P003
cond | trap | liquid | condensate | stated | P003
# P004
lamp | rx | energy | light | stated | P004
cond | gc | gas | sample | stated | P004
```

`B.groups`

```
prep | Preparation | - | P005
run | Run, 4 h | - | P006
```

`B.nodes`

```
s1 | Load catalyst | step | prep | P005 | 50 mg | stated | - | step=1
s2 | Purge | step | prep | P005 | 30 min | stated | - | step=2
d1 | O_{2} < 0.1%? | decision | prep | P005 | - | stated
s3 | Start run | step | run | P006 | 4 h | stated | - | step=3
s4a | Light | step | run | P006 | n = 3 | stated | - | step=4a
s4b | Dark | step | run | P006 | n = 3 | stated | - | step=4b
s5 | Sample gas | step | run | P006 | at 4 h | stated | - | step=5
```

`B.edges`

```
s1 | s2 | flow | - | stated | P005
s2 | d1 | flow | - | stated | P005
d1 | s2 | return | no: repeat | stated | P005
d1 | s3 | flow | yes | stated | P005
s3 | s4a | flow | - | stated | P006
s3 | s4b | flow | - | stated | P006
s4a | s5 | flow | - | stated | P006
s4b | s5 | flow | - | stated | P006
```

## 调用

```
export KIT_INPUT=./input KIT_WORK=./work KIT_OUTPUT=./out
python3 scripts/figkit.py brief
python3 scripts/figkit.py build
python3 scripts/figkit.py verify
```

编辑（把 Trap 改名为 Cold trap，其余不动）：先冻结 v1，再改 `A.nodes` 那一行，`spec.json` 加 `"edit_scope":["node-trap","A-edge-cond-liquid-trap","A-group-loop"]`：

```
python3 scripts/figkit.py build --revise "freeze layout"
rm -f out/figure_before_edit* out/edit_record.json work/layout_before_edit.json
# 修改 A.nodes 与 spec.json 后
python3 scripts/figkit.py build --revise "rename Trap to Cold trap, requested"
```

## 示意输出（形状，非成绩）

`build` 打印 `BUILT status=...`，随后是 ATTENTION（必须处理）和 NOTE（须回读原句）。本例中 Trap 与 Gas chromatograph 只有入口，会各有一条 flow continuity 提示：前者是原文写明的终点，后者记入 `unresolved`。`out/` 内含 `figure.svg/png/pdf`、`element_source_map.csv`（部件表与步骤表，含定位）、`edge_table.csv`、`result.json`；编辑后另有 `figure_before_edit.*` 与 `edit_record.json`。

## 图元规范与失败清单

| 内容 | 约定 |
|---|---|
| 液体 / 气体 / 物料 | 蓝实线 / 绿实线空心箭头 / 深蓝实线 |
| 能量 / 信号 / 控制 | 橙点划线 / 紫点线 / 黄褐点线 |
| 废料、回流 | 橄榄色虚线，标签写去向或终止条件 |
| 装配接口 | `assembly`，圆点端 |
| 常见失败 | 越过中间单元直连；同一容器两个名字画成两个；分组面板里有未分组节点（版面被拉宽、字变小）；`step=` 写在第 9 列之前（被当成别的字段）；固定版面放入过多节点；改线型颜色但图例未改 |
