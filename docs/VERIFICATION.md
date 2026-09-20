# 接手核查记录（Verification Log）

本文件记录 **2026-09-11 接手后** 的所有实测结论，每条都注明证据文件。
与 `report.md` 配合阅读；`report.md` 是交付报告，本文件是原始核查台账。

---

## 1. 原始交付内容复核

| 复核项 | 结论 | 证据 |
|---|---|---|
| medium 网格 58 934 单元 / 59 466 节点 / 118 399 面 | ✅ 一致 | `run/check_med.out` |
| medium 总体积 1.055334e-01 m³（πR²L 偏差 0.013 %） | ✅ 复算一致 | `run/check_med.out` L70–78 |
| 域范围 x∈[0, 0.72] m、y∈[0, 0.216] m | ✅ 一致 | `run/check_med.out` L71–72 |
| coarse 网格 26 892 单元 / 27 250 节点 / 54 141 面 | ✅ 一致 | `run/trn_edc2.txt`（Fluent 读入回显） |
| 入流组分归一（jet 1.000000 / pilot 0.999976 / coflow 0.999996） | ✅ 一致 | `results/inlet_composition.csv` + 独立复算 |
| `decks/run_flamed.bat` 的 ROOT 写死旧路径 | ⚠️ 已修 | 改为 `%~dp0..` |

### 1.1 混合物分数独立核算（新做，`scripts/check_mixfrac.py`）

| 量 | 本核算 | 文档 | 偏差 |
|---|---|---|---|
| Z_st（化学计量混合物分数） | **0.352** | 0.351 | +0.001 |
| pilot Z | **0.272** | 0.270 | +0.002 |
| jet Z | 1.000 | 1（定义） | — |
| coflow Z（干空气） | 0.000 | 0（定义） | — |

结论：**两流（fuel = 射流, oxidizer = 干空气）的火焰面/PDF 口径即可覆盖 pilot 的组分状态**，
不需要三流模型。（pilot 温度仍由模型决定，见 report §11.3。）

---

## 2. SLFM 火焰面库：确认 2D headless 无入口

逐条排除，均有日志：

| 尝试 | 结果 | 证据 |
|---|---|---|
| 设置树 `models.species.partially_premixed_model_options` | 非预混/部分预混下 `boundary`/`flamelet`/`control` 均 **inactive** | `run/probe_ppo.log` |
| TUI `non-premixed-combustion/fuel-species`、`oxid-species` | 无法赋值；进菜单即报 `Fuel species sum to 0 (unity sum is required)` | `run/trn_*.txt` |
| Scheme `prepdf/bc`（RP 变量） | `rpsetvar` + `quote` 形式**可写且回读成功**，但校验仍失败 | `run/probe_bchyp.log`、`run/probe_fuelsp.log` |
| Scheme `%calc-flamelet` / `%calc-pdf-table` | C 层 primitive，**调用即 SIGSEGV**（无参 → `too few arguments(0)`；带参 → 进程崩） | `run/probe_prim.log` |
| GUI-only 符号（`pdf-fuel`/`pdf-oxid`/`pdf-flamelet-parameters`…） | 在 solver scheme 里**全部 unbound**（只存在于 cortex GUI 的 oblist） | `run/probe_pdfsym.log` |

**关键结构记录（`prepdf/bc` 默认值）**
```
[[300, 300, 300], (True,), [[o2, 0, 0.233, 0], [n2, 0, 0.767, 0]]]
   ↑三股流温度       ↑标志      ↑[组分, idx, 氧化剂列, 未用列]
```
即默认只填了氧化剂列，燃料列全 0 → 与报错完全吻合。

**结论**：Fluent 2025 R2 的 SLFM「Create Flamelet Library」只有 GUI 实现。
→ 按用户指示改走 **EDC**。

---

## 3. EDC 路线实测

### 3.1 走通的

