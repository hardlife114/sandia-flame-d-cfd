# 非预混模型 headless 使能：第六轮探测结论

> 探测脚本：`scripts/dev/probe_np_{tree,tui,decide,scheme,species,dir,pp}.py`
> 日志：`run/probe_np_*.log`、`run/trn_np_*.txt`
> 日期：2026-09-14

---

## 一、结论（先说结果）

**无法无界面创建 `run/np_eq_seed.cas.h5`。原因是一个循环依赖，不是"懒"或"没找对命令"。**

```
要让模型 option = non-premixed-combustion
    → Fluent 立即校验燃料流分数（unity sum）
    → 燃料流分数为 0 → 校验失败 → 赋值回滚
要设置燃料流分数
    → 节点 setup/models/species/partially-premixed-model-options 等
    → 实测 get_state() 返回 "the object is not active"
    → 只有模型启用后才激活
```

GUI 的 Species 对话框把「选模型」和「填 Boundary 标签」放在**同一个事务**里，
点 OK 时才校验 —— 所以只有 GUI 能打破这个环。这正是项目 9/11 SLFM 那次卡住的同一个机制。

---

## 二、证据链（每一条都可复现）

### 2.1 `execute_tui` 从不抛异常 ⚠ 重要修正

上一轮（probe_np1..14）的"静默拒绝"结论**建立在假前提上**：
`execute_tui` 对无效命令**不抛异常**，Fluent 只在转录里打一行
`Error: invalid command` 就继续。关着转录跑，只会看到"没报错"，于是误判为"静默拒绝"。

验证（`run/trn_np_tui.txt`）：
```
/define/models/species/model           → Error: invalid command  Error Object: "model"
species.model = {'option': 'off', ...} ← 完全没变
```
**教训：任何以 `execute_tui` 做的探测，必须开转录并逐条读回显，不能只看有没有异常。**

### 2.2 真正的拦路石：unity-sum 校验

开转录后，TUI 命令的真实回显（`run/trn_np_decide.txt`）：
```
/define/models/species/non-premixed-combustion? yes
  Boundary Species...

Error: Fuel species sum to 0 (unity sum is required)
Error Object: #f
```
注意前面那行 `Boundary Species...` —— Fluent 已经在处理边界物种/流组分，然后发现燃料列全空。

### 2.3 API 赋值被"吞掉"（不是值写错）

`species.model.option` 的合法枚举**确实包含**目标值：
```
get_attr('allowed-values') = ['off', 'species-transport', 'non-premixed-combustion',
                              'premixed-combustion', 'partially-premixed-combustion',
                              'pdf-transport']
```
但赋值后 `get_state()` 不变、转录 0 新增行 → 校验失败被回滚，PyFluent 不报错。

### 2.4 物种补齐无效（排除"缺 CH4"假设）

材料库 `cortex/lib/propdb.scm` 里 `mixture-template` 默认只有 `h2o o2 n2`。
导入 CH4 两步机理后 → 新建材料 `new-import`（6 物种，含 ch4）。
**再次使能 NP → 仍然 `Fuel species sum to 0`** → 说明缺的不是物种，而是**分数**。

### 2.5 组分节点在模型启用前不可用（决定性的）

`dir()` 枚举 `setup.models.species` 暴露出的全部子节点：
```
model / options / reactions / species_transport_expert_options
partially_premixed_model_options / tfm_options / wall_surface_options
integration_parameters / turb_chem_interaction(_options) / edc_options
chemistry_solver / import_chemkin / water_corrosion_pre
```
而 `get_active_child_names()` 只返回：
```
['model', 'options', 'reactions', 'species_transport_expert_options']
```
其余（含 `partially_premixed_model_options`）全部
`RuntimeError: api-get-var: the object is not active`。
`setup` 下也没有任何 pdf/combust/stream 分支。

### 2.6 交互式 TUI 菜单在无界面下无法驱动

```
/define/models/species/pdf
  Select an available mixture material.
  (new-import mixture-template)
  Error: GENERAL-CAR-CDR: invalid argument [1]: improper list     ← 菜单选择列表构建失败
/define/models/species/pdf new-import   → 转录 0 新增行（输入被吞）
```
这个菜单依赖 GUI 侧的数据结构，headless 下拿不到。

---

## 三、给用户的最简 GUI 步骤（含两个易踩的坑）

1. 从 **Fluent Launcher** 启动（2D、双精度、12 核）—— 代理环境派生的 GUI 必闪退（dx11/opengl 均崩）
2. `File → Read → Case` → `run/np_eq_pregui.cas.h5`
3. `Define → Models → Species`：
   * Model 选 **Non-Premixed Combustion**
   * **Boundary 标签**：
     * ⚠ **坑 1**：默认边界物种表是 `ch4, h2, jet-a, n2, o2`，**没有 h2o**。
       而方案 A 的氧化剂流（湿空气）含 H2O 0.006256 → 需在 Boundary Species 框里
       输入 `h2o` 点 **Add**。
     * Species Unit 选 **Mass Fraction**
     * Fuel 列：CH4 = 0.15637、O2 = 0.19650、N2 = 0.64713
     * Oxid 列：O2 = 0.23574、N2 = 0.75800、H2O = 0.006256
     * Temperature：Fuel 294 K、Oxid 291 K
   * **Chemistry 标签**：State Relation = **Equilibrium**
   * **Table 标签**：确认非绝热（Non-Adiabatic）设置
   * 点 OK（此刻才做 unity-sum 校验）
4. `File → Write → Case` → 另存为 **`run/np_eq_seed.cas.h5`**
5. 之后看门进程会自动 12 核跑 `run_np_eq.py`

> ⚠ **坑 2**：`prep_np_pregui.py` **没有导入任何机理/热力学库**（已核实），
> 所以该 case 的 `mixture-template` 只有 `h2o o2 n2`。
> 若 GUI 里 Add `ch4` 失败，先在 `File → Read → Case` 后执行一次 Chemkin 机理导入
> （或用 `scripts/run_edm.py` 里同样的 `species.import_chemkin(...)`），
> 让材料含 `ch4 o2 n2 co2 h2o co`，再进 Species 面板。

---

## 四、我实际做成了什么 / 没做成什么

**做成**：
* 把"为什么必须 GUI"从"校验只能 GUI 过"的笼统说法，落实成**可复现的循环依赖证据**（§2.3–2.5）
* 修正了上一轮的**方法论错误**：`execute_tui` 不抛异常 → 所有 TUI 探测必须开转录（§2.1）
* 补齐了 API 合法枚举、隐藏节点清单、材料库结构等可复用情报
* 发现两个会让 GUI 步骤失败的隐患（边界物种缺 h2o；pregui case 无机理物种）§三

**没做成**：无法生成 `np_eq_seed.cas.h5`（headless 下被循环依赖卡死）。

**唯一可能的绕路**（未验证，成本高）：手工构造 .cas.h5 的 HDF5 设置段 ——
不建议，脆弱且易产生无效 case。
