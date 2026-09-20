# Sandia Flame D — 今日操作总结与可复现流程

**日期**：2026-09-12  
**工作目录**：`C:\Users\lx\Desktop\fluent_flamed`  
**环境**：Fluent 2025 R2 + Chemkin 2025 R2 + Cantera 3.2.0

---

## 今日完成的四条线

| # | 线 | 结果 |
|---|---|---|
| 1 | Chemkin GUI 火焰面库 | ✅ **12 条 GRI 火焰面**（χ=0.5–200） |
| 2 | EDM + 两步机理 D/E/F | ✅ 三算例点火并出对标图 |
| 3 | 燃烧模型对比（EDC/有限速率） | ✅ 结论：仅 EDM 能维持 |
| 4 | 网格审查 / 振荡 / Cantera 备份库 | ✅ 记录在案 |

---

# A. Chemkin GUI 火焰面库（重点可复现流程）

## A0. 前置：命令行预处理（推荐先做）

**目的**：生成 `chem.asc` / `tran.asc`，避免 GUI 预处理路径/编码问题。

```powershell
# 1) 准备短路径工作目录（长中文路径易导致 GUI I/O 错误）
mkdir C:\cktmp -Force
$gri = "D:\Program Files\ANSYS\2025R2\v252\fluent\fluent25.2.0\KINetics\data"
Copy-Item "$gri\grimech30_50spec_mech.inp" C:\cktmp\chem.inp
Copy-Item "$gri\grimech30_thermo.dat"       C:\cktmp\therm.dat
Copy-Item "$gri\grimech30_transport.dat"    C:\cktmp\tran.dat

# 2) 化学集 .cks（必须含 OUT_*_ASC，且只用 -i，不要 -o）
@"
#
Chemistry Set Name=gri
IN_CHEM_INPUT=C:\cktmp\chem.inp
IN_THERM_DB=C:\cktmp\therm.dat
IN_TRANS_DB=C:\cktmp\tran.dat
IN_SURF_INPUT=
SYSTEM_FLAG=FALSE
FIT_TRANSPORT_PROPERTIES=1
OUT_CHEM_ASC=C:\cktmp\chem.asc
OUT_CHEM_OUTPUT=C:\cktmp\chem.out
OUT_TRAN_ASC=C:\cktmp\tran.asc
OUT_TRAN_OUTPUT=C:\cktmp\tran.out
"@ | Set-Content C:\cktmp\gri.cks -Encoding ASCII

# 3) 预处理
$ck = "D:\Program Files\ANSYS\2025R2\v252\reaction\chemkin.win64"
$root = "D:\Program Files\ANSYS\2025R2\v252"
$env:PATH = "$ck\bin;$root\tp\IntelCompiler\2023.1.0\winx64;$root\tp\IntelMKL\2023.1.0\winx64;$root\tp\zlib\1.2.13\winx64;$env:PATH"
cd C:\cktmp
& "$ck\bin\CKPreProcess.exe" -i gri.cks
# 成功标志：chem.asc ≈ 169 KB，tran.asc ≈ 272 KB
```

**坑**：
- `-o chem.asc` 只会打开输出文件，**不会**真正跑机理；
- `.cks` 用相对路径 + 长路径 → `Failure ... output NULL` 或 I/O error；
- 6 组分机理 + 50 组分 transport → 组分不匹配 I/O error。

---

## A1. 启动 Chemkin 并建工程

```powershell
$ck = "D:\Program Files\ANSYS\2025R2\v252\reaction\chemkin.win64"
Start-Process -FilePath "$ck\bin\run_chemkin.bat" -WorkingDirectory $ck\bin
# 等待窗口：ANSYS Chemkin 2025 R2
```

| 步骤 | 操作 |
|---|---|
| 1 | 工具栏 **New...** → 输入工程名 `FlameD_Flamelet` → Enter |
| 2 | 左侧 **Models → Flame Simulators** |
| 3 | 把 **Diffusion Flamelet Generator**（第 2 行最后一个图标）拖到右侧 Diagram |

---

## A2. Pre-Processing（GUI，关键 6 步）

左侧树：**Pre-Processing**