| 项 | 结果 |
|---|---|
| EDC 启用 | `turb_chem_interaction` 允许值实测：`finite-rate/no-tci` / `finite-rate/eddy-dissipation` / `eddy-dissipation` / `eddy-dissipation-concept` |
| 前置条件 | **必须先开 `volumetric-reactions`**，否则 `turb_chem_interaction` inactive |
| 化学求解器 | `true stiff-solver` ✅（内置刚性 ODE，不走 CHEMKIN） |
| ISAT | `method=isat`、`error_tolerance=1e-3`、`table_size=200` 均可设 |
| S1 冷流 | 收敛，continuity 3.2e-1 → 2.5e-2 |
| S2 能量+多组分扩散 | energy 残差 → 1.0e-7 |
| S5 反应流 150 步 | 跑完，808 s |

### 3.2 踩到的坑（全部已修进脚本）

| # | 坑 | 现象 | 正确做法 |
|---|---|---|---|
| 1 | `chemkin-cfd-solver` | 打印 `CHEMKIN features will be unavailable (see chem.out)`（chem.out 为 0 字节），随后 Cortex SIGSEGV 或挂起 | 用 `stiff-solver` |
| 2 | 设置树访问时机 | 读网格前 `settings.setup.models` 整体 inactive，`__getattribute__` 抛 `InactiveObjectError` | 访问器写成惰性 property |
| 3 | Fluent 枚举用**显示名** | 写 kebab-case 报 `Value is not allowed` 并提示最接近显示名 | `"Intensity and Hydraulic Diameter"`、`"Temperature"`、`"eddy-dissipation-concept"` |
| 4 | GRI 3.0 组分名大小写 | `species_mass_fraction["CH4"]` 报 no attribute | 键用小写 `ch4`/`o2`/`n2` |
| 5 | 壁面处理路径 | `v.near_wall_treatment = "..."` 报 `ASSQ: invalid argument` | `v.near_wall_treatment.wall_treatment = "enhanced-wall-treatment"` |
| 6 | field_data API | `s.fields.field_data.get_fields` **不存在** | 用 `get_scalar_field_data(field_name=..., surfaces=[...], node_value=True)` |
| 7 | line surface | 直接 `s.tui.surface.line_surface(...)` 无效 → ASCII 导出 y 坐标**恒为 0** | `line_surface` 是 TUIMenu，必须 `.create(...)` |
| 8 | `svarlist-value` / `%get-max-value` | 本环境 unbound，取不到场极值 | 用 `get_scalar_field_data` 读边界 |
| 9 | patch 点火 | TUI `/solve/initialize/patch ...` 报 `invalid command "patch"`；设置树 `initialization.patch` inactive | 见 §4 |

### 3.3 并行化学死锁

- 现象：卡在第 327 步；**20 s 间隔两次采样，所有 compute 进程 CPU 计数完全不变**
  （如 pid 101628 两次均为 `1263.484375`），transcript 5 分钟无新增。
- 该步耗时从正常 ~80 s 异常升至 1:23。
- 判定：**真死锁**（非慢），已手动终止全部 Fluent 进程。
- 注：`run/fluent-0-error.log` 中 `Fatal signal raised sig = Segmentation fault`
  的栈（`Build_Grid`/`CX_Primitive_Error`）时间戳为 **18:40:41**，属早先另一次运行的旧记录。

---

## 4. 点火未生效 → 结果其实没烧

`scripts/probe_read.py` 读 `run/edc2_coarse_react.dat.h5`：

| 位置 | 温度 |
|---|---|
| 出口 `pressure-outlet-9` | **297.3 – 298.3 K** |
| 径向外边界 `pressure-outlet-10` | 295.4 – 300.0 K |
| 轴 `axis-8` | 294.0 – 419.8 K |
| `velocity-inlet-6`（pilot） | 1136.9 – **1880.0 K** ← 入口给定值，非燃烧 |

出口组分：`ch4` 5.5e-4~8.8e-4、`o2` 0.114~0.184、`co2` 7.8e-5~1.3e-4、`oh` ~5e-10
→ **痕量/稀释量级，无燃烧产物**。

> **判据勘误**：早先脚本以「全场最高温 > 1500 K」判定有燃烧，会把 pilot 入口的
> 1880 K 误判为火焰温度。**正确判据必须排除入口**，看内部/出口温度与 CO₂/H₂O 生成量。

