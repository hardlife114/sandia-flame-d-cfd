# Sandia Flame D 复现：圆射流湍流燃烧 CFD 对标

3D 与 2D 轴对称 RANS 复现 Sandia/TNF **Flame D** 值班射流火焰，
逐站温度 RMS 最低做到 **215 K**；并给出误差来源的定量归因与对照实验验证。

- 求解器：ANSYS Fluent 2025 R2（PyFluent 脚本化，headless）
- 湍流：k-ε realizable + Enhanced Wall Treatment
- 燃烧：涡耗散模型（EDM）／非预混平衡 + β-PDF（两套对比）
- 网格：结构化六面体，最大 889k 单元；已做 GCI 网格收敛性验证

---

## 一、效果较好的算例（推荐）

按逐站温度 RMS 排序，前三个是本项目可用的算例：

| # | 算例 | 逐站 RMS | 几何 | 燃烧模型 | 备注 |
|---|---|---:|---|---|---|
| **1** | `np_eq_d_v5_medium_so` | **215.0 K** | 2D 轴对称 | **非预混平衡 + β-PDF** | **最佳**；β-PDF 平均是精度关键 |
| **2** | `box3d_round` | **242.0 K** | **3D 全域** 432 mm 方域 | EDM | 3D 最佳；圆进口分区 |
| **3** | `box3d_round300` | **264.2 K** | **3D 全域** 300 mm 方域（= 实验风洞） | EDM | 域贴实验尺寸，约束略强 |

> **RMS 定义**：实验站位 r/d ∈ [−0.01, 6.0]，CFD 径向剖面线性插值后
> `RMS = sqrt(mean((T_CFD − T_EXP)²))`，对 x/d = 0.75, 1, 2, 3, 15, 30, 45, 60, 75 取均值。

**算例 1 的物理要点**：非预混模型求解 ⟨T⟩ = ∫P(F)·T_eq(F)dF，
天然包含混合分数脉动的平均——这正是 EDM（一阶矩闭包）缺失的部分（见下文归因）。

**算例 2 / 3 的物理要点**：进口按 **半径** r = √(y²+z²) 分区（jet / pilot / coflow），
而非按 |y| 条带。这一处修正把火焰偏移从 T 反对称 RMS **471 K 降到 4.9 K**，
远场 T>1000 K 占比从 **92.9% 降到 0.0%**。

---

## 二、完整对标表（含局限算例）

科学结论需要"哪些不行"同样清楚，故一并列出：

| 算例 | RMS | 为什么差 |
|---|---:|---|
| 2D 轴对称·非预混·一阶 | 227.0 K | 离散格式降级 |
| 3D 圆进口·EDM·300 mm | 264.2 K | 见推荐表 |
| **2D 全域平面·非预混·二阶** | **463.5 K** | **几何结构性误差**：平面模型缺柱面积项（∂/∂z≡0），火焰片抬离轴线、峰值不衰减。加密到 532k 单元、升到二阶格式都不改变解 → **平面 2D 不能用于圆射流对标**，仅适合狭缝构型 |
| 2D 全域平面·一阶 | 475.4 K | 同上 |
| 3D 方管·EDM（错误进口 BC） | 674.1 K | 进口按条带分区 + 停留在点火态 |
| 2D 轴对称·EDM（冷入口） | 681.5 K | EDM 快速化学 + 火焰过短 |

---

## 三、关键发现

### 1. 火焰偏移的根因是进口分区方式（已修复）

早期 3D 算例把进口按 |y| 条带分区（这是在描述**平面**射流），
而 Flame D 是**圆形**射流。后果是火焰片沿 y 方向被拉成"片状"并抬离轴线。

改为按半径分区后：

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| T 反对称 RMS @x/d=30 | 471 K | **4.9 K** |
| 远场 T>1000 K 占比 | 92.9% | **0.0%** |
| 逐站 RMS | 674.1 K | **242.0 K** |

### 2. 收敛性：75 步即达机器精度（附验证方法）

同一算例在 75 / 300 / 450 步各存一次盘（`.dat.h5`，154 MB），
**字节级比较只有 144 字节不同，且全为 ASCII 元数据**——场数据逐字节一致。

> ⚠️ 判据陷阱：`T@30d`（一条线上的 min/max）被进口温度与化学峰值"钉死"，
> 从第一段起就恒定，**不能**用作收敛判据。要看收敛请做字节级或剖面 diff。

### 3. x/d=15 误差最大：定量归因

实验在 x/d=15 有一个明显的温度"谷"（T_max 1633 K，而 x/d=3 是 1937 K、x/d=45 回升到 1938 K），
伴随**最强的温度脉动**（T_rms 316 K，是 x/d=3 的 4 倍）。分解如下：