| 步骤 | 操作 | 注意 |
|---|---|---|
| 1 | **Working Dir** = 工作目录（建议短路径 `C:\cktmp` 或 `...\chemkin_work`） | 长路径易失败 |
| 2 | **Chemistry Set** 下拉 → 选 `.cks` | 若选到系统库 `D:\Program Files\...`，会提示 Copy |
| 3 | 若系统库 → 点 **Clone** → 保存到 Working Dir | 会生成 `Copy_of_xxx.cks` + 机理副本 |
| 4 | 核对 4 个文件：Gas / Thermo / Transport 有路径，**Surface 留空** | Surface 只用于催化 |
| 5 | Process Transport = **Fit with Normal Output** | |
| 6 | 点 **Run Pre-Processor** | 成功标志见底部状态栏 |

**成功状态栏示例**：
```
Pre-Processing Successful for C:\...\Copy_of_grimech30.cks run in C:\...
```

**失败对照**：
| 报错 | 原因 | 处理 |
|---|---|---|
| files are missing / Invalid Path | 相对路径或文件不在 | 用绝对路径；Surface 留空 |
| unexpected I/O error … chem.inp | 组分数与 transport 不匹配 / 编码 | GRI 三件套一起用 |
| Status Code = 26 | 同上 | 查 Working Dir 下 `.out` 日志 |

---

## A3. Diffusion Flamelet Generator 配置

左侧树展开 **Diffusion_Flamelet_Generator (C1)**。

### 3.1 C1_Inlet1（Fuel）— 25% CH₄ / 75% air（摩尔）

1. **Stream Properties Data (Fuel)**：Inlet Temperature = **294** K  
2. **Species-specific Properties (Fuel)**：Unit = mole fraction  

| Species | Data | Add |
|---|---|---|
| CH4 | 0.25 | Add |
| O2 | 0.1575 | Add |
| N2 | 0.5925 | Add |

（和 = 1.0）

### 3.2 C1_Inlet2（Oxidizer）— 干空气

1. 双击树中 **C1_Inlet2** → 弹 “This inlet is Oxidizer” → **OK**  
2. Temperature = **291** K  
3. Species：

| Species | Data |
|---|---|
| O2 | 0.21 |
| N2 | 0.79 |

### 3.3 C1_ Diffusion Flamelet Generator → Reactor Physical Properties

| 参数 | 值 | 说明 |
|---|---|---|
| Pressure | **0.993** atm | Flame D |
| End Time | 0.05 s | 瞬态积分上限 |
| Nominal χ | **50** 1/s | 名义标量耗散率 |
| Minimum χ | **0.5** 1/s | |
| Steps to minimum | **8** | 生成 8 条低 χ |
| Maximum χ | **200** 1/s | |
| Steps to maximum | **3** | 生成 3 条高 χ |
| Max T for Initial Profile | 2200 K | |
| Min Flame Temp | 1500 K | 低于则判熄火 |
| Compute Extinguishing Flamelets | 勾选 | |

→ 共 **1+8+3 = 12** 条火焰面。

### 3.4 Grid Properties

| 参数 | 值 |
|---|---|
| Max Grid Points | 250 |
| Grid 类型 | Use Biased Grid |
| Bias 0→Z_st | 1.5 |
| Pts 0→Z_st | 25 |
| Bias Z_st→1 | 1.2 |
| Pts Z_st→1 | 40 |
| Adaptive grad / curv / n | 0.1 / 0.5 / 10 |

### 3.5 Run

树 **Run Calculations** → **Begin**  
底部出现 `Done running all jobs` / success。

---

## A4. 成功产物与读法

Working Dir 下：

```
diffusionFlamelet_5.0000E-01.fla   … 12 个 .fla
FlameD_Flamelet.inp                 # 完整输入（可直接复现）
FlameD_Flamelet.out                 # 含 SSDR / Tflame 表
FlameD_Flamelet.log                 # 批处理日志
Copy_of_grimech30_gas.asc / _gtran.asc
```

**`.fla` 结构**：
```
HEADER
  STOICH_SCADIS, NUMOFSPECIES, GRIDPOINTS, STOICH_Z, PRESSURE
BODY
  Z
  TEMPERATURE
  MASSFRACTION-H2 … MASSFRACTION-N2
  PREMIX_YCDOT
END
```

**解析脚本**：`scripts/parse_fla.py` → `flamelet/fluent_flamelib_D.dat` + `flamelets_from_fla.png`

---

## A5. 导入 Fluent（尚未打通）

| 尝试 | 结果 |
|---|---|
| PyFluent `import_standard_flamelet(*.fla)` | Fluent **崩溃** |
| Utility → Export Solution | 仅 CSV，非 Fluent PDF |