**根因**：初始场为冷态，点火 patch 未生效；EDC 在 294 K 的 CH₄/空气混合区不自燃，
pilot 的 1880 K 是被冷射流+冷伴流夹住的薄环，热量被对流带走。

**下一轮方案**（已写入 `scripts/ignite.py`）：
1. 先用 `eddy-dissipation`（非刚性，迭代便宜）把高温区做出来 → 切 EDC 续算
2. 点火通道穷举：scheme `%patch`/`%patch-field`/`apply-patch`、TUI patch 多种写法、
   `standard-initialize` 带温度

---

## 5. TNF 实验数据（已取得并核查）

### 5.1 下载
`refs/tnf/`：`pmCDEF.zip`(8.05 MB)、`TUD_LDV_DEF.zip`(28 KB)、`LongRecordsFlameD.zip`(3.67 MB)

### 5.2 核查结论（`scripts/qc_tnf.py` → `results/tnf_qc.txt`）

| 项 | 结果 |
|---|---|
| 覆盖火焰 | C / D / E / F 四组 |
| Flame D 行数 | 164（Yave）+ 164（Yfav）= 328 |
| 中心线温度峰值 | **1957 K @ x/d = 45**（文档 L_stoic/d = 47 ✅） |
| 中心线温度序列 | 5d:298 → 15d:504 → 30d:1357 → 45d:1957 → 60d:1629 → 80d:1113 K |
| 径向峰值 | x/d=1:1893 K、x/d=2:1953 K、x/d=3:1937 K、x/d=30:1716 K |
| 混合物分数 F 范围 | 0.0000 – 1.0143（>1 为脉动噪点） |

### 5.3 ⚠️ 归档缺少 x/d = 7.5 的径向剖面

文档 §MEASUREMENT LOCATIONS 列出径向测点 `x/d = 1, 2, 3, 7.5, 15, 30, 45, 60, 75`，
但**归档里没有 7.5**。两条独立证据：

1. **标量数据**：`pmD.stat` 含 `D01 D02 D03 D075 D15 D30 D45 D60 D75`（无 7.5）
2. **速度数据**（独立压缩包）：`TUD_LDV_D.d01 d02 d03 d075 d15 d30 d45 d60`（无 7.5）

命名规则（前导零为小数）：`01→1`、`02→2`、`03→3`、**`075→0.75`**、`15→1.5`、`30→3.0`、`45→4.5`、`60→6.0`、`75→7.5`。

旁证：`D075` 剖面中心线温度 307 K，而中心线在 5d 处为 298 K、10d 处 352 K —
若 `D075` 是 7.5d，中心线应约 430 K，实测仅 307 K，故 `D075 = 0.75d`。

**影响**：对标时 x/d = 7.5 只能用中心线插值（≈430 K）近似，不可与径向剖面并列。
`scripts/postprocess.py` 的 `X_D_RADIAL` 已按归档实际位置设为
`[0.75, 1, 2, 3, 15, 30, 45, 60, 75]`。

---

## 6. 后处理对比核心的自检（`scripts/selftest_compare.py`）

`postprocess.py` 的 `extract()` 需要 Fluent 才能跑，但它的 **`compare()` 核心**
（CFD↔实验配对 + RMS/偏差计算）此前**从未执行过**。若这部分错位，会**静默产出
错误的对标表**——是本项目风险最高又最便宜可测的一环。

做法：把 TNF 实验数据本身当作"CFD 结果"喂进 `compare()`。恒等输入应得 RMS≈0；
再施加已知扰动（+100 K 恒定、0.9 倍缩放）验证误差按解析值变化。

**结果：14/14 通过。** 过程中抓出 **3 个真实 bug**（都会污染最终对标）：