```
实验 1633 K ──(+130 K 熄火/辐射)── 非预混+βPDF 1763 K ──(+452 K 缺 PDF 平均)── EDM 2215 K
```

轴心（r/d=0）的对比更极端：

| x/d=15 轴心 | 温度 |
|---|---:|
| 实验 | **498 K** |
| 非预混 + β-PDF | 713 K |
| 3D EDM | 1471 K |

实验该处 **F=0.908（富燃）+ Y_O2=0.174（有氧）却只有 498 K**——混合了但没烧，
即**局部熄火**；而 EDM 不可熄火，必然烧到接近绝热火焰温度。

→ **轴心超温 973 K 的分解：缺 β-PDF 标量脉动平均 758 K（78%）+ 熄火/辐射 215 K（22%）**

### 4. 对照实验：证伪"湍流模型衰减过快"假设

怀疑"k-ε 对圆射流衰减预测过快"，于是做了一个**等温惰性混合**对照算例
（同网格、同进口、同湍流模型，仅关闭化学反应与能量方程）。

先验证实验有效性：惰性条件下 CH4 只能来自射流，故 Y_CH4 = 0.15637·w_jet，
权重由**元素守恒**反解——实测/预测比 = **1.000**（4 个站位，CH4 与 O2 皆然），
确认反应确已关闭。

结果（轴心混合分数）：

| x/d | 3 | 15 | 30 | 45 | 60 |
|---|---:|---:|---:|---:|---:|
| 实验（燃烧） | 0.988 | 0.908 | 0.657 | 0.387 | 0.220 |
| **惰性（无燃烧）** | 0.973 | 0.395 | 0.173 | 0.118 | 0.090 |
| 燃烧 EDM | 0.997 | 0.984 | 0.538 | 0.185 | 0.119 |

把惰性解拟合成自由圆射流经典衰减律 `F_cl = K/(x/d − x0/d)`：

```
K = 5.43,   x/d ≥ 30 处偏差 ≤ 0.007
文献经典值 K_d ≈ 5.4–6.2（Becker）
```

**K = 5.43 落在经典区间内** → k-ε 的纯湍流混合预测是正确的，不是误差源。

### 5. 误差根因收敛到燃烧模型

| 现象 | 证据 |
|---|---|
| 燃烧确实抑制射流混合（真实物理） | 惰性 x/d=45 → 0.118；实验燃烧 → 0.387 |
| CFD 的抑制在 x/d ≤ 15 **过强** | EDM 0.984 vs 实验 0.908 |
| CFD 的抑制在 x/d ≥ 30 **过早消退** | EDM 0.185 vs 实验 0.387 |

抑制效应的**空间分布是错的**，这与 **EDM 火焰过短**（燃烧区在 x/d≈30–45 就结束）一致。
三处症状——x/d=15 轴心超温 +973 K、下游欠温 −343 K、混合分数场分布错误——**同源于 EDM**。

---

## 四、目录结构

```
.
├── README.md
├── LICENSE                    MIT；含第三方材料声明（GRI-Mech / TNF 数据不在 MIT 范围内）
├── scripts/                   核心脚本（30 个）
│   ├── flamed_common.py           常量、进口配方、网格规格
│   ├── gen_mesh_box3d.py          3D 六面体网格（圆进口分区、--dry-run）
│   ├── gen_mesh.py                2D 轴对称/平面网格
│   ├── verify_mesh3d.py           网格校验
│   ├── run_box3d_edm.py           3D EDM 求解（分段可续）
│   ├── run_box3d_mix.py           3D 等温惰性混合（对照实验）
│   ├── run_np_eq.py               2D 非预混平衡求解
│   ├── driver_round.py            3D 分段接力驱动器
│   ├── prep_np3d_pregui.py        非预混模型的 GUI 前置 case 生成
│   ├── export_box3d_profiles.py   剖面导出
│   ├── extract_slices.py          切片提取
│   ├── render_slices.py           云图渲染
│   ├── analyze_asym.py            对称性破缺量化
│   ├── compare_species_rms.py     组分 + 混合分数逐站对标
│   ├── compare_mix_vs_burn.py     惰性 vs 燃烧对照分析
│   ├── verify_mix_inert.py        惰性实验有效性验证（元素守恒反解）
│   ├── station_rms_so_compare.py  逐站温度 RMS 汇总
│   ├── accuracy_axisym_vs_planar.py  轴对称 vs 平面精度对比
│   ├── gci_analysis.py            Roache GCI 网格收敛性
│   ├── inspect_inlets.py          进口边界逐项回读
│   ├── archive_run.py             算例归档（生成可复现清单）
│   ├── parse_tnf.py  qc_tnf.py    TNF 实验数据解析与质检
│   └── …                          误差预算、启动辅助、绘图
├── docs/                      13 篇文档
│   ├── AI_OPERATIONS_MANUAL.md    ★ 操作手册（环境/命令/坑/复现）
│   ├── BACKUP_POLICY.md           备份规范与「可复现」判定标准
│   ├── CALC_CARD_3D_V3/V4/V5.md   各阶段计算卡（逐项边界条件核对）
│   ├── GCI_FLAMED_V4.md          网格收敛性完整报告
│   ├── NP_MIXTURE_FRACTION_CONVENTION.md  非预混混合分数口径
│   └── REPORT_COMBUSTION_MODELS.md        燃烧模型对比评估
├── mechanism/                 化学机理（1步 / 2步 / 2步relaxed + GRI-Mech 3.0）
├── results/                   CSV 剖面数据 + 图件
└── archive/                   4 个算例的可复现归档清单
```