**建议**：Fluent GUI → Species → Partially Premixed → `steady-diffusion` → Import Flamelet → 选 `.fla`；成功后再 headless 续算。

---

# B. EDM 流场算例（生产路线，已可复现）

## B1. 单火焰（以 D 为例）

```powershell
$A="D:\Program Files\ANSYS\2025R2\v252"
$PY="$A\commonfiles\CPython\3_10\winx64\Release\python\python.exe"
$env:PYTHONPATH="$A\commonfiles\CPython\3_10\winx64\Release\Ansys\PyFluentCore"
cd C:\Users\lx\Desktop\fluent_flamed

# 文档温度 + EDM + 两步 + 一阶 + 伪瞬态
& $PY scripts\run_edm.py --mesh coarse --skip-hot --edm-only --mech 2step `
      --flame D --n-cold 150 --n-edm 2500 --chunk 250 --switch-t 0

# E / F 改 --flame E 或 F，建议 --n-edm 2000
```

**设置要点**（脚本已内置）：
- `--skip-hot`：入口用文档温度（热入口反而吹熄）
- 一阶：必须走 `solution.methods` API（TUI 无效）
- 伪瞬态：`pseudo_time_settings` automatic/conservative
- 点火后**不要**切 EDC（会立刻熄）

## B2. 对标图

```powershell
& $PY scripts\plot_cmp_detail.py --cfd results/cfd_edm_d_coarse_2step_c_only_fo.csv --tag edm_D --flame D
& $PY scripts\plot_field.py --case edm_coarse_2step_c_only_fo --tag edm_2step
```

## B3. 入口设置速查

| | Jet | Pilot | Coflow |
|---|---|---|---|
| U D/E/F [m/s] | 49.6 / 74.4 / 99.2 | 11.4 / 17.1 / 22.8 | 0.9 |
| T [K] | 294 | 1880 | 291 |
| CH₄ | 0.15637 | 0 | 0 |
| O₂ | 0.19650 | 0.054 | 0.23574 |
| CO₂ / H₂O / CO | 0 | 0.1098 / 0.0942 / 0.00407 | H₂O 0.006256 |
| N₂ 余量 | 0.647 | 0.738 | 0.758 |

壁面 500 K；出口表压 0；操作压 0.993 atm。

---

# C. 关键结论（写报告时用）

1. **EDM + 两步**是本环境唯一能稳定维持 Sandia D/E/F 燃烧的模型。  
2. **EDC / finite-rate-edm** 从 EDM 场切换后数百步内全局熄火（与 Ea 无关）。  
3. **SLFM**：Chemkin GUI **可以**建库；Fluent headless **不能**建/导库，import `.fla` 会崩。  
4. coarse 网格有明显数值扩散（火焰过早贴轴）；medium 拓扑不同，无关性未达标。  
5. 稳态 EDM 有熄火–再点燃极限环；一阶+伪瞬态只能拉长平稳段。

---

# D. 文件索引

| 文档/结果 | 路径 |
|---|---|
| 火焰面库报告 | `REPORT_CK_FLAMELET_D.md` |
| D/E/F 研究报告 | `REPORT_SANDIA_DEF.md` |
| 燃烧模型对比 | `REPORT_COMBUSTION_MODELS.md` |
| 网格审查 | `MESH_AUDIT.md` |
| 对标/进口说明 | `docs_COMPARE_MESH_BC.md` |
| 接手说明 | `HANDOFF.md` |
| 主对标图 | `results/figs/cmp_edm_2step.png` |
| 火焰面图 | `flamelet/flamelets_from_fla.png` |
| 12 条 .fla | `flamelet/*.fla` |

---

# E. 今天 GUI 操作时间线（浓缩）

```
New Project → 拖 Diffusion Flamelet Generator
  → Pre-Processing：Working Dir + Clone 官方 grimech30 + Run Pre-Processor ✅
  → Inlet1 Fuel：T=294，CH4/O2/N2 = 0.25/0.1575/0.5925
  → Inlet2 Ox：T=291，O2/N2 = 0.21/0.79
  → Reactor：P=0.993 atm，χ=50→0.5 (8步) / →200 (3步)
  → Grid：biased，25+40 点
  → Run Calculations → Begin → 12 条 .fla 成功
```

GUI 耗时主要在：系统化学集必须 **Clone 到 Working Dir**；Surface 留空；路径用短路径。