| # | 缺陷 | 后果 | 修法 |
|---|---|---|---|
| 1 | `load_tnf()` 用 `(x/d, round(r/d,2))` 做 dict 键 | **164 个实验点被折叠成 146**（2 处 r/d 四舍五入碰撞 + 16 个中心线点因 r/d→0.0 互相覆盖）；恒等输入也出现非零 RMS | 改为返回**全量列表**，逐点配对 |
| 2 | CFD CSV 无字段区分径向/中心线 | `compare()` 把**中心线样本混进径向剖面**（两者 x/d 会撞车），产出 `T_cfd_max = 1953 K` 这种等于 x/d 数值的荒谬结果 | CFD CSV 新增 `profile` 列（`radial`/`centerline`），`compare()` 按它分组 |
| 3 | 对重复 r/d 先取平均再插值 | TNf 数据本身在同一 (x/d, r/d) 有多个不同测值（x/d=0.75 的 r/d=-2.78 → 291/290 K；x/d=45 的 r/d=0.0 → 1938/1957 K），取平均＝人为平滑真实散布 | 改用**最近邻匹配**，并输出 `max_abs_dr_over_d` 让配对质量可见 |

自检用例与判据：

| 用例 | 期望 | 实测 |
|---|---|---|
| 恒等输入（CFD==实验） | RMS ≤ 重复坐标散布 | max RMS = **1.095 K**（散布 6.0 K） |
| 恒等输入 bias | \|bias\| ≤ 散布 | max\|bias\| = **0.000 K** |
| 恒等输入峰值 | \|ΔT_max\| ≤ 散布 | **0.000 K** |
| +100 K 恒定偏置 | RMS ∈ [100, 100+散布] | **100.000 – 100.006** |
| 0.9 倍缩放 | 与解析值一致（容差 0.05 K，CSV 打印精度） | max\|diff\| = **6.4e-3** |
| CFD 缺 x/d=45 | 该点跳过，其余 8 个保留 | ✅ |
| `load_tnf` 完整性 | 保留全部 164 点 | ✅ |
| 重复坐标存在性 | 确认（证明最近邻的必要性） | 2 组 |

> 顺带修正：`postprocess.py` 里 `X_D_RADIAL` 已改为归档实际位置
> `[0.75, 1, 2, 3, 15, 30, 45, 60, 75]`（无 7.5，见 §5.3）。

---

## 7. 对标参考图与契约（`scripts/plot_tnf.py`）

生成于 `results/figs/`（matplotlib 无界面模式；注意其默认字体**无中文字形**，
标签已统一用英文，否则会渲染成方框）：

| 图 | 内容 |
|---|---|
| `tnf_centerline_T.png` | 中心线温度，峰值 1957 K @ x/d=45，标注 L_stoic/d=47 与 L_vis/d≈67 |
| `tnf_radial_T.png` | 全部 9 个径向剖面 |
| `tnf_scatter_FT.png` | **F–T 状态关系**：峰值 ~1950 K 近 F_stoic=0.351，降至 F=1.0 处 ~300 K |

`results/targets_tnf.csv`：**对标契约表**，164 个实验目标点，含
F、T 与 Y(O₂/N₂/H₂O/CH₄/CO/CO₂/OH/H₂/NO) 及 CO-LIF。
CFD 结果一到，`postprocess.py --compare` 即可离线出对标表（纯 Python，秒级）。

---

## 9. 加速与对标管线（Round 4 新增）

### 9.1 换用 5 组分单步机理（关键提速）

GRI-Mech 3.0（53 组分 / 325 反应）在本机实测 **12.6 s/步**，200 步要 42 分钟以上，
且出现过并行化学死锁，完全无法在合理时间内出结果。

改用自建单步总包机理 `mechanism/ch4_1step_chem.inp`：
```
ELEMENTS  O H C N  /  END
SPECIES   CH4 O2 CO2 H2O N2  /  END
REACTIONS  CH4+2O2=>CO2+2H2O   2.119E+11   0.000   20270.0
END
```
热力学文件 `ch4_1step_thermo.dat` 的 NASA 系数**直接从 Fluent 自带
`KINetics/data/grimech30_thermo.dat` 抽取**（脚本 `scripts/make_simple_thermo.py`），
因为手写格式会让 Fluent 报 `Memory allocation failed during Chemkin mechanism import`。

| 机理 | 组分数 | 实测速度 |
|---|---|---|
| GRI-Mech 3.0 | 53 | 12.6 s/步 |
| **单步总包** | **5** | **0.155 ~ 0.163 s/步** |