---

## 五、复现

### 环境

```
ANSYS Fluent 2025 R2（v252）
Python：ANSYS 自带 CPython 3.10（含 PyFluent）
```

给 Windows 版 ANSYS Python 传路径时必须用 `D:\...` 形式；
在 git bash 里写 `/d/...` 会 `ModuleNotFoundError: No module named 'ansys.fluent'`。

### 主流程

```bash
# 1) 生成 3D 网格（300 mm 实验尺寸域）
python scripts/gen_mesh_box3d.py --compact --round --half-mm 150 \
       --dmin 0.5 --dmax 10 --out mesh/box3d/compact_round300.msh

# 2) 分段接力求解（冷流 60 步 + 反应 18×25 步，段间可中断续算）
python scripts/driver_round.py --tag box3d_round300 \
       --mesh mesh/box3d/compact_round300.msh --cores 10

# 3) 后处理
python scripts/export_box3d_profiles.py --case run/box3d_round300.cas.h5 --tag box3d_round300
python scripts/analyze_asym.py run/slices_round300/sz0.npz      # 对称性判据
python scripts/station_rms_so_compare.py                        # 逐站 RMS
python scripts/compare_species_rms.py                           # 组分 + 混合分数
```

### 算例归档（可复现性保证）

```bash
python scripts/archive_run.py --tag box3d_round300 \
       --mesh mesh/box3d/compact_round300.msh --backup-dir /path/to/backup
```

归档器采集代码版本、网格（含 sha256 与生成命令）、算例定义、**边界条件逐项回读记录**、
阶段序列、环境与对标指标，并做 6 项复现充分性自检。
标准是：**拿到备份不需要任何口头补充就能重跑出同一结果**。
详见 `docs/BACKUP_POLICY.md`。

### 关于非预混算例的一处已知限制

非预混模型的**使能**必须经一次 GUI（Fluent 的 fuel-stream unity-sum 校验会挡住
TUI/settings 路径）。`prep_np3d_pregui.py` 已把其余设置全部备好，
GUI 只需：Species Model → Non-Premixed（Equilibrium + Beta PDF）→ 另存种子 case。
此外绝热非预混不求解能量方程，**pilot 的 1880 K 无法显式给定**，
只能由已燃气体混合分数 F=0.27 体现（这是该模型的固有近似，已在计算卡中标明）。

---

## 六、已知局限

1. **EDM 不可熄火**：x/d=15 的局部熄火无法复现，残留约 130 K 偏差。
2. **绝热假设**：未计辐射，峰值温度偏高约 40–80 K。
3. **非预混平衡模型同样不可熄火**：能修掉缺 PDF 平均的部分，修不了熄火。
4. **k-ε 对圆射流**：经对照实验验证其衰减率正确，但燃烧-湍流耦合的空间分布仍有偏差。
5. 平面 2D 模型**不适用**于圆射流（见 §二）。

---

## 七、引用与致谢

- 实验数据：Barlow & Frank, *Piloted CH4/Air Flames C, D, E and F*,
  Sandia National Laboratories，经 TNF 工作组公开分发。
- 化学机理：**GRI-Mech 3.0**（Berkeley / Stanford / U Texas / SRI）。
- 求解器：ANSYS Fluent 2025 R2，通过 PyFluent 脚本驱动。

本项目为独立复现工作，与上述机构无隶属关系。

## 八、许可

本项目代码与文档采用 **MIT License**（见 [`LICENSE`](LICENSE)）。

第三方材料 —— **GRI-Mech 3.0 机理**（`mechanism/grimech30_*`）与
**Sandia/TNF 实验数据**（`results/tnf_flamed.csv`）—— 遵循其原始条款，
**不在 MIT 授权范围内**，详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