**加速约 80 倍。** 代价：单步机理**无法给出 CO / OH / H2 / NO 等中间组分**，
也无法表征局部熄火 —— 报告中 CO/OH 的对标不可用。

### 9.2 三个关键 API 坑（本轮实测确认）

**(a) 边界组分：N2 是"余量组分"，且 Fluent 不做归一化**

Fluent 边界的 `species_mass_fraction` **只暴露 4 个组分**
（`ch4/o2/co2/h2o`），**N2 不在其中**——它由 Fluent 取 `1 - 其余之和`。
且 Fluent **不做归一化**，和必须恰好为 1，否则报
`Sum of species fractions (1.25) exceeds one`。

早期版本错误地把 4 个组分按 0.353 归一化，把 CH4 抬到 0.443，化学计量完全错。
正确做法（`scripts/run_fast2.py`）：
```python
explicit = {"ch4": 0.15637, "o2": 0.19650}        # 只用原始质量分数
st = {k: {"option": "value", "value": explicit.get(k, 0.0)} for k in smf.keys()}
smf.set_state(st)                                  # N2 自动补 0.64713
```
实测回读：jet `{ch4: .15637, o2: .19650}` → N2 余量 0.64713 ✅

**(b) line surface 签名是 `line_surface(name, x, y0, x, y1)`**

` 是 **TUIMethod**（不是 TUIMenu，`.create()` 会报
`'line_surface' object has no attribute 'create'`）。实测正确形式为
**4 个数值参数、两端点同 x**：
```python
s.tui.surface.line_surface("r30", 30*d, 0.0, 30*d, R_DOMAIN)
# -> x∈[0.216,0.216], y∈[0,0.216]  即 x/d=30 的径向线 ✅
```
用 7 参数形式会创建出朝向完全错误的 surface（这是早期 ASCII 导出全部作废的根因）。

**(c) 读数必须走 `get_state()`，不能 `.value`**

`smf['ch4'].value` 返回的是对象而非数值；正确读法是
`smf.get_state()` → `{'ch4': {'option':'value','value':0.15637}, ...}`。

### 9.3 已建立的完整对标管线（已跑通）

`scripts/run_fast2.py` 一条命令完成：
设置 → 热态点火 → 冷态续算 → **截取 9 个径向剖面 + 中心线** → 写
`results/cfd_fast_<mesh>.csv`。

`scripts/plot_compare.py` → `results/figs/cmp_<tag>.png`：
6 个径向剖面 + 中心线的 CFD/实验对照，每格标注 RMS。

**本次实测结果（coarse，未点火）**：

| x/d | 0.75 | 3 | 15 | 30 | 45 | 60 |
|---|---|---|---|---|---|---|
| RMS (K) | 177 | 616 | 634 | 985 | 1199 | 949 |

中心线 CFD 全程约 300 K，实验峰值 1957 K —— **平均 RMS ≈ 760 K**。
CFD 在 x/d=0.75 抓到 pilot 的 ~1700 K 峰值（RMS 仅 177 K），
但从 x/d=3 起迅速衰减到 300 K。

### 9.4 仍未解决的问题：燃烧没有建立

实测出口 CO2 ≈ 1.3e-3（完全燃烧应约 0.15），O2 基本未消耗 ——
**不是"反应慢"，而是几乎没有反应发生**。

已排除：
* 组分设错 —— 9.2(a) 修正后回读确认正确
* 机理没导入 —— 5 组分导入成功
* EDC 没开 —— `turb_chem_interaction` 确认为 `eddy-dissipation-concept`
* 没点火 —— 热入口 1100 K 时域内确实升到 ~880 K，但改回 294 K 后立即熄掉

待查（下一轮）：
1. 单步机理**只有 4 个反应组分**，"惰性余量 N2" 的处理是否让 EDC 的反应速率被稀释
2. EDC 细结构反应器在 5 组分体系下是否需要调 `volume_fraction_constant` /
   `time_scale_constant`
3. `stiff-solver` 与单步机理的搭配是否真的在积分化学（可查 transcript 的
   化学迭代计数）
4. 是否需要**两步机理**（Westbrook-Dryer，仍只有 5~6 组分）以降低着火温度

---

## 10. 当前状态与下一步

**已完成**：原始内容复核、混合分数核算、SLFM 排除、EDC 打通、
TNF 数据取得与核查、参考图与对标契约、后处理对比核心自检 14/14、
**5 组分单步机理（提速 80 倍）**、**完整对标管线跑通并出图**、
**EDM 点火成功并出对标图**（§11）、全部脚本与坑位记录。

**未完成**：
1. 压制 EDM 周期性熄火-再点燃振荡；修正 under-relaxation TUI 路径
2. 中场过热 / 火焰偏短的模型偏差（两步机理或有限速率混合）
3. coarse 收敛
4. medium 网格
5. 用全量标量（含 CO/OH）的对标 —— 需回到 GRI 机理

**环境限制**：EDC + 53 组分刚性化学在 6 核机上约 12.6 s/步并出现过并行死锁，
故先用单步机理建立可用结果。

---

## 11. EDM 点火成功（2026-09-12）

### 11.1 关键实验

| # | 配置 | 结果 | 证据 |
|---|---|---|---|
| 1 | 三入口临时加热 1100 K + EDM 1500 步 | 500–1000 步 T≈2100–2150 K，**1500 步熄火**（T=768 K） | `run/run_edm.log`（第一轮） |
| 2 | **文档温度** + EDM 250 步 | **T_max=2230 K，CO2=0.146，点着** | 同文件后续 |
| 3 | 文档温度 + EDM 250 步后立刻切 EDC | **250 步内熄火**（T→311 K） | 同 |
| 4 | 文档温度 + **全程 EDM 2500 步** | 建立火焰，但有振荡；最终 T_max=2262 K | `run/run_edm.log` |
| 5 | 从 #4 续算 +3000 步 | 远场大幅改善：x/d=45 T_max 711→**1861 K** | `run/run_edm_cont.log` |

### 11.2 结论

1. **EDM 能点着 Sandia flameD**（文档温度即可，无需热入口）。
2. **EDC + 单步机理不能维持火焰**——点着后切 EDC 会立刻熄。
   根因仍是 Arrhenius（Ea=20270 cal/mol）在细结构反应器温度下太慢。
3. **热入口 1100 K 反而有害**：把冷 jet 也加热后 EDM 会过度燃烧再吹熄。
   正确做法是保持文档温度，靠 pilot 1880 K 引燃。
4. EDM 仍**周期性熄火-再点燃**（约每 1000–1500 步一次深谷），
   under-relaxation TUI 路径 `solve/set/under-relaxation` 在本环境
   报 `'set' object has no attribute 'under'`，尚未调成。

### 11.3 对标（续算后，`results/figs/cmp_edm_cont.png`）

| x/d | 0.75 | 3 | 15 | 30 | 45 | 60 | mean |
|---|---|---|---|---|---|---|---|
| RMS (K) | 265 | 434 | 942 | 564 | 138 | 181 | **~420** |

- 中心线 CFD 峰 **2296 K @ x/d=36** vs 实验 **1957 K @ x/d=45**
- 偏差模式：近场尚可 → **中场过热、火焰略短** → 远场（x/d≥45）已接近
- 这是 EDM + 单步机理的典型局限（无解离、无中间产物、混合即燃）

### 11.4 主文件

| 文件 | 说明 |
|---|---|
| `scripts/run_edm.py` | 点火主脚本（支持 `--skip-hot` / `--edm-only` / `--switch-t` / `--mech 1step\|2step`） |
| `scripts/run_edm_cont.py` | 从已有 case 续算并导出 |
| `run/edm_coarse_c_only_cont.cas.h5` | 1-step 最好续算算例 |
| `run/edm_coarse_2step_c_only_fo.cas.h5` | **★ 2-step 当前主算例** |
| `results/cfd_edm_coarse_2step_c_only_fo.csv` | 2-step 剖面 |
| `results/figs/cmp_edm_2step.png` | ★ 2-step 对标图 |
| `MESH_AUDIT.md` | 网格无关性审查 |

---

## 12. 振荡、两步机理、网格、火焰面（2026-09-12 下午）

### 12.1 EDM 振荡根因与缓解

| 发现 | 证据 |
|---|---|
| TUI `/solve/set/discretization-scheme/...` **不生效** | `solution.methods` 里 temperature/species 仍为 **second-order-upwind**（`probe_urelax4`） |
| 二阶温度/组分是振荡主因之一 | 改用 settings API 强制 **first-order-upwind** 后平稳段变长 |
| URF：`controls.under_relaxation` **inactive**；无 `tui.solve.set.under_relaxation` | `probe_urelax` 系列 |
| 可用稳控 | `solution.methods` 一阶 + `run_calculation.pseudo_time_settings`（automatic/conservative）+ `tui.solve.set.pseudo_transient yes` |

**正确设一阶（必须走 settings API）：**
```python
ds = s.settings.solution.methods.spatial_discretization.discretization_scheme
for k in ds.get_state():
    if k != "pressure":
        ds.set_state({k: "first-order-upwind"})
```

**仍未完全压住**：coarse 上约每 750–1250 步仍会出现深谷熄火后再点燃（稳态 EDM 极限环）。彻底解决需**真瞬态小时间步**或改模型。

### 12.2 两步机理（已落地）

| 文件 | 内容 |
|---|---|
| `mechanism/ch4_2step_chem.inp` | CH4+1.5O2=>CO+2H2O；CO+0.5O2=>CO2（Ea cal/mol） |
| `mechanism/ch4_2step_thermo.dat` | 从 GRI 抽 CH4/O2/CO2/H2O/**CO**/N2 |
| 运行 | `run_edm.py --mech 2step` |

coarse + EDM + 一阶 + 伪瞬态 + 文档温度，2500 步：
- RMS：239 / 430 / 919 / 562 / **143** / **129**（x/d=0.75/3/15/30/45/60），mean≈**403 K**
- 中心线峰 **2289 K @ 35.8d**（实验 1957 @ 45d）
- x/d=45 中心线 **1899 K**（1-step FO 同窗口仅 1421 K）→ **远场明显更合理**
- CO 在 x/d=15 达 ~0.014（1-step 无 CO）

### 12.3 网格无关性（`MESH_AUDIT.md`）

- 静态：三级 26.9k / 58.9k / 116.6k，近场 Δ 0.45/0.30/0.21 mm，阶梯合理。
- medium 同 2-step 跑到 1750 步（超时未存盘）：燃烧窗内 T_max≈2230–2270 K（与 coarse 差 ~1–2%），但 **T_axis@x/d=30 仅 ~370 K vs coarse ~2170 K** → **火焰拓扑网格敏感**（coarse 数值扩散使火焰提前贴轴）。
- **未满足** report 的 1% 峰值无关判据；振荡主导误差，fine 暂缓。
- 工程建议：对标暂用 coarse+2-step，报告必须声明 coarse 扩散偏差。

### 12.4 火焰面 / SLFM 复核（headless）

| 路径 | 结果 |
|---|---|
| `species.model.option = partially-premixed-combustion` | ✅ 可设 |
| `chemistry.state_relation` allowed | `['equi', 'steady-diffusion', 'fgm', 'unsteady-flamelet']` |
| **`state_relation = 'steady-diffusion'`** | ✅ **这就是 SLFM**；`flamelet` 子树激活 |
| `chemistry.flamelet_options` | `['create-flamelet', 'import-flamelet']`（默认 create） |
| `ppo.boundary`（PDF 燃料/氧化剂） | ❌ **仍 inactive**（headless） |
| `import_standard_flamelet` | ❌ inactive（无库文件；KINetics/data 无 .fld） |
| TUI `non-premixed-combustion/*` | 仍无法赋值（与 §2 一致） |

**结论**：设置树里 **能打开 SLFM 模型开关**，但 **PDF 边界 + 火焰面库生成/导入仍无 headless 入口**。
与 HANDOFF §4.1 一致：**Create Flamelet Library 仅 GUI**。若必须 SLFM，需在 GUI 生成库文件后再 headless 导入（本机当前无现成 .fld）。

证据：`run/probe_flamelet2.log` … `probe_slfm_create.log`。


