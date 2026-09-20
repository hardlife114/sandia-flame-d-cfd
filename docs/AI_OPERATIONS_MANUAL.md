# Sandia Flame D 项目 —— AI 操作手册（可复现工作日志）

> 面向对象：接手本项目的另一个 AI 助手
> 目的：**照着做就能复现全部操作**，并避开已经踩过的所有坑
> 最后更新：2026-09-14

---

## 0. 先读这一节：环境与铁律

### 0.1 环境事实

| 项 | 值 |
|---|---|
| 项目根 | `C:\Users\lx\Desktop\fluent_flamed` |
| ANSYS | 2025 R2，`D:\Program Files\ANSYS\2025R2\v252` |
| Fluent CPython | `D:\Program Files\ANSYS\2025R2\v252\commonfiles\CPython\3_10\winx64\Release\python\python.exe` |
| 该 Python 的库 | **有 numpy / pandas**（用官方 PyFluent） |
| WorkBuddy 托管 Python | `C:\Users\lx\.workbuddy\binaries\python\versions\3.13.12\python.exe`，**无 numpy / pandas** |
| 逻辑核 | 12 |
| 求解模式 | 2D 轴对称、双精度、压力基耦合求解器 |

**选择解释器的规则**：
* 只做纯文本/文件操作 → 用托管 Python（快）
* 只要涉及 numpy / pandas（画图、解析 CSV）→ **必须**用 ANSYS 的 CPython

### 0.2 铁律（违反会直接失败）

1. **启动 Fluent 必须带 `start_watchdog=False`**。
   否则 PyFluent 会去启动 watchdog 子进程，在本机抛
   `PermissionError: [WinError 5] 拒绝访问`，连启动都起不来。
2. **不要用 bash 的 `sleep` / `head` / `find` / `grep` / `cat`**。本环境 Git Bash 缺少 coreutils。
   等待用 `python -c "import time; time.sleep(N)"`；查找用 Glob/Grep 工具。
3. **不要从 bash 调 `cmd.exe`**（被安全策略拦截）；PowerShell 的输出捕获不稳定，
   需要看输出时**重定向到文件再读**。
4. **PowerShell 的 `*>` 重定向写出的是 UTF-16LE**，读的时候要 `bytes.decode('utf-16-le')`。
5. **Fluent 读网格后会按"类型+编号"重命名 zone**，文件里写的标签名无效。
   zone 10 的壁面实际叫 `wall-10`，不是 `wall-farfield`。
6. **每次跑 Fluent 之前要先取得用户确认**（用户明确要求过）。
7. 跑完检查残留进程：`fl2520.exe` / `fl_mpi2520.exe` / `cx2520.exe`，
   用 `D:\Program Files\ANSYS\2025R2\v252\fluent\ntbin\win64\winkill.exe <pid>` 清掉。

### 0.3 标准启动模板

```powershell
$A="D:\Program Files\ANSYS\2025R2\v252"
$PY="$A\commonfiles\CPython\3_10\winx64\Release\python\python.exe"
$env:PYTHONPATH="$A\commonfiles\CPython\3_10\winx64\Release\Ansys\PyFluentCore"
Set-Location "C:\Users\lx\Desktop\fluent_flamed"
& $PY scripts\run_edm.py <参数...> *> run\xxx.stdout.txt
```

Python 内部启动方式（所有脚本统一）：

```python
import os
os.environ["AWP_ROOT252"] = r"D:\Program Files\ANSYS\2025R2\v252"
import ansys.fluent.core as pyfluent
s = pyfluent.launch_fluent(
    mode="solver", dimension=2, precision="double",
    processor_count=12,          # 默认吃满全部逻辑核
    ui_mode="no_gui",
    start_transcript=False,
    start_watchdog=False,        # ← 关键
    cleanup_on_exit=True)
```

---

## 1. 项目物理设定（动任何东西前必须知道）

| 项 | 值 | 出处 |
|---|---|---|
| 燃料射流直径 d | 7.2 mm | `flamed_common.D_JET` |
| 计算域 | 720 mm（轴向）× 216 mm（径向）= 100d × 30d | `L_DOMAIN` / `R_DOMAIN` |
| 射流速度 U_jet | 49.6 m/s，T=294 K | Sandia Flame D 实验值 |
| pilot | U=11.4 m/s，T=1880 K，含燃烧产物 | 稳定火焰的关键 |
| 伴流 | U=0.9 m/s，T=291 K | |
| Re | 22 400 | |
| 火焰带径向位置 | r/d 1.3 ~ 6.3（即 r = 9.45 ~ 45 mm） | 实验测量 |
| 化学机理 | 两步总包（Westbrook-Dryer 风格） | `mechanism/ch4_2step_chem.inp` |

机理内容（**不可逆**，这一点后面很重要）：

```
CH4 + 1.5 O2 => CO + 2 H2O      A=5.012E+11  Ea=48400 cal/mol
CO  + 0.5 O2 => CO2             A=2.239E+12  Ea=24000 cal/mol
```

另有变体：`ch4_1step`（单步总包）、`ch4_2step_relaxed`（Ea 降到 20/15 kcal）、
`ch4_2step_ultra`（12/8 kcal）、`grimech30`（完整机理）。

---

## 2. 网格系统

### 2.1 数据模型（`flamed_common.py`）

网格规格是"分段一维布点"，径向和轴向各一套：

```python
MESH_SPECS_V5 = {
    "coarse": {"axial": [...], "radial": [...], "refine": 1.0},
    "medium": {"axial": [...], "radial": [...], "refine": 1.2670},
    "fine":   {"axial": [...], "radial": [...], "refine": 1.7000},
}
```

**段有三种写法**（`gen_mesh.build_axis` 识别）：

| 写法 | 含义 | 用于 |
|---|---|---|
| `(a, b, d)` | 均匀段，间距 d | v1 |
| `(a, b, q, d0)` | 几何渐变，增长比 q，首层 d0（`d0=None` 继承上一段末层） | v2/v3 |
| `{"a":…, "b":…, "d0":…, "d1":…}` | **双端锁定**：首末间距都给定，反解 (n, q) | **v4/v5（推荐）** |

**为什么必须有双端锁定**（v4 修的核心缺陷）：
用 `(a,b,q,d0)` 时 `refine` 只缩首层间距，而 q 固定、段长固定 →
尾层间距几乎不变 → **整段平均间距不缩**，级间加密形同虚设。
实测外场加密比 = **1.000（完全不加密）**。
`{"a","b","d0","d1"}` 让 `refine` 同时缩 d0/d1，整段严格按 1/refine 缩放。

### 2.2 当前三级规格（v5）

| 级别 | refine | 单元数 | h_eff |
|---|---:|---:|---:|
| coarse | 1.0 | 103 912 | 1.008 mm |
| medium | 1.2670 | 207 636 | 0.713 mm |
| fine | 1.7000 | 415 305 | 0.504 mm |

单元数比 1 : 1.998 : 3.997，r21 = 1.4143、r32 = 1.4136（理想 1.4142）。

### 2.3 操作：生成网格

```bash
# 用托管 Python 即可（不依赖 numpy）
python scripts/gen_mesh.py --specs v5
# 输出 mesh/v5/{coarse,medium,fine}.msh + 每个 zone 的面数与类型码清单
```

### 2.4 操作：离线核查级间加密（秒级，不启 Fluent）

```bash
python scripts/mesh_refine_ratio.py --specs v5
```
**必看指标**：`med/crs` 与 `fine/med` 应≈ 0.707。
若某处 = 1.000，说明该段加密失效 —— 立刻停下来查规格。

### 2.5 操作：出网格图

```bash
python scripts/plot_mesh_grids.py --specs v5      # 三级 × 三级放大（轴对称三级网格）
& $PY scripts/plot_mesh_planar.py                 # 全域平面三联图（§11.5b，与 .msh 同源）
```
* 需 ANSYS 的 Python（matplotlib）；中文标注依赖 `plot_style.use_cjk()`（自动注册雅黑）
* 自动抽稀（放大区按目标可视间距取每 N 条线画一条），否则细网格挤成灰团
* 产出 `results/figs/mesh_grids_v5.png` 与 `mesh_compare_v4_vs_v5.png`

**其余网格类脚本（按需）**：

| 脚本 | 用途 |
|---|---|
| `plot_mesh_local.py` | 局部网格对比（v1-medium / v2-coarse / v3-coarse 近口区） |
| `plot_mesh_detail.py` | 网格细节（喷唇特征线落位） |
| `plot_mesh_quality.py` | v1 vs v2 网格质量分布 |
| `plot_refine_ratio.py` | v3→v4 级间比（GCI 前提核查） |
| `plot_grid_cmp.py` | 网格对比图 vs TNF 站位 |
| `plot_mesh_conv_profiles.py` | 网格收敛性剖面 |
| `mesh_audit.py` | 网格审计 → `docs/MESH_AUDIT.md` |
| `mesh_audit_v2.py` | v1/v2 审计（Fluent 实机） |
| `mesh_refine_ratio.py` | 离线级间比（§2.4） |

### 2.6 操作：Fluent 实机核验（读入 + mesh check）

```bash
python scripts/check_mesh_v2.py --specs v5        # 三级依次读入 + mesh check
python scripts/check_mesh.py                      # 单网格快速核查
```
**通过标准**：3 次 `mesh check` 全 Done、0 Error、三个体积都等于
`1.055334e-01 m³`（解析 πR²L）。

### 2.7 边界条件拓扑（v5）

| zone | 名称（文件内） | Fluent 内名称 | 类型码 | 说明 |
|---|---|---|---|---|
| 3 | wall-lip | `wall-3` | 3 | 喷唇壁，500 K |
| 4 | wall-rim | `wall-4` | 3 | 外唇壁，500 K |
| 5 | inlet-jet | `velocity-inlet-5` | 10 | 燃料射流 |
| 6 | inlet-pilot | `velocity-inlet-6` | 10 | pilot |
| 7 | inlet-coflow | `velocity-inlet-7` | 10 | 伴流 |
| 8 | axis | `axis-8` | 37 | 对称轴 |
| 9 | outlet | `pressure-outlet-9` | 5 | **唯一的出口** |
| 10 | wall-farfield | **`wall-10`** | 3 | 外缘固壁 300 K |

> **v5 的域改动**：外缘圆柱面由压力出口改为固壁，只保留流向出口。
> 原因见 §4.2。

---

## 3. 求解：`run_edm.py` 完全参考

### 3.1 参数表

| 参数 | 默认 | 说明 |
|---|---|---|
| `--mesh` | `medium` | 网格级别名（coarse/medium/fine） |
| `--mesh-dir` | `mesh` | 网格目录，如 `mesh/v5` |
| `--flame` | `D` | Flame D/E/F |
| `--mech` | `1step` | `1step` / `2step` / `2step-relaxed` |
| `--model` | `edm` | `edm`（推荐）/ `edc`（**会熄火，别用**） |
| `--edm-only` | False | 只跑 EDM，不切 EDC |
| `--n-cold` | 150 | 冷态（关化学）步数 |
| `--n-edm` | 2500 | 阶段1 步数（请求值，见坑 §6.2） |
| `--n-edc` | 1500 | 阶段2 EDC 步数 |
| `--chunk` | 250 | 每块迭代步数（块间打印监控） |
| `--switch-t` | 0 | >0 时 T_max 达阈值提前切模型 |
| `--pseudo-scale` | 1.0 | 伪瞬态时间步缩放（**0.5 更稳**） |
| `--urf` | 0 | 能量/组分欠松弛（**0.5，强烈建议给**） |
| `--cores` | os.cpu_count() | 并行核数 |
| `--skip-hot` | False | 入口直接用文档温度（跳过热态自持阶段） |
| `--edc-tau` `--edc-cxi` `--edc-pasr` | — | EDC 常数/PaSR（**已证无效**） |
| `--avg-from` `--avg-count` | 0 | 周期采样（用户已要求**停用**） |

### 3.2 **现行稳定协议**（复制这条就能跑出收敛解）

```bash
python scripts/run_edm.py --mesh coarse --mesh-dir mesh/v5 --skip-hot \
       --mech 2step --edm-only --flame D \
       --n-cold 250 --n-edm 1500 --chunk 100 \
       --pseudo-scale 0.5 --urf 0.5
```

**成功判据**（看日志）：
```
[EDM 100/1500]  T_max=2220.8 K  T_axis=2095.7 K  CO2_max=0.1439  r@Tmax=1.41d
[EDM 1500/1500] T_max=2220.8 K  ... （100→1500 步温度变化 < 0.1 K）
残差 continuity≈7.4e-04  energy≈5.2e-09
判定：**火焰建立**
```
耗时：coarse 约 75 s（0.05 s/步，12 核）。

### 3.3 日志监控怎么做

`run_edm.py` 每 `--chunk` 步打印一行，含 T_max / T_axis / CO2_max / r@Tmax
**和实时残差**（`res_str()` 从转录 `run/trn_edm.txt` 里解析最近一次迭代）。
残差解析函数是 `last_residuals()`，可独立复用。

---

## 4. 燃烧模型的结论（这一段能省你几天时间）

### 4.1 起点：稳态 EDM 的极限环

v4-coarse 按朴素协议跑到 2000→2250 步之间**熄火**（T_max 2272→357 K）。
降伪瞬态步长后看清是**极限环**：周期 ≈250 步，`T_axis` 在 291↔386 K、
`r@Tmax` 在 0↔1.39d 之间摆动。**任何单张快照都是随机相位的照片。**

**不要**用"周期采样平均"去掩盖它（用户已明确否决这个做法），要去找根因。

### 4.2 根因：外缘开边界

旧拓扑外缘是压力出口，日志里出现 **2107 次 `Reversed flow`，最多占该面 100% 面积**。
改成固壁（§2.7）+ 补欠松弛 0.5 之后，**EDM 完全稳定**，极限环消失。

> 结论：振荡不是 EDM 模型的问题，也不是网格的问题，是**边界条件**。

### 4.3 EDC：全部失败，不要再试

| 组合 | 做法 | 结果 |
|---|---|---|
| 冷流 + 1880 K pilot → EDC 直启（生产机理） | `--model edc` | ❌ 熄火，T_max 恒 358 K |
| 同上，relaxed 机理（Ea 20/15 kcal） | `--mech 2step-relaxed` | ❌ 同 |
| EDM 点火后切 EDC（生产机理） | `--n-edm 800 --n-edc 2000` | ❌ 切换即熄 |
| EDM 点火后切 EDC（relaxed） | 同上 + relaxed | ❌ 同 |
| EDC + PaSR | `--edc-pasr` | ❌ 参数值不被接受（`Value is not allowed`） |
| EDC + C_τ = 3.0 | `--edc-tau 3.0` | ❌ 完全无反应（358.0 K 一条直线） |

**根因**：EDC 的反应只发生在湍流"细丝"里，体积分数小、停留时间极短；
两步总包机理（不可逆、Ea 48 kcal）在这个配置下算不出足够的反应速率。
降活化能（relaxed）也没用。

### 4.4 finite-rate/EDM：更差，排除

组合模型 min(EDM, Arrhenius) 实测平均 RMS 919 K（纯 EDM 是 412 K）——下游火焰被冻死。

### 4.5 精度天花板

| 模型 | x/d=3 | 15 | 30 | 45 | 60 | 平均 RMS |
|---|---:|---:|---:|---:|---:|---:|
| EDM（v1-coarse） | 290 | 922 | 584 | 133 | 134 | 413 |
| EDM（v5-coarse，2× 单元） | 282 | 898 | 587 | 175 | 119 | **412** |

**关键判断：网格翻倍后 RMS 几乎不变（413 → 412）→ 误差已完全由 EDM 模型决定，
加密网格不再有意义。** 要提精度必须换模型（火焰面 / GRI+EDC / 非定常）。

---

## 5. 后处理

```bash
# 多网格精度对比（表 + 三联图）
python scripts/accuracy_compare.py --specs v5

# 网格收敛性 GCI（Roache，支持非等距加密比）
python scripts/gci_analysis.py --specs v5 --tag v5

# 三级剖面叠合 vs TNF 实验
python scripts/plot_mesh_conv_profiles.py --specs v5 --tag v5

# 单算例多组分对标
python scripts/plot_cmp_detail.py --cfd results/cfd_edm_d_v5_coarse_2step_c_only_fo.csv --tag mycase
```

**RMS 口径**（所有脚本必须一致）：把 CFD 径向剖面插值到实验 r/d 上求均方根，
限制 r/d ≤ 4.5，且只在实验点落在 CFD 覆盖范围内时计算。

**GCI 的关键细节**：
* `h_eff = sqrt(V_domain / N_cells)`，`V_domain = 1.055334e-01 m³`
* 指标必须是**线性泛函**！"径向温度最大值"是非线性的——峰值位置在振荡，
  场平均会把峰抹平，且抹平程度随网格变化。
  应用**固定空间位置取值**或**径向积分**（脚本已实现）。
* 中远场（x/d ≥ 30）网格依赖性**非单调**，Roache 公式无解 → 如实报告，不要硬算。

---

## 6. 坑清单（最有价值的一节）

### 6.1 Fluent 相关

| 坑 | 现象 | 解法 |
|---|---|---|
| watchdog 启动失败 | `PermissionError WinError 5` | `launch_fluent(..., start_watchdog=False)` |
| zone 改名 | `'wall' has no attribute 'wall-farfield'` | Fluent 按类型+编号命名 → 用 `wall-10` |
| URF 设置无效 | `api-get-var: the object is not active` | 耦合求解器下 settings API 不可用，**回退 TUI**：`/solve/set/under-relaxation/<eq> <val>`（energy/k/epsilon/各组分全部可设） |
| `iterate()` 提前停 | 日志说 2000 步，实际只跑 217 步 | Fluent 达收敛判据就停；**日志里"步数"是请求数不是实际数**。熄火态残差掉得快，尤其明显 |
| 残差突跳 | 迭代计数连续，残差突然 ×400 | 这是**新方程/新模型投入求解**（如打开组分方程）的正常响应，不是失稳。判据：转录里该行前面有 `Integrating chemistry` 等事件行 |
| 网格质量 | 单元段取值必须为 3 | 实测：4 → SIGSEGV，2 → Failed in Fill_Domain |
| 残留进程 | 下次启动失败/占 CPU | 跑完用 `winkill.exe <pid>` 清 `fl2520`/`fl_mpi2520`/`cx2520` |
| **后台 PowerShell 宿主静默杀运行** | `run_in_background` 后台跑 run_np_eq.py，2–3 分钟内进程无声消失：无 Windows 崩溃事件、无 python traceback、无 Fluent trn，日志停在前几个 chunk | **长求解一律前台分段接力**（见 §11.5），每段 ≤9 min、段间落盘 dat 续算。注意：2026-09-15 上午同方式曾成功 32 min，属随机存活，不可依赖 |
| **★ 进程随机外部击杀（2026-09-15 下午定性）** | 前台/后台**都会**被随机硬杀：python 静默消失（无 traceback）、Fluent 转录无异常戛然而止（残差健康）、**Fluent 本体在 python 死后仍继续算几分钟**（trn 时间戳 > capture 时间戳）；Defender/系统事件/许可证日志全部无记录。实测寿命 3.5–10.4 min 随机，无法建立安全阈值 | 三层防御：①`--autosave-every 100` 每 100 步落盘 `<tag>_as.dat.h5`；②`driver_dense.py` 监督循环（subprocess 逐段跑，段死自动 `--resume --resume-data <tag>_as.dat.h5` 续跑，损失 ≤100 步）；③Start-Process/WMI 分离进程**均被 WorkBuddy 安全策略静默拦截**（`-PassThru` 返回空 PID / CIM 被拒），不要浪费时间尝试 |
| **PowerShell 前台 timeout 会杀整棵进程树** | 前台命令超时（timeout 参数到点）→ python+Fluent 全被杀，返回 exit 1，**无超时提示**（表现为"静默失败"） | 每段预算 = timeout − 2 min 缓冲。17:38:19/17:57:42 两例死亡时刻与 timeout 精确吻合（对照 trn 最后写入时间） |
| driver 起子进程秒退 rc=1 | `driver_dense.py` 里 subprocess 调 run_np_eq 报 `ModuleNotFoundError: No module named 'ansys.fluent'` | **driver 必须显式传 `env=` 并写入 PYTHONPATH**（继承链断在 driver 的启动命令没设 $env:PYTHONPATH） |
| `check_convergence` 回读是对象不是 bool | 0.30.5 里 `eqs[name].check_convergence` 赋值 `=False` 不报错，但回读得到 `<settings_252.check_convergence object>`；只凭"赋值成功"判断已关闭不可靠 | 赋值后再取 `.value.get_state()`（或对象 `get_state()`）拿真值回读，7 个方程全 False 才算关干净（`run_np_eq.py::disable_residual_autostop` 已内置） |
| 收敛判据≠只有方程级一层 | 怀疑 iterate 被判据提前返回时，用**计时法**检验：`iterate(30)` 正常应 ≈0.8 s/步（planar medium）；若 <5 s 返回即被判据拦截 | 2026-09-15 实测关掉判稳后 iterate(30)+iterate(70) 均跑满（0.76–0.80 s/步）——`check_env_solver.py` T5/T7 |

### 6.2 代码与工具

| 坑 | 解法 |
|---|---|
| 托管 Python 无 numpy/pandas | 凡涉及数值/画图，改用 ANSYS 的 CPython |
| `build_axis()` 返回 list | 乘标量前先 `np.asarray()` |
| 改规格后级间比不对 | 单元数≈refine^2.71（整数取整），refine 因子必须**数值反解**（`scripts/dev/_solve_v5.py`） |
| ANSYS 的 matplotlib 无中文字体 | `from plot_style import use_cjk; use_cjk()`（注册微软雅黑） |
| PowerShell `*>` 输出是 UTF-16LE | 读文件用 `decode('utf-16-le')` |
| PowerShell 输出捕获不稳 | 重定向到文件再读；**更严重时 stdout 全空**——一切结论以脚本自己落盘的 log/flag 文件为准（`Out-File -Encoding utf8` 捕获 traceback、结尾再写一个 `*_flag.txt` 判完成） |
| plot 脚本 `--cfd` 参数 | 传**相对 results/ 的文件名**（脚本内部 `RES / a.cfd` 自动拼前缀），带 `results/` 前缀会变成双重路径 FileNotFound |
| bash 无 coreutils | 无 `sleep`/`head`/`dirname`；等待用 python `time.sleep` |
| 大段代码编辑 | 先用 Read 看全文，确认精确后再 Edit |
| `df.T` | 是转置，不是名为 T 的列 → 用 `df['T']` |

### 6.3 物理/建模

| 坑 | 说明 |
|---|---|
| 外缘开边界 | 射流问题的外场出口会产生大面积回流 → 稳态解振荡。**改固壁** |
| 无欠松弛 | URF=1.0 时火焰根部易过冲；0.5 明显更稳 |
| EDM 高估温度 | 纯混合控制，近场（x/d=15）RMS ~900 K 是模型固有 |
| 只加密网格不换模型 | 误差不会改善（见 §4.5） |

### 6.4 非预混（Non-Premixed）模型：GUI-only，且有循环依赖

**`execute_tui` 对无效命令不抛异常**（只在转录里打 `Error: invalid command`）。
所以任何 TUI 探测**必须开转录并逐条读回显**，否则会把"命令没生效"误判成"静默拒绝"。

非预混使能是**循环依赖**，headless 无解（详见 `docs/NP_HEADLESS_BLOCKER.md`）：

```
设 model=non-premixed → 立即校验燃料流分数 → 分数为 0 → 回滚
填分数 → 需要 partially_premixed_model_options 等节点
        → 这些节点"not active"，模型启用后才激活
```
GUI 的 Species 对话框把"选模型 + 填 Boundary"放在同一事务（点 OK 才校验），只有它能破环。

**进 GUI 前的两个隐患（会让操作失败）**：
1. **默认边界物种表是 `ch4, h2, jet-a, n2, o2`，没有 `h2o`**。方案 A 的氧化剂流（湿空气）
   含 H2O 0.006256 → **必须先 Add `h2o`**，否则氧化剂流分数凑不到 1。
2. **`run/np_eq_pregui.cas.h5` 未导入任何机理**（`prep_np_pregui.py` 里没有 `import_chemkin`），
   其 `mixture-template` 只有 `h2o o2 n2`。若 GUI 里 Add `ch4` 失败，
   先导入一次机理（`species.import_chemkin(...)`，参数见 `run_edm.py`）再进 Species 面板。

**方案 A 的流组分（Sandia Flame D）**：

| | CH4 | O2 | N2 | H2O |
|---|---:|---:|---:|---:|
| Fuel 流（=jet） | 0.15637 | 0.19650 | 0.64713 | — |
| Oxid 流（=湿空气伴流） | — | 0.23574 | 0.75800 | 0.006256 |

Species Unit 选 **Mass Fraction**；Temperature：Fuel 294 K、Oxid 291 K；
Chemistry 标签 State Relation = **Equilibrium**。

**GUI 启动限制**：代理/命令环境派生的 Fluent GUI **必在图形初始化阶段闪退**
（本机 AMD 核显，dx11 与 opengl 均崩；journal 读 case 本身总是成功）。
→ **必须由用户从 Fluent Launcher 启动**。

---

## 7. 从零复现的完整步骤

```bash
# ① 生成网格
python scripts/gen_mesh.py --specs v5

# ② 离线验证级间比（应为 0.707）
python scripts/mesh_refine_ratio.py --specs v5

# ③ 出网格图
python scripts/plot_mesh_grids.py --specs v5

# ④ Fluent 实机核验（3 次 mesh check，0 Error）
python scripts/check_mesh_v2.py --specs v5

# ⑤ 求解（现行稳定协议，coarse 约 75 s）
python scripts/run_edm.py --mesh coarse --mesh-dir mesh/v5 --skip-hot \
       --mech 2step --edm-only --flame D \
       --n-cold 250 --n-edm 1500 --chunk 100 --pseudo-scale 0.5 --urf 0.5

# ⑥ 精度对比 + 图
python scripts/accuracy_compare.py --specs v5

# ⑦ （可选）medium / fine 同样跑，然后做 GCI
python scripts/gci_analysis.py --specs v5 --tag v5
```

每一步的预期输出与通过标准见前文对应小节。

---

## 8. 目录约定（新增文件请遵守）

| 目录 | 放什么 |
|---|---|
| `docs/` | 所有文档；`docs/handover/` 放跨项目汇总 |
| `scripts/` | 生产脚本；`scripts/dev/` 放探测/废弃脚本 |
| `mesh/<specs>/` | 各代网格 `.msh` |
| `results/` | 分析产出 `.csv`；`results/figs/` 放图 |
| `run/` | 单次运行的日志/stdout/case/data |
| `logs/` | Fluent 转录 `.trn`、cleanup bat、错误日志 |
| `mechanism/` | 化学机理 |

**根目录只放 `README.md`**。任何临时文件用完即清。

---

## 9. 交付状态与待办

**已完成**：v2→v5 网格演进（含修复级间加密缺陷）、v5 三级网格实机核验、
振荡根因定位（开边界）、v4 三级 GCI（近场 GCI 0.49 %）、EDC 路线彻底排除。

**现行最佳解**：`results/cfd_edm_d_v5_coarse_2step_c_only_fo.csv`
（EDM + 生产机理 + 固壁 + URF 0.5 + 12 核，T_max = 2220.8 K 恒定，残差收敛）

**待办**：
1. 用现行协议推 v5 medium（~20 min）/ fine（~40 min），出正式 GCI
2. 若要提精度，换燃烧模型（火焰面 / GRI+EDC / 非定常）—— 网格已不是瓶颈
3. `docs/report.md` 仍是 SLFM 口径，需按现结论改写

---

## 10. 非预混 baseline 进行中（2026-09-14 追加）

### 10.1 目标与决策
Equilibrium + β-PDF 快速 baseline，与 EDM 412 K 同网格（v5-coarse）同协议对比。
方案 A 口径（TNF 标准）：fuel 流 = ch4 0.15637 / o2 0.19650 / n2 0.64713；
oxidizer 流 = o2 0.23574 / n2 0.75800 / h2o 0.006256；
入口 f：jet 1.0 / pilot 0.27（文档值）/ coflow 0，方差 0。

### 10.2 新坑（先读再动手）

| 坑 | 现象 | 解法 |
|---|---|---|
| 非预混无法 headless 使能 | `? yes` 报 "Fuel species sum to 0"；settings `option` 赋值静默失效；DB 无 methane-air 混合物 | **GUI Species 面板点一次**（与 flamelet import 同模式），另存种子 case 后 headless 续作。14 次探测证据：`run/probe_np1..14.log`（脚本在 `scripts/dev/probe_np*.py`） |
| 代理环境派生 Fluent GUI 必闪退 | Start-Process 启动 fluent.exe：读 case 成功、图形初始化即崩（dx11 / opengl 都崩） | **GUI 一律由用户从 Fluent Launcher 手动启动**；journal 方式（`-i xxx.jou` 内 `/file/read-case`）只用于 headless 读 case |
| 看门进程双触发 | 两个 watcher 同时等同一文件 → 求解被启动两次 | 换看门前先停旧的（TaskStop），再起新的 |

### 10.3 现场状态与自动链
- `run/np_eq_pregui.cas.h5`：除 Species 面板外全部就绪的前置 case（k-ε realizable +
  EWT、操作压、入口速度/温度/湍流、壁温 500/500/300、出口 0 Pa、已混合初始化）
- 用户 GUI 完成 Species 面板后另存 `run/np_eq_seed.cas.h5`
- 看门进程检测到种子 case → 自动 12 核运行 `scripts/run_np_eq.py`
  （含种子校验：模型未激活会拒绝运行）→ `results/cfd_npeq_d_v5_coarse.csv`
- 收尾对比：`python scripts/compare_np.py` → `results/rms_model_compare.csv`
  （np_eq vs EDM vs TNF，温度 RMS x/d=3/15/30/45/60）

## 11. 非预混运行命令总手册（2026-09-15 追加；重要命令一一检验过）

> 所有命令的工作目录都是项目根 `C:\Users\lx\Desktop\fluent_flamed`。
> 解释器固定为 ANSYS CPython（§0.3 三要素：CPython + PYTHONPATH + watchdog=False），
> 下文记 `$PY` 与 `$env:PYTHONPATH`，不再重复。

### 11.0 ★★ 计算卡规范（铁律，2026-09-16 用户明示）

> **用户原文**："这是重大错误，需要在以后每一次计算时避免，其中进口边界条件的设置
> 在计算卡中必须明确与当前算例符合，这是核心要求。"

**任何大规模计算前提交计算卡，其中"边界条件"部分必须满足**：

1. **逐项完整**：每个边界 × 每个参数（U / I / Dh / T / 组分质量分数 / 压力），
   缺项即为不合格的计算卡。
2. **逐项对照**：每个参数列三列——【算例定义值（来源）】【本次计算取值】【一致性】。
3. **三类值区分标注**（严禁混同）：
   * **算例定义值**：权威来源，如 Flame D 文档 `jet 294 K / pilot 1880 K(±50) /
     coflow 291 K` 与 `Y_JET / Y_PILOT / Y_COFLOW`（`flamed_common.py`）；
   * **启动策略临时值**：如热态 1100 K —— 必须写"临时，须在自持段切回"；
   * **近似值**：如 pilot 用平衡态组分 —— 注明近似依据与已知影响。
4. **禁止**用脚本默认参数冒充算例定义；**移植既有脚本必须通读完整阶段序列**
   （启动 → 自持/维持 → 导出）——只取前半段是 2026-09-15 3D 事故的根因。
5. **提交前**从脚本实际参数反查（不凭记忆）；**计算后**用
   `scripts/inspect_inlets.py` 从 case 回读核对（逐项 + 组分总和）。
6. **Flame D 标准进口口径（权威表，任何 Flame D 类计算照此核对）**：

   | 边界 | U | I | Dh | **文档温度** | 组分（质量分数） |
   |---|---|---|---|---|---|
   | jet | 49.6 m/s | 8.79% | 7.2 mm | **294 K** | ch4 .15637 + o2 .19650 + n2 .64713 |
   | pilot | 11.4 m/s | 10.92% | 10.5 mm | **1880 K** | o2 .054 + co2 .1098 + h2o .0942 + co .00407 |
   | coflow | 0.9 m/s | 1.0% | 0.30 m | **291 K** | o2 .23574 + h2o .006256 + n2 .758 |
   | 喷嘴壁 lip/rim | — | — | — | 500 K | — |
   | 远场壁 | — | — | — | 300 K | — |
   | 出口 | — | — | — | — | p_gauge = 0 |

   启动策略（EDM 类）：三进口临时 1100 K → 建成火焰后**必须切回文档值跑自持段**
   （`run_box3d_edm.py --hold`）。

### 11.1 启动方式三要素（每次运行前自查）

```powershell
$A = "D:\Program Files\ANSYS\2025R2\v252"
$PY = "$A\commonfiles\CPython\3_10\winx64\Release\python\python.exe"   # 3.10.16
$env:PYTHONPATH = "$A\commonfiles\CPython\3_10\winx64\Release\Ansys\PyFluentCore"  # ★ 无它 import 必败
Set-Location C:\Users\lx\Desktop\fluent_flamed
```

验证（一次即可）：`& $PY -c "import ansys.fluent.core as p; print(p.__version__)"` → `0.30.5`。
PyFluent 以**目录包**形式装在 `Release\Ansys\PyFluentCore`，v252 全树无 `ansys_fluent_core`
dist-info、各系统 Python 均无 —— **永远不要走 pip 安装路线**。

### 11.2 运行方式矩阵（run_np_eq.py）

| 场景 | 命令要点 | 说明 |
|---|---|---|
| 轴对称基线（coarse/medium/fine） | `& $PY scripts\run_np_eq.py --cores 10 --tag np_eq_d_v5_medium --n-iter 3000 --min-steps 1500 --conv-tol 1e-3` | 读 seed + hybrid 初始化；seed 决定网格 |
| 换网格（GCI / 全域 planar） | 追加 `--mesh-msh mesh/v5/medium.msh`（planar 用 `mesh/planar_full/medium.msh`） | `replace_mesh` 跨拓扑可保留 np 模型（planar 全域实测成功） |
| 全域 planar | 追加 `--planar --pdf np_eq_seed.pdf` | axis-8→symmetry + `two_dim_space=planar`；镜像入口 -14/-15 自动探测并同步设置 |
| **续算**（推荐） | `--resume <tag 或路径>` | 读上一轮 case+data，跳过换网格/初始化；BC 幂等重申。三种写法：tag 名 / `run\xxx` / 绝对路径 |
| 二阶协议（一段式） | 追加 `--so-step 500` | 前 500 步一阶启动，之后动量/k/ε/fmean/fvar 切二阶（压力恒二阶） |
| 二阶（接力段） | `--so-at-start` | 启动即二阶，跳过 force_first_order（接力第 2+ 段专用） |
| 关判据防早停 | 默认已内置（7 方程回读全 False） | 若日志出现"★ FAIL: 仅 n/7"立即停下排查 |

运行日志：`run/log_<tag>.txt`（主日志）、`run/trn_<tag>.txt`（Fluent 转录）——按 tag 分文件，**多会话不要共用**。

### 11.3 已验证的一键命令（现行基准）

```powershell
# 轴对称二阶基准（medium，RMS 215.0 K，判稳 1700 步，~16 min）
& $PY -u scripts\run_np_eq.py --cores 10 --mesh-msh mesh/v5/medium.msh `
  --tag np_eq_d_v5_medium_so --n-iter 3000 --min-steps 1500 --conv-tol 1e-3 --so-step 500

# 全域 planar 一阶（RMS 475.4 K，2000 步跑满）
& $PY -u scripts\run_np_eq.py --cores 10 --mesh-msh mesh/planar_full/medium.msh `
  --planar --tag np_eq_d_v5_planar_full --n-iter 2000 --min-steps 500
```

### 11.4 后台 vs 前台（2026-09-15 血泪结论）

- `run_in_background` 后台方式**两次**在 2–3 min 内静默死亡（无事件/无 traceback/无 trn；
  上午同方式曾成功 32 min，随机存活不可依赖）。
- **长求解一律前台分段接力**：每段 ≤9 min（PowerShell 工具前台超时上限 10 min），
  段末自动落盘 `run/<tag>.cas.h5/.dat.h5`，下一段 `--resume` 接力。
- 每段命令末尾接 stdout 捕获 + 完成旗标（脚本 print 全双写 log_<tag>.txt，旗标只判"跑完没崩"）：
  `... 2>&1 | Out-File run\legN_capture.txt -Encoding utf8; "DONE" | Out-File run\_legN_flag.txt -Encoding ascii`

### 11.5 分段接力标准协议（实测模板：全域 planar 二阶，共 2 段 ~17 min）

```powershell
# 第 1 段：从一阶收敛解续算；200 步一阶缓冲 + 200 步二阶；禁早停（判据跨段会误判）
& $PY -u scripts\run_np_eq.py --resume np_eq_d_v5_planar_full `
  --tag np_eq_d_v5_planar_full_so --cores 10 `
  --n-iter 400 --min-steps 999999 --so-step 200 `
  --out-pts 0,2,4,6,8,10,15,20,30

# 第 2 段（及以后）：--so-at-start 纯二阶接力；段间看 log 里 T_max/T_axis 是否冻结
& $PY -u scripts\run_np_eq.py --resume np_eq_d_v5_planar_full_so `
  --tag np_eq_d_v5_planar_full_so --cores 10 `
  --n-iter 380 --min-steps 999999 --so-at-start `
  --out-pts 0,2,4,6,8,10,15,20,30
# 收尾段想用判据：--min-steps 0 --conv-tol 1e-3（判稳 break 后导出）
```

步速参考（planar medium 415k 单元、10 核）：一阶 0.76–0.95 s/步，二阶 1.09 s/步。
判稳标志：T_max/T_axis/CO2_max 监测点连续 3 次采样完全冻结（0.00% ≪ 0.1% 阈值）即可停。

### 11.5b 反应区加密网格（medium_dense，2026-09-15 追加）

```powershell
# 生成（532,524 单元，+28%；面积校验自动）
& $PY scripts\gen_mesh_planar.py --dense    # → mesh/planar_full/medium_dense.msh
```

* 加密设计依据 `planar_error_mechanism.py`：火焰片半宽到 75d 处 10.2d(73mm)，
  原 v5-medium 径向 y>45mm 后 ~4.6mm（剪切层每半宽仅 ~12 网格）。
* 加密内容（基准 = v5-medium 等效间距，即规格值 ÷1.2670，**近口段不回退**）：
  径向 seg4 [9.45,45mm] d1 0.2755→0.2119mm；**新增 seg5 [45,80mm] d1=0.75mm**；
  seg6 [80,130] 4.68→2.6mm。轴向 [80,300] 1.70→1.36、[300,600] 7.87→4.92、[600,720] →6.5。
* ★ 坑：dense 段表若用原始规格值（refine=1.0），近口段会比 v5-medium 粗 27%
  （0.164 vs 0.124mm 首层）——**所有间距必须先除以 refine 换算成等效值**。
* 求解：`scripts/driver_dense.py` 监督循环（段死自动续），或按 §11.5 手动接力。
  tag = `np_eq_d_v5_planar_full_dense`；步速 ~1.2 s/步（一阶）/ ~1.9 s/步（二阶）。
* **实战结果（2026-09-15 19:08，driver 6 段 47.5 min 一次通过零被杀）**：
  280 一阶 + 1240 二阶，段 6 内 T_max/T_axis 监测点完全冻结（收敛）。
  **五方逐站 RMS（station_rms_so_compare.py）**：dense 465.7 vs medium 463.5 K
  （前 7 站差 ≤1 K，仅 x60/x75 差 1–2.7%）——**反应区加密不改变解，
  medium 网格已是网格无关解**；平面解 463.5 K 误差确证为几何-物理结构性
  （2D 平面 vs 轴对称），与网格分辨率无关。
* 插值初场路线（`prep_dense_init.py`，write/read-interpolate）**未打通**：
  0.30.5 的 `settings.file` 与 `s.tui.file` 下只有 `interpolate` 一个名字，
  字符串 TUI `/file/write-interpolate <file>[ yes][ ()]` 三种形态均不落盘
  （疑似交互挂起）；继续探索时应先 `dir()` 探测再逐一试参数形态。

### 11.6 行为检验（怀疑环境/判据/新机器时先跑这个）

```powershell
& $PY -u scripts\check_env_solver.py     # T1 import … T9 存盘往返，11 项 PASS/FAIL
# 结果：run/check_env_solver.log（结论行）+ run/trn_check_env.txt（含 TUI 判据 dump）
```

覆盖：import / launch / 续算读入 / 判据层级回读 / **iterate 计时法**（30 步 ≈24 s 为跑满，
<5 s 即被判据拦截）/ field_data 线读取 / 二阶切换回读 / write-read 往返。

### 11.7 后处理命令集（全部用 ANSYS CPython）

```powershell
# 单解 vs TNF 实验：6 站径向 + 中心线（--cfd 传相对 results/ 的文件名！）
& $PY scripts\plot_solution_vs_tnf.py --cfd cfd_np_eq_d_v5_planar_full_so.csv --tag planar_full_so
#   → results/figs/planar_full_so_radial.png / _centerline.png

# 四方逐站 RMS 表（全域二阶/一阶 vs 轴对称二阶/一阶）
& $PY scripts\station_rms_so_compare.py     # → results/station_rms_so_compare.csv

# 平面 vs 轴对称云图/剖面三联 + 精度表
& $PY scripts\plot_planar_compare.py ;  & $PY scripts\accuracy_axisym_vs_planar.py

# 全场 rake 提取（34 横线 → npz，供云图）
& $PY scripts\extract_fields2.py --case run/<tag>.cas.h5 --data run/<tag>.dat.h5 --out field_xxx

# 进口站 x/d=0.75 六组分对比（轴对称 / 全域平面两个版本）
& $PY scripts\check_inlet_station.py ;  & $PY scripts\check_planar_inlet_station.py

# PDF 表内容核查（流组分/绝热/f_st）
& $PY scripts\check_pdf_table.py run\np_eq_seed.pdf

# 网格可视化（全域平面三联图：全域/近场/喷嘴细节，与 .msh 同源数据）
& $PY scripts\plot_mesh_planar.py            # → results/figs/mesh_planar_full.png

# 平面误差机理图（峰值衰减 + 半宽增长 vs 实验/轴对称 + 理论标度线）
& $PY scripts\planar_error_mechanism.py      # → results/figs/planar_error_mechanism.png

# 误差预算分解（分段 RMS + 关键标量偏差 + 轴线分解）
& $PY scripts\error_budget.py                # → results/figs/error_budget.png
#   + results/error_budget.csv（逐站）+ results/error_budget_scalars.csv（标量偏差）

# 欠迭代 vs 真收敛对比（395 步假收敛 vs 3000 步 vs TNF）
& $PY scripts\plot_medium_395_vs_3000.py

# 2D 场云图（T/组分，轴对称或平面）
& $PY scripts\plot_field.py --case run/<tag>.cas.h5 --data run/<tag>.dat.h5 ...

# 多解站位误差表（np_eq vs edm vs TNF；相对误差版）
& $PY scripts\station_errors.py ;  & $PY scripts\station_rel_errors.py

# 场数据逐点比较（EDM vs np_eq 的 CSV 差分）
& $PY scripts\compare_f_field.py

# 全场提取（早期版，轴对称/平面通用）
& $PY scripts\extract_fields.py --case ... --data ...
```

> 绘图字体：所有 matplotlib 脚本开头调 `from plot_style import use_cjk; use_cjk()`
> （`scripts/plot_style.py`，注册微软雅黑；ANSYS CPython 的 matplotlib 无中文字体，
> 不调会方框乱码）。

### 11.8 当前基准数字（2026-09-15 16:40 更新）

| 解 | 全站温度 RMS | 备注 |
|---|---:|---|
| **轴对称·二阶（medium_so）** | **215.0 K** | 现行最佳基准；峰值 2021.9 K @37.2d（模型误差显现） |
| 轴对称·一阶（medium_full3k） | 227.0 K | 真 3000 步 |
| **全域平面·二阶（planar_full_so）** | **463.5 K** | 本次；T_axis@30d 772.5 K，二阶较一阶仅 −2.5% |
| 全域平面·加密网格（planar_full_dense） | 465.7 K | 532k 单元反应区加密；前 7 站与原网格差 ≤1 K |
| 全域平面·一阶（planar_full） | 475.4 K | 双火焰片结构 |

结论：二阶对 planar 解改善很小（463.5 vs 475.4）——平面 2D 的误差是**结构性的**
（无 r² 面积增长 → 火焰片抬离轴线、下游不衰减），数值格式不是主要矛盾；
**轴对称假设对 Flame D 不可替代**。

### 11.9 误差来源量化结论（2026-09-15，error_budget.py）

**分段 RMS（轴对称二阶基准 215.0 K）**：近场(0.75–3d) 209 / **中游(15–45d) 297** /
远场(60–75d) 104 —— 误差集中在中游（火焰发展区）。

**关键标量偏差（轴对称二阶 vs 实验）**：
| 指标 | 实验 | CFD | 偏差 |
|---|---:|---:|---:|
| 中心线峰值 T | 1938 K | 2021.9 K | **+4.3%** |
| 峰位 x/d | 45 | 37.2 | **−17.4%**（火焰偏短） |
| 轴线 T @15d | 498 K | 714 K | **+43.4%** |
| 轴线 T @30d | 1339 K | 1848.7 K | **+38.1%** |
| 轴线 T @45d | 1938 K | 1835.3 K | −5.3% |

**归因排序**（量级为工程估计）：
1. **平衡化学（无限快、不可熄火）≈ 主导（~120–150 K）**：轴线中游 +38~43% 意味火焰
   在轴线上"过早点燃、发展过快"（实验是抬升型逐步点亮）；近场 CO 高估 4.5–6×、
   火焰面过窄（CH4 截断 r≈0.8 vs 实验 1.5）皆为同一根源。
2. **绝热假设（模型强制禁能量方程+辐射，~40–60 K）**：无热损失 → 峰值 +4.3%。
3. **β-PDF/k-ε 交互简化**：局部熄火缺失 → 火焰偏短 17.4%。
4. **进口/边界（~10–30 K）**：氧化流湿空气 H2O 1% vs TNF 4%（f_st +1.3%）、
   pilot 用平衡态近似（实验含 CO/H2 残留）——待 GUI 修正。
5. **数值（≤10 K）**：已基本消除（真收敛 + 二阶 + GCI 0.051% + 加密不变解）。
6. 实验不确定度 ±3–5%（TNF 数据自身）。

（完整数据：`results/error_budget.csv` 逐站、`results/error_budget_scalars.csv` 标量偏差；
图 `results/figs/error_budget.png`。）

### 11.9b 为什么轴对称 2D 可行、平面 2D 不可行（结论性认知，勿再试平面）

**核心：这不是"2D 精度不够"，而是平面 2D 换掉了物理问题本身。**

* **轴对称 2D = 圆射流的精确维度约化**：方程保留柱坐标面积项
  `(1/r)·∂(rρv)/∂r`。这一项编码了"周向面积 ∝ r"的真实几何 →
  卷吸 ∝ x、中心温度差 ΔT ∝ **1/x**，与 Sandia 圆射流实验的几何完全一致。
  少算的那个维度是**利用对称性**省掉的，物理没有被近似掉。
* **平面 2D = 无穷宽片射流（狭缝）**：面积项不存在 → 卷吸 ∝ √x、
  ΔT ∝ **1/√x**（衰减慢得多）、半宽增长更快。拿它去对标圆射流实验，
  等于用"片射流"回答"圆射流"的问题。
* **实测对照（同为二阶、真收敛、同网格量级）**：
  轴对称 RMS 215.0 K（峰值 2021.9 @37.2d，衰减趋势同实验）；
  平面 RMS 463.5 K（峰值恒定 ~1795 K 平推出口、轴线掏空 772 vs 1940 K、
  双火焰片不闭合）。平面解另叠加约 +250 K 的几何结构性误差。
* **不可通过数值手段补救**：反应区加密（532k 单元）解不变（465.7≈463.5）、
  二阶仅改善 2.5%、GCI 中位 0.051% —— 网格/格式/收敛已排除，
  平面框架内无解，只能上真 3D。
* **实践含义**：Flame D 及一切圆射流/旋流燃烧器对标必须用轴对称 2D（或 3D）；
  平面 2D 仅适用于狭缝/长条构型。这解释了为何 2026-09-15 的全域平面
  测试只能作为"验证轴对称假设必要性"的反例，不能作为对标基准。

### 11.10 数据准备与模型对比脚本

| 脚本 | 用途 | 备注 |
|---|---|---|
| `parse_tnf.py` | 解析 TNF pmCDEF 原始数据（Sandia/TUD Flame D）→ CSV | 不启 Fluent |
| `qc_tnf.py` | TNF 数据质控（缺测/异常点） | 产出 `results/tnf_qc.txt` |
| `gen_profiles.py` | 生成 flameD 入口 Fluent profile CSV | 边界 profile 用 |
| `parse_fla.py` | 解析 Chemkin `.flamelet/.fla` → Fluent ASCII | 火焰面库路线 |
| `parse_grid.py` | 解析 Fluent legacy ASCII 网格（Grid） | 网格取证 |
| `plot_tnf.py` / `plot_compare.py` | TNF 数据绘图 / CFD-TNF 对比（纯 Python） | 不启 Fluent |
| `postprocess.py` | 早期后处理（CFD vs TNF 汇总） | 已被 §11.7 各专用脚本取代 |
| `run_edc.py` | EDC 模型运行（GRI 3.0 + EDC） | §4.3 结论来源；现用 np_eq 线 |

### 11.11 历史/一次性脚本（保留备查，不再常用）

`boot_fluent.py`（早期启动器）、`setup_flamed.py`（早期会话搭建）、
`drive_flamed.py`（早期 PyFluent 编排）、`watch_runs.py`（v4 求解看门）、
`prep_planar_pregui.py`（全域平面 pregui 备份路线，已被 replace_mesh 取代）。

### 11.12 2D→3D 网格转换：Fluent 2025R2 **无内置命令**（2026-09-15 证伪，勿重复尝试）

**结论**：Fluent 2025R2（本部署）**没有任何可用的 2D→3D 网格旋转/拉伸命令**。
要得到 3D 网格只能：自写 legacy ASCII 3D 生成器（hex + 轴心 wedge），或走 GUI Meshing
workflow（需人工操作）。

**完整证据链**（探测脚本：`scripts/dev/probe_2d3d.py`、`probe_2d3d_meshing.py`、
`probe_dmp_2d3d.py`）：

| 探测 | 结果 |
|---|---|
| solver 模式 `/mesh/2d-to-3d`、`/mesh/2d_to_3d`、`/mesh/convert-2d-to-3d`、`/mesh/revolve` | 转录全为 `Error: invalid command` / `Error Object: "..."` |
| solver 模式 `s.tui.mesh` / `s.settings.mesh` 过滤 3d\|rotate\|revolve\|extrude | 仅命中 `rotate`（旋转已存在的 3D 网格，不能把 2D 变 3D） |
| **scheme dump 字符串取证** `lib\fl114-64.dmp`（140 MB，全部 TUI 命令定义） | `2d-to-3d` / `2d_to_3d` / `2dto3d` / `2d-3d` **0 hits**；`extrude` 92 hits 全是边界层棱柱（`-prism-extrude`）与 UTL；`revolve` 20 hits 属 **TGrid 模块**（`ti-create-revolved-surface`、"No edge zones are selected for revolve"） |
| meshing 模式（`launch_fluent(mode="meshing")`） | `/mesh` 全 20 个子节点（adapt/check/modify_zones/rotate/scale/smooth_mesh/surface_mesh/translate…）**无 extrude/2d-to-3d**；`file.read_mesh` 报 `menu not found` |
| 安装目录 *.msh 示例（为路线 B 取证） | 无（示例文件不在安装目录） |

**3D 化可行路线（备忘）**：
1. **自写生成器（推荐）**：2D 轴对称网格绕轴旋转 n 段；θ 首尾节点合并（全周无缝）；
   r=0 轴心节点合并 → 第一圈 quad 自动成为 wedge 单元。
   legacy ASCII 单元类型码经验表（待实测确认）：1=tri、2=tet、3=quad（**已实测**）、
   4=hex、5=pyramid、6=wedge。
2. TGrid 模块（`fluent25.2.0\tgrid\`）：dump 显示有 revolve 能力，但为 GUI 工具，
   headless 可行性未验证，需确认许可；
3. GUI Meshing workflow：需人工操作（当前不可用）。
4. 维度读取：`setup.general.solver.two_dim_space`（值 `axisymmetric` / `planar`；
   **无** `solver.dimension` 属性——0.30.5 实测）。

### 11.13 ★ 自写 3D 六面体网格（legacy ASCII 格式已破解，2026-09-15）

**3D hex legacy ASCII 格式要点（实测破解，`scripts/dev/probe_hex_format.py` 8 变体验证）**：

| 字段 | 2D（已验证） | **3D（本次破解）** | 说明 |
|---|---|---|---|
| 标题 | `(1 "...")` | 同 | |
| 维度 | `(2 2)` | **`(2 3)`** | |
| 节点索引段 | `(10 (0 1 N 0 2))` | **`(10 (0 1 N 0 3))`** | 末位=坐标维数 |
| 单元索引段 | `(12 (0 1 M 0))` | 同 | |
| 面索引段 | `(13 (0 1 F 0))` | 同 | |
| 单元段 | `(12 (1 1 M 1 0))` + 每单元整数 **3**（quad） | **hex 类型码 = 4** | |
| **面段** | `(13 (zone first last type **2**))` | **`(13 (zone first last type 4))`** | ★ 末位 = **面的节点数**（2D quad 边 2 节点 / 3D quad 面 4 节点）。**写成 3 会被按三角面逐行解析 → interior 面 0 个 → 节点索引越界 → `invalid grid`**（血的教训） |
| 面行 | `n1 n2 c0 c1`（4 列） | **`n1 n2 n3 n4 c0 c1`（6 列）** | c1=0 表示边界面 |
| 单元类型码 | quad=3 | **hex=4**（5/6 均失败：`invalid grid`） | 统一表：1=tri, 2=tet, 3=quad, 4=hex, 5=pyr, 6=wedge, 7=poly |
| 节点序 | — | 标准序（底 4 逆时针 + 顶 4 对应）通过；swapbase/toprev 也被接受 | Fluent 容忍顺序 |

**长方体通道 3D 网格生成器**（用户指定构型：底面进口/顶面出口/四周壁面/火焰区加密）：

```powershell
& $PY scripts\gen_mesh_box3d.py --level coarse   # → mesh/box3d/coarse.msh（2.49M hex）
& $PY scripts\gen_mesh_box3d.py --compact        # → mesh/box3d/compact.msh（945,888 hex）
& $PY scripts\verify_mesh3d.py mesh/box3d/compact.msh --cores 4   # 读入+check
```

* **compact 规格（推荐，<100 万单元）**：334×472×6 = **945,888 hex**。
  **反应区保持 v5 coarse 细度**（x 0–200mm 0.30→2.0mm；y |y|≤45mm 火焰带
  0.099–0.212mm，全 90° 正交）；粗化外围（x>200mm → 12/28mm；y>45mm → 7/22mm）；
  z 6 段（每半 8/55/153mm——条带射流沿 z 梯度≈0，是最高效压缩杠杆）。
  反应区核心占 58.5% 单元。实测：读入 25 s、min volume 2.96e-10 m³（正）。
* 几何：x∈[0,720]（轴向）y∈[-216,216] z∈[-216,216]；x/y 向沿用 v5 火焰带加密规格。
* 进口分区（按 |y|，沿 z 全宽）：`inlet-jet` ≤3.6mm / `inlet-pilot` ≤9.1mm /
  `inlet-coflow` 其余；出口 1 个（x=720）；壁面 4 个（y±、z±）。
* 实测核验（2026-09-15 21:18）：读入 46 s、`minimum volume 1.48e-10 m³`（正）、
  无 Error、全部面识别为 quadrilateral ✓
* ★ 生成器坑（已修）：面的边界判定必须用**面索引** `== n`（写 `== n-1` 会把
  最后一个单元的出口/壁面误标为内部 → `KeyError: 0`）。
* ★ **燃烧模型前置（重要）**：`np_eq_seed.cas.h5` 是 2D 轴对称 case，
  **2D→3D 无法 replace_mesh**（维度不匹配），且非预混模型 headless 无法使能
  （§6.4 循环依赖，与维度无关）→ **3D 非预混燃烧需用户 GUI 建一次"3D 非预混种子
  case"**（读 3D 网格 → Species 面板设非预混+流组分 → 算 PDF 表 → 存 case+pdf），
  之后所有 3D 网格变更用 3D→3D replace_mesh（可行），全部 headless。
  **headless 可行的 3D 燃烧替代路线 = species transport + 有限速率/EDM**
  （`run_box3d_edm.py`，与 2D 的 run_edm.py 同构：热态入口 1100K 启动 +
  2 步机理 + eddy-dissipation）。

**3D 求解脚本与实测（2026-09-15 晚，945,888 hex / 10 核）**：

```powershell
# 冷流（纯流动+能量，全 headless，验证链路）
& $PY -u scripts\run_box3d_cold.py --n-iter 120 --so-step 100 --cores 10
# 燃烧（species transport + ch4_2step + EDM；首段冷流 60 步→开反应）
& $PY -u scripts\run_box3d_edm.py --phase cold --n-cold 60
& $PY -u scripts\run_box3d_edm.py --phase edm --resume --n-iter 50 --seg seg01
# 监督器（后台自动续段 + 逐段备份到 run/backup_3d/）
& $PY -u scripts\driver_box3d.py
```

* **冷流实测**：读网格 17 s、hybrid init 33 s、**迭代 5.32–5.48 s/步**（一阶，10 核）；
  k-ε realizable + EWT、能量方程、三进口速度/湍流/温度、4 壁面 300K **全部 headless 设置成功**。
* **★ 每段时长必须 ≤8 min**（工具前台 timeout 10 min；120 步 × 5.4 s + 启动 2 min
  = 12.8 min 会被杀——这是"静默失败"的又一种成因，与随机击杀不同）。
* 3D 建线面需 **6 个坐标**（`line_surface(name, x0,y0,z0, x1,y1,z1)`；2D 是 4 个）；
  3D 判稳方程回读含 `z-velocity` 与 `energy`（共 7 项）。
* 备份策略：driver 每段结束把 `box3d_edm.cas/dat.h5` 复制到
  `run/backup_3d/segNN/`；网格备份 `run/backup_3d/compact.msh`。
* ★ **EDM 使能顺序坑（2026-09-15 实撞）**：必须先执行
  `/define/models/species/volumetric-reactions yes`（TUI），
  `setup/models/species/turb-chem-interaction` 节点**才会激活**；
  若先设 turb_chem 会报 `api-set-var: the object is not active`，
  且**不报错地留在 finite-rate/no-tci**（第一次 3D driver 因此在跑 finite-rate
  而非 EDM——检查方法：读 case 后打印 `turb_chem_interaction.get_state()`，
  应为 `'eddy-dissipation'`）。已封装 `enable_edm()` 幂等函数（重试 3 次 +
  回读校验），续算分支也调用。
* 3D EDM 实测节奏（945,888 hex / 10 核 / 40 步一段）：**~5.2 min/段**
  （启动 1.5 min + 40×5.5 s），迭代 **6.8–7.8 s/步**；热入口 1100K 启动策略
  与 2D run_edm.py 一致（EDM 峰值 ~2515 K 为模型特性）。

**★ 3D 方管 EDM 燃烧结果（2026-09-15 23:16–00:21，14 段零失败）**：

* 流程：冷流 60 步（species off）→ 开 EDM + species → 560 步 → **稳定收敛**
  （T@30d 峰值 2518–2541 K，波动 ±0.5%，无振荡/发散；步时降至 4.8 s）。
* 产物：`results/cfd_box3d_edm.csv`（9 站剖面 397 点/站 + 中心线）、
  `results/figs/box3d_{compare,centerline}.png`；备份 `run/backup_3d/`
  （网格 + seg01–14 逐段 case/dat + final/ 汇总）。
* **关键结果（x/d 站）**：
  | x/d | 3D T_max | 3D T_axis |
  |---|---:|---:|
  | 1 | 2054.7 | 1100.2（热入口未燃） |
  | 3 | 2191.1 | 1125.5 |
  | 15 | 2312.0 | 2308.3 |
  | 30 | 2540.5 | 2465.5 |
  | 45 | 2606.1 | 2452.5 |
  | 60 | 2640.4 | 1555.1 |
* **物理结论**：3D 方管的火焰是**中央宽火焰**（x/d≥15 轴线温度 2300–2465 K，
  高温区宽 4–5d，|y|>4–5d 处受 300 K 冷壁影响降至 ~500 K）——与**平面 2D 的
  "双火焰片、轴线掏空"结构显著不同**（有限宽度 + 四周壁面约束抑制了横向铺展）。
  **这定量证明平面 2D 的"z 向无穷宽"假设在有限通道内不成立**，是该 3D 计算的
  核心价值。（对比图 `box3d_compare.png` 已标注：3D=EDM、2D=np_eq，模型与构型均不同，仅作参照。）

**★ 3D 方管 EDM vs TNF 实验（七方 RMS 表，2026-09-16 00:50）**：

| 解 | x0.75 | x1 | x2 | x3 | x15 | x30 | x45 | x60 | x75 | **均值** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 轴对称·二阶（np_eq） | 211 | 222 | 224 | 181 | 438 | 311 | 142 | 143 | 64 | **215.0** |
| 轴对称·一阶 | 197 | 242 | 234 | 199 | 472 | 332 | 153 | 152 | 63 | 227.0 |
| 全域平面·二阶 | 184 | 240 | 290 | 296 | 648 | 620 | 745 | 559 | 589 | 463.5 |
| 全域平面·加密 | 184 | 240 | 290 | 296 | 647 | 619 | 745 | 565 | 605 | 465.7 |
| **3D方管·EDM(热入口1100K)** | 646 | 718 | 735 | 708 | **1154** | 690 | 334 | 441 | 641 | **674.1** |
| **轴对称·EDM(冷入口294K)** | 191 | 367 | 527 | 558 | 618 | **922** | **1201** | 1013 | 736 | **681.5** |

**归因结论（重要）**：
1. **3D 方管 EDM（674.1）≈ 轴对称 2D EDM（681.5）**——构型完全不同（方管+四壁 vs
   圆自由射流）但 RMS 仅差 1% → **误差主因是 EDM 模型本身（~680 K），构型差异贡献很小**。
   （np_eq 平衡化学 215 K 压倒性更优，与 §4.3 的 2D 结论一致。）
2. 3D 误差结构：**近场 4 站（0.75–3d）646–735 K 主要来自热入口 1100 K 策略**
   （实验入口 294 K，基线直接高 ~800 K）；中游 x15（1154 K）为 EDM 高温区
   过宽所致（混合控制无动力学限制 → 峰值 2515–2640 K vs 实验 1938 K）。
3. **后续若要逼近实验**：① 3D 改冷入口复算（把入口温度切回 294/291/291 K 续算
   ~150 步，预计近场 RMS 大幅下降）；② 3D 非预混平衡模型（需 GUI 种子 case，
   预期可达 215 K 量级）。

**★★ 进口温度协议误区（2026-09-16 凌晨发现并修正，务必牢记）**：

* **Flame D 文档进口温度**：**jet 294 K / pilot 1880 K（燃烧产物！）/ coflow 291 K**。
  `flamed_common`：`T_JET=294 / T_PILOT=1880 / T_COFLOW=291`。
* `run_edm.py` 的完整协议是**三段**（第 520–597 行）：
  ① **热态启动**（入口全 1100 K，`--hot`）→ 建火焰；
  ② **切回文档温度 + "自持"段**（`n_hold=1500`，第 591–597 行 `set_T(k, BASE_T[k])`
     → "入口改回文档值"）→ 火焰自持运行；
  ③ 导出（最终结果）。
  **`--skip-hot` 则跳过①直接用文档温度**。
* **本次 3D 的失误**：只照搬了①热态启动，**漏掉②自持段**→ 560 步全在 1100 K 热态下
  运行，解停在"点火态"而非文档工况 → 对标实验时近场 RMS 646–735 K 虚高。
  （2D EDM 导出的对比 CSV 入口为 294 K，证明其经过了②自持段。）
* **修正命令**（`run_box3d_edm.py` 已加 `--hold`）：
  ```powershell
  & $PY -u scripts\run_box3d_edm.py --phase edm --resume --hold --n-iter 40 --seg hold01
  ```
  `--hold` 在续算时把三进口温度切回 294/1880/291 K（并打印确认），续算直到稳定。
* **教训**：照搬既有脚本时，必须通读其**完整阶段序列**（启动→维持→导出），
  不能只看前半；进口温度是"工况定义"的核心项，**必须在计算卡中逐项列出**。

**★ 自持段修正结果（2026-09-16 01:15–01:48，10 段零失败）**：

* 修正：三进口温度 1100 K → **文档值 294/1880/291 K**（`run_box3d_edm.py --hold`）。
* **RMS 从 674.1 → 341.7 K（改善 49%）**；逐站：近场 646–735 → **100–339 K**；
  中游 x15 1154 → 933、x30 690 → 616；远场 441–641 → 211–243 K。
* 纠错核查（`analyze_box3d_hold.py`）：**jet 区 294.0 K / coflow 区 291.0 K
  = 文档值完全一致**；jet ch4 0.15628（文档 0.15637）、coflow o2 0.23574（完全一致）；
  火焰自持（T_max 2208 K，实验 1938 K）；峰值较热态降低 400 K；
  轴线 @15d 2308 → 842 K（实验 498 K）。
* 产物：`results/cfd_box3d_edm_hold.csv`、`figs/box3d_edm_hold_{radial,centerline}.png`、
  `results/box3d_hold_analysis.txt`；备份 `run/backup_3d/hold01–hold10/`。

**★ 3D GCI 网格无关性验证体系（2026-09-16 02:00 起）**：

| 级别 | 单元数 | 维度 x×y×z | 加密因子 | 状态 |
|---|---:|---|---:|---|
| G1 粗 | 945,888 | 334×472×6 | 1.000 | 已完成（885 步） |
| G2 中 | 1,885,008 | 454×692×6 | 1.267 | 计算中 |
| G3 细 | 3,238,704 | 612×882×6 | 1.605 | 排队 |

* 生成命令（等比加密，**z 固定 6 段**——沿 z 梯度≈0，加密只作用于有梯度的 x/y）：
  ```powershell
  & $PY scripts\gen_mesh_box3d.py --compact --refine 1.2670 --out mesh/box3d/gci_med.msh
  & $PY scripts\gen_mesh_box3d.py --compact --refine 1.6050 --out mesh/box3d/gci_fine.msh
  ```
* 协议（三级一致）：冷流 60（热态 1100K 启动）→ 热态 EDM → 自持段（文档温度）；
  驱动器 `driver_gci.py`（后台串联 G2/G3，段长 25/15 步/段，≤8 min/段）。
* ★ 坑：`build_z_axis()` 默认参数是**非 compact 的 12 段表**——compact 相关调用必须
  显式传 `Z_HALF_MM_COMPACT`（曾因此生成出 3.77M 而非 1.89M 的"中网格"）。

**★★ 判稳判据升级（2026-09-16 05:20 实撞）**：

* **只看 T_max 会误判收敛**！G2（1.89M）自持段 T_max 稳定在 2208–2245 K（±2%），
  但 **T_min 从 438 K 持续升到 611 K**——说明冷射流尚未贯穿、温度场仍在演化。
* **升级判据（两个都要满足）**：
  ① T_max 序列相对变化 <1%（原判据）；
  ② **T_min 稳定在入口温度附近（294±10 K）**——冷流贯穿的判据（G1 收敛时为 291–298 K）。
* 物理原因：切换入口温度后，冷流（294 K）从入口推进到下游需要**对流时间尺度**
  （cold-flow 前沿达到 x/d=30 需要 >200 步）；在此期间 T_max 可能已"看起来稳定"。
* 副产品结论：**网格越细收敛越慢**（G1 945k/265 步自持即稳；G2 1.89M/205 步仍未稳
  → 需补 200 步）；3D GCI 的计算成本随网格非线性上升。
* 两级解对比（G1 vs G2，**收敛度不同**）：RMS 341.7 vs 585.7 K，中下游 45–75d
  差异 3 倍——**这是收敛度差异，不是网格效应**（教训：GCI 必须在各组充分收敛后比较）。

**★★ 两级网格敏感性结果（2026-09-16 06:25，G1 945,888 / G2 1,885,008 均已充分收敛）**：

| x/d | G1 T_max | G2 T_max | Δ% | G1 T_axis | G2 T_axis | Δ% |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 2171.8 | 2173.2 | **0.1** | 294.1 | 294.1 | **0.0** |
| 3 | 2171.8 | 2173.1 | **0.1** | 305.4 | 305.2 | **−0.1** |
| 15 | 2201.6 | 2207.8 | 0.3 | 842.1 | 714.1 | −15.2 |
| 30 | 2205.4 | 2216.5 | 0.5 | 1796.3 | 1672.1 | −6.9 |
| 45 | 2207.9 | 2229.8 | 1.0 | 2144.6 | 1784.4 | −16.8 |
| 60 | 2202.7 | 2225.4 | 1.0 | 2007.5 | 1967.1 | −2.0 |

* **结论**：①**峰值温度网格基本无关（Δ 0.1–1.0%）**；②轴线温度**近场网格无关
  （Δ≤0.1%）**、**中游（15/45d）敏感（Δ −15~−17%）**；③**火焰形态对网格敏感**——
  G1（粗）保持双火焰片至 x/d=45 且形态更接近实验，G2（细）火焰更宽、更早合并成单峰。
* **物理解读**：粗网格的数值扩散部分"补偿"了 EDM 模型的过度燃烧（与 2D
  "一阶扩散抵消模型误差"现象同源）；细网格更真实地暴露 EDM 的宽火焰特性。
* 产物：`results/gci_two_level.{txt,csv}`、`figs/gci_two_level.png`；备份
  `run/backup_3d/final_gci_med/`。
* **G3（3,238,704）未跑**：估算需 ≥600 步 ≈ 4–5 小时（3.24M 单元步时 ~40 s）
  → 留作后续（网格已生成 `mesh/box3d/gci_fine.msh`，driver 已就绪）。

**★★ G3 温度异常诊断与路线终止（2026-09-16 10:25，用户发现 3124 K 超绝热上限）**：

* **异常确认**：G3 热态段 T@30d 峰值 **3124 K**，超出 CH₄/空气绝热上限
  （φ=1、294 K 入口约 2226 K；含 jet 预热 1100 K 约 **2900 K**）——**物理不可能**。
* **诊断**（`diag_hotspot2.py`）：创建 iso-surface T=2800/3000/**3100 K 均成功**
  → 超温是**区域性**的（非孤点数值噪声）。`field_data` 对新建 iso 面需刷新缓存
  （`get_surfaces_info` 未含新面 → 场数据读取报 not allowed surface，属已知限制）。
* **根因**：EDM 是唯象模型，反应源项 ∝ 湍流混合率（ε/k），**无化学动力学限制、
  也不守恒能量上限**——3.24M 细网格上局部单元的 ε/k 异常 → 反应源爆炸 →
  区域性超绝热温度。G1（945k）/G2（1.89M）未出现（峰 2200–2530 K 合理），
  **3.24M 细网格触发**。
* **决策**：**G3 EDM 路线终止（解物理无效，不用于 GCI）**。网格本身无问题
  （`gci_fine.msh` 保留备用）。**网格无关性验证以两级结论为准**（§11.13 前节）。
* **3D 燃烧的可行出路**：
  a. **3D 非预混平衡模型**（推荐）：需 GUI 建一次 3D 非预混种子 case（约 5 分钟），
     预期精度与 2D np_eq 同级（215 K）；模型物理上不依赖湍流混合率的唯象公式；
  b. EDC（有限速率 + 混合控制，headless 可行）：更物理，但成本 ~2×EDM 且 2D 结论
     亦劣于 np_eq；
  c. EDM 限幅参数（治标，不推荐）。
* **诊断脚本**：`scripts/diag_hotspot2.py`（iso-surface + 体积积分，v2）。

**★ 切片可视化方法（2026-09-16 12:30 打通）与远场伪影发现**：

* **★ 建面必须用 settings API**：`s.settings.results.surfaces.iso_surface.create(name=nm)`
  + `[nm] = {"field": "z-coordinate", "iso_values": [0.0]}` → 面**立即被 field_data 识别**；
  **TUI 的 `/surface/iso-surface` 会静默失败**（不报错但面未注册，field_data 报
  "not an allowed surface"）——踩坑两次才定位。
* 提取：`s.fields.field_data.get_scalar_field_data(field_name=<场>,
  surfaces=[<面名>], node_value=True)` → npz（`extract_slices.py`）；
  渲染：tricontourf + 去重（`render_slices.py`）。
* **切片结论**：
  ① **火焰区（|y|≤40mm）可信**：近场双火焰片 → 中游中央高温带 → 下游渐降，峰值 2209 K；
  ② **y=0 平面（x–z）沿 z 完全均匀** → 验证"条带射流沿 z 无梯度"假设，**支持 z 向
     6 段粗化决策**；
  ③ **★ 远场异常（新发现）**：**y<0 侧 |y|>50mm 区域出现虚假高温**
     （x∈[300,500]mm 33% 点 >1000 K、x∈[500,720]mm 46% 点 >1000 K，max 2193 K），
     而 y>0 侧对称位置 295 K 正常 → **EDM 伪影 + 破坏 y 对称性**
     （机制同 G3 超绝热：微量燃料经数值扩散进入外围 + 异常 ε/k 触发虚假反应）。
  ④ **对已交付结论无影响**：RMS 对标只用 |y/d|≤6（=43mm）火焰区数据 ✓。

**★ 网格总览图与 BC 全面核查（2026-09-16 12:40）**：

```powershell
& $PY scripts\render_mesh_overview.py   # → figs/mesh_overview.png（域+进口分区）、mesh_detail.png（加密分布）
& $PY scripts\inspect_all_bc.py         # → run/bc_check.txt（逐项对照表，报告全绿）
& $PY scripts\check_turb_inlet.py       # 进口湍流参数专项（多路径回读）
```

* **网格总览**：域 720×432×432mm，945,888 hex（334×472×6），进口面按 |y| 分
  jet(≤3.6mm)/pilot(≤9.1mm)/coflow 三条带（沿 z 全宽）；火焰区加密、外围/下游粗化、
  z 向 6 段（尺寸分布见 mesh_detail 面板 c）。
* **★ BC 核查结果：全部一致** —— jet/pilot/coflow 的 U/I/Dh/T/组分逐项符合
  （jet 49.6/0.0879/7.2mm/294K、pilot 11.4/0.1092/10.5mm/**1880K**、
  coflow 0.9/0.01/0.30m/291K）；出口 0 Pa；4 壁面 300K 无滑移；
  species-transport(6 组分)/EDM/k-ε realizable+EWT/能量 on/操作压力 101325 Pa。
* ★ **读取坑**：进口湍流节点结构是 `<node>.get_state()`（**无 `.value` 层**），
  而 momentum/thermal 节点是 `<node>.value.get_state()` —— 统一封装
  `gval()` 兼容两种（曾因路径写错误报"I/Dh = None 不符"）。

**★ 网格尺度报告（2026-09-16 12:50，`scripts/report_mesh_scale.py`）**：

| 方向 | 最小 | 最大 | 比值 |
|---|---:|---:|---:|
| Δx 轴向 | **0.3000 mm** | 27.956 mm | 93.2 |
| Δy 横向 | **0.1235 mm** | 21.324 mm | 172.6 |
| Δz 展向 | 8.00 mm | **153.00 mm** | 19.1 |

* **最小单元体积 0.2965 mm³**（0.30×0.1235×8mm）——位于 x/d=2.19、y/d=−0.54
  **火焰区 ✓**；**最大 91209.4 mm³（91.21 cm³）**——位于 x/d=98、y/d=−28.5、z=−139.5
  （下游外围）；体积比 **3.08e5**。
* **与 Fluent `/mesh/check` 交叉核对：min/max 体积偏差均为 0.000%** ✓（规格重建
  与读入结果完全一致，可作后续网格报告的快速来源）。
* **★ 长宽比（网格弱点）**：**max 1238，P50 = 224，P90 = 840**。根因：z 向仅 6 段
  （中心 Δz=153mm）遇上火焰区 Δy 最小 0.124mm。工程上 >1000 会削弱梯度重构精度、
  加剧数值扩散——**可能是远场伪影与对称性破缺的促成因素**。
* **建议**：z 向 6 → 8–10 段（中心 Δz 153 → 92mm，长宽比降至 ~743；单元 945,888
  → ~1.58M），代价可接受。
* **★ 可视化**：`scripts/render_mesh_scale.py` → `results/figs/mesh_scale.png`
  （六联：(a)Δx 沿程 (b)Δy 沿程 (c)Δz 柱状 (d)z=0 平面单元体积 log 云图
  (e)体积分布双峰 (f)长宽比分布）、`mesh_ar_sensitivity.png`（长宽比 vs z 段数
  折线：6→1238、**8→929（1.26M，已低于准则 1000）**、10→743（1.58M）、
  12→619（1.89M）、16→464（2.52M））。
* **着色提示**：新画图脚本必须 `from plot_style import use_cjk; use_cjk()`，
  否则 ANSYS 自带 matplotlib 渲染中文为方框（本图首版即踩此坑）。

### ★§11.14 火焰偏移根因 = 边界条件**类型**错误（封闭 vs 开放）（2026-09-16 13:20）

* **现象**：3D 解火焰面整体向 −y 偏移，且远场（y<0，|y|>50mm）出现 1800–2200 K
  虚假高温；对称性破缺沿程单调放大（x/d=5 时 T 反对称 RMS 50 K → x/d=30 时 471 K；
  x∈[500,720] 且 y<−50 区域 **92.9% 的点 >1000 K**，而对称的 y>+50 侧仅 299 K）。
* **排除"数值写错"**（`scripts/inspect_bc_deep.py` → `run/bc_deep.txt`）：
  三进口 U/I/Dh/T/组分全对；**重力关闭**；操作压力 101325；出口表压 0 Pa →
  **p_abs = 1 atm ✓ 正确**；**wall-7/8、wall-9/10 逐叶子比对除名称外 0 项不同**；
  网格 zone 面数成对严格相等（616/968/9504、12980=12980、74340=74340）。
  → **不存在数值层面的 y 向不对称 BC**。
* **★ 真正的错误：四个侧面设成 300 K 无滑移壁面（封闭通道）**，而 Flame D 实验
  是**开放环境**射流火焰 → 卷吸被截断（`scripts/diagnose_offset.py`）：

  | x/d | 条带射流所需 Q(x) | 封闭域可供给 | 供需比 |
  |---|---|---|---|
  | 15 / 30 / 45 / 100 | 0.693 / 0.979 / 1.199 / 1.788 | 0.855 | 1.23 / **0.87** / **0.71** / **0.48** |

  对照**圆射流轴对称**构型（已验证 215 K）：供需比 **15.9 → 2.38 全程 ≥1 ✓**；
  条带构型的相对卷吸能力只有圆射流的 **3.6%（差 28 倍）**
  （供给/射流自身流量：条带 2.4× vs 圆射流 67.4×）。
* **失效链**：卷吸截断 → 热产物回流 → EDM 无熄火机制继续"燃烧"回流产物 →
  释热膨胀 → 压力场把射流进一步推向该侧 → **正反馈** → Coanda 型偏转失稳。
  （也统一解释了 2D 平面构型的结构性误差：同为条带射流，同样流量饥饿。）
* **修正**：侧壁 wall → **pressure-outlet（开放，0 Pa，回流 291 K + 空气组分）**；
  出口回流 300 K→291 K、组分"全 0（等效纯 N₂）"→空气；出口表压 0 Pa **保持**。
* **更深层**：条带射流（∝x 卷吸）≠ 圆射流（∝x²），即使开放边界也**不能定量对标**
  Flame D → 3D 定量路线必须改用**圆形进口分区**（r=√(y²+z²)），见计算卡方案 C。
* 新脚本：`inspect_bc_deep.py`（逐 zone 全量叶子回读 + 对称配对比对 + 操作条件）、
  `diagnose_offset.py`（卷吸供需核算）、`analyze_asym.py`（解场对称性量化）、
  `verify_mesh_lim.py`（网格校验）。

### §11.15 限幅网格 compact_lim（0.5–10 mm）（2026-09-16 13:15）

* 生成：`gen_mesh_box3d.py --compact --dmin 0.5 --dmax 10 --out mesh/box3d/compact_lim.msh`
* **新增能力**：`clamp_specs()`（限幅 + 自动合并短于 dmin 的薄段——唇口 0.25/0.35mm
  无法在 0.5mm 下限下分辨，必须并入相邻段）、`build_z_axis(dmax)`（按 ≤dmax 均匀铺满）、
  `--dry-run`（只统计不写文件）。
* **结果**：**3,270,960 单元（295×252×44）**，Δx 0.498–10.005、Δy 0.493–9.894、
  Δz 9.818（均匀 44 段）；**最小体积 2.4117 mm³ / 最大 971.9 mm³（体积比 403，
  V1 为 3.08e5）**；**最大长宽比 20.3（V1 为 1238）**；**正交质量 1.00000**；
  Fluent 读入 37 s，体积与规格重建偏差 0.000%。
* ★ **副作用**：z 向 6 → 44 段使单元数 ×3.46（945,888 → 3,270,960）→ 单步约 ×3.5。
  若需控成本，**1/4 域（symmetry）+ 同限幅 = 0.82M**，比 V1 还少。

### §11.16 ★ 圆形进口（严格对标实验）+ 百万单元预算（2026-09-16 13:40）

* **用户裁定**：BC 错误就是**进口分区**——实验是**圆射流**，必须用**到中心的半径**
  分区，不能用 |y| 全宽条带；**四周壁面保持 wall**；**coflow 以外为空气**；
  单元总数 **≤ 100 万**；并明确要求**全域计算**（不用 1/4 域）。
* **进口分区（新）**：`r = √(y²+z²)`，按面形心判定
  | zone | 判据 | 实验几何 | BC |
  |---|---|---|---|
  | 3 inlet-jet | r ≤ 3.6 mm | 主射流 d=7.2 mm | 49.6 m/s，294 K，ch4 .15637+o2 .19650 |
  | 4 inlet-pilot | 3.6 < r ≤ 9.1 mm | 稳燃环 d=7.7/18.2 mm | 11.4 m/s，1880 K，产物组分 |
  | 5 inlet-coflow | 9.1 < r ≤ **150 mm** | 伴流喷口 **d=300 mm** | 0.9 m/s，291 K，空气 |
  | 11 inlet-air | r > 150 mm | 伴流以外（四角） | **静止空气**：0 m/s，291 K，空气组分 |
* **为什么必须用渐变/等间距子段做 z**：圆射流要在两个横向都分辨 7.2 mm 的圆，
  轴线附近必须 Δ≈0.5 mm → z 向不能再是 6 段（条带构型才允许）。
* **★ 踩坑（重要）**：几何**渐变段**在 `n_from_ends` 反解时首层会被压到下限以下
  （实测 0.467 / 0.487 mm < 0.5），改用**等间距子段**即可精确守住 [0.5, 10] mm。
  另：`clamp_specs()` 必须对**已选**规格生效（曾误写成对 X_COMPACT 生效 →
  `--tight` 静默失效，单元数仍是 295×252 那一套）。
* **百万预算规格（--tight）**：x 126 段（0–30mm @0.75mm，其余迅速拉到 ≤10mm）；
  y/z 各 88 段（0–7mm @0.5mm → 1mm → 2mm → 5mm → 9.9mm）。
  **全域 126×88×88 = 975,744 单元**（≤100 万 ✓），Δ ∈ [0.500, 9.87] mm。
  对照：非紧致全域圆进口 = 7,136,640（超预算 7×）；1/4 域紧致 = 266,616。
* 新脚本/新参数：`gen_mesh_box3d.py --round --tight [--quarter]`；
  进口分区**面积自动校验**（离散面积 vs 理论圆面积 + 反算等效直径）已内置打印。

### ★§11.17 "伴流以外的空气不是静止的"（2026-09-16 14:05，用户纠正）

* **核对结论（用户正确）**：项目原始计算卡 `CALC_CARD_3D_FLAME_D.md` 与**已验证的
  2D 轴对称基准（RMS 215 K）** 都把伴流定义为 **9.45–216 mm 全域 0.9 m/s 空气流**；
  实验的 300 mm 只是**喷口尺寸**，CFD 中伴流延伸到域边界。
  若把 r>150mm 设成静止空气，会在封闭域内造出一个"死水腔"，既不真实又导致卷吸不足。
* **修正**：zone 11（inlet-air）由 0 m/s → **0.9 m/s**（I=1%、Dh=0.30 m、291 K、
  空气组分 o2 .23574 / h2o .006256），与 coflow 完全一致；300 mm 分区仅作几何标记保留。
* **★ 踩坑（严重，已被新校验拦下）**：`run_box3d_edm.py` 模块级常量 `DOC_T` 与
  `main()` 内 `--hold` 分支的**同名局部变量**冲突 → 触发
  `local variable 'DOC_T' referenced before assignment`；由于进口设置用
  try/except 包着，**异常被吞掉**，结果是"速度设了、温度与组分没设"却继续开算。
  → 已重命名模块级常量为 `INLET_DOC_T`，并在设置后加**硬校验**：逐进口回读
  U/T，任一不符即 `sys.exit(5)` 中止（绝不允许带错设置开局）。
* **V3 首发状态**：4 个进口校验全绿（jet 49.6/294、pilot 11.4/1880、
  coflow 0.9/291、air 0.9/291）+ 4 壁面 300 K；冷流 6.28 s/步。
* 新脚本：`driver_round.py`（冷流 60 + 反应 18×25 = 450 步，段间可续）。

### 11.18 ★ 计算域缩减到实验尺寸 300 mm（V4，2026-09-16）

* **发现**：V3 在跑的 `compact_round.msh` 横向是 **y,z ∈ [−216, 216] mm（432 mm 方域）**，
  （`R_DOMAIN = 30*D_JET = 216 mm` 是模块默认值，`--half-mm` 不给就走它）。
  横向面积 186,624 mm² = **实验风洞（300 mm 方，90,000 mm²）的 2.07 倍** → 约束过松，
  对标结果会一直带"域过大"的质疑。用户裁定：**计算域 ≥ 实验即可，缩到 300 mm**。
* **新网格**：`--half-mm 150` → `yz_spec(0.150)` 生成 84+84 段，
  **889,056 单元（126×84×84）**，节点 917,575；
  Δx 0.7457–9.8642、Δy/Δz **0.5000–10.0000** mm（仍全部落在 [0.5,10] ✓），
  比 V3 省 8.9%（外围已是 10 mm 粗网格，所以单元数省得不多，**收益主要是保真度**）。
* **★ 分区逻辑随之变化**：`RCOF = R_COFLOW if (ys[-1] > 0.1501) else 1e9`。
  half=150 时 `ys[-1]=0.150` 不 > 0.1501 → **RCOF=1e9 → 整个截面都是 coflow，
  zone 11（inlet-air）不再存在**。这是**物理正确**的：实验风洞内全是伴流空气，
  四角不该被拆成独立区（V3 里四角 air 占进口面积 62%，参数与 coflow 完全相同）。
  方形截面 Dh = 4A/P = 4×0.09/1.2 = **0.30 m，恰好等于实验值**。
* **★ 代码坑（已修）**：`run_box3d_edm.py` 的**硬校验循环没有 try/except**，
  对 4 个进口逐一 `bc.velocity_inlet[Z3[k]]` 取值。300 mm 域没有 zone 11 →
  直接抛异常崩溃。已加 `ACTIVE` 分区探测：
  ```python
  _zin = set(bc.velocity_inlet.keys())
  ACTIVE = [k for k in ("jet","pilot","coflow","air") if Z3[k] in _zin]
  ```
  两个循环都改为遍历 `ACTIVE`；jet/pilot/coflow 缺失则 `sys.exit(5)`，仅 air 允许缺失。
* **`driver_round.py` 加 `--tag` / `--mesh`**：新域用 `box3d_round300` +
  `compact_round300.msh`，**不覆盖** V3 的 `box3d_round.*`（V3 结果留作域敏感性对照）。
* **命令**
  ```bash
  # 试算（不写文件）
  python scripts/gen_mesh_box3d.py --compact --round --half-mm 150 \
         --dmin 0.5 --dmax 10 --dry-run
  # 生成
  python scripts/gen_mesh_box3d.py --compact --round --half-mm 150 \
         --dmin 0.5 --dmax 10 --out mesh/box3d/compact_round300.msh
  # 计算（V3 跑完后）
  python scripts/driver_round.py --tag box3d_round300 \
         --mesh mesh/box3d/compact_round300.msh --cores 10
  ```
* **用户裁定（2026-09-16 14:50）**：**先让 432 mm 的 V3 跑完全部 450 步**（≈15:37），
  再启动 300 mm 的 V4；V4 反应段**维持 450 步**（不增不减）。
  计算卡：`docs/CALC_CARD_3D_V4.md`。
* **判据提醒**：V4 出结果后必看 §11.16 的**对称性判据**（T 反对称分量 RMS < 30 K，
  V1 条带进口为 471 K）——这是"圆进口是否修复火焰偏移"的唯一量化指标。

### 11.19 ★★ V3 结论：圆进口**已修复火焰偏移**（2026-09-16 15:45）

* V3（432mm 域、圆进口、air 0.9 m/s）跑完 60 + 450 步后用 `analyze_asym.py` 判定：

| 判据 | V1（条带进口） | **V3（圆进口）** | 阈值 | 结论 |
|---|---|---|---|---|
| T 反对称 RMS @ x/d=30 | **471 K** | **4.9 K** | < 30 K | ✅ 修复 |
| T 反对称 RMS 最大（x/d=15） | — | **10.5 K** | < 30 K | ✅ |
| v_y 对称分量均值 | — | **0.00–0.01 m/s** | ≈ 0 | ✅ |
| v_x 反对称 RMS | — | ≤ **0.16 m/s** | ≈ 0 | ✅ |
| 远场 T>1000 K 占比 | **92.9%** | **0.0%** | < 0.1% | ✅ 修复 |

* **T_max 沿程**：2074（x/d=5）→ 2197（15）→ 2099（30）→ 1627（45）→ 1182（60）
  → 985（75）→ 905（90）K —— 火焰正常建立并沿程衰减，**不再是 V1 那种"贴壁不衰"**。
* **结论**：偏移的根因就是**进口分区按 \|y\| 条带**（平面射流）而非**半径**（圆射流），
  条带射流在闭通道里卷吸不足 → Coanda 型偏斜。改圆进口后偏移消失。
  这一结论支持了此前"平面 2D 不能用于圆射流对标"的判断（同源：几何结构性误差）。
* **★ 分析脚本踩坑（已修，重要）**
  1. `analyze_asym.py` 原先用 **1 mm 分箱**统计对称性，但切片数据是**结构化网格节点**
     （127 列 × 85 行），1 mm 分箱把样本打散 → **只有 x/d=5 一个站位够点**。
     → 改为**取整列 x**（`np.unique(x)` 里最近的一列）+ **镜像插值配对**
     （`np.interp(-y, y, T)`），9 个站位全部可算，且不依赖网格严格对称。
  2. y 分箱范围原写死 ±216 mm → 改为按数据自适应 `ymax = ceil(max|y|)`，
     432mm / 300mm 域通用。
  3. `analyze_asym.py` 现在接受**命令行路径参数**：`python scripts/analyze_asym.py <sz0.npz>`。
  4. `extract_slices.py` 原来写死 `box3d_edm.cas.h5` → 加
     `--tag / --case / --procs / --out`，可按算例导出到独立目录。
* **★ git bash 环境坑（必记）**：给 Windows 版 ANSYS Python 设 `PYTHONPATH` 时，
  **必须写成 `D:\\Program Files\\...` 形式**；写成 git bash 的 `/d/Program Files/...`
  Windows Python 不认 → `ModuleNotFoundError: No module named 'ansys.fluent'`。
  正确写法：
  ```bash
  export PYTHONPATH="D:\\Program Files\\ANSYS\\2025R2\\v252\\commonfiles\\CPython\\3_10\\winx64\\Release\\Ansys\\PyFluentCore"
  export AWP_ROOT252="D:\\Program Files\\ANSYS\\2025R2\\v252"
  ```
* **V3 归档**：`run/backup_3d/v3_432/{cas,dat}`、`run/asym_report_round432.txt`、
  `results/figs/asym_vs_x_round432.png`、`run/slices_round/*.npz`。
* **V4 已启动**（15:43）：`--tag box3d_round300 --mesh mesh/box3d/compact_round300.msh`，
  冷流段校验通过（`进口分区生效=['jet','pilot','coflow'] 网格缺失=['air']`，
  3 进口全绿），反应段 18×25 进行中，预计 ~17:00 完成。

### 11.20 ★★ V4（300mm 域）结果 · 域敏感性 · 收敛性铁证（2026-09-16 17:10）

* **V4 完成**：16:59 全部 18 段 rc=0（冷流 60 + 反应 450 步），6.15 s/步。
  判据同样全绿：T 反对称 RMS 最大 **7.1 K**（x/d=10）、v_y 对称均值 ≈0、
  远场 T>1000 K 占比 **0.0%**。

* **★ 收敛性铁证（消除"欠迭代"质疑，方法可复用）**
  对 `run/backup_3d/seg02|seg12|seg18/box3d_round300.dat.h5`（75 / 300 / 450 步）做
  **字节级比较**：154,522,468 字节中**仅 144 字节不同**，且差异全是 ASCII 元数据串；
  **场数据逐字节一致** → 解在 **seg02（75 步）即已收敛到机器精度**，
  300→450 步零变化。
  → 另用 `export_box3d_profiles.py` 导出 seg02/seg12/seg18 的剖面 CSV，
    **md5 完全相同**（`3ca442fd…`），交叉印证。
  > 注意判据陷阱：`T@30d`（line 上的 min/max）被进口温度与化学峰值"钉死"，
  > 从第 1 段起就恒定，**不能**用作收敛判据。要看收敛请用字节级或剖面 diff。

* **逐站温度 RMS 对标（口径同 §11.9，`station_rms_so_compare.py`）**

  | 算例 | RMS 均值 [K] |
  |---|---:|
  | 3D 方管·EDM（热入口，旧） | **674.1** |
  | **3D 圆进口·432mm 域（V3）** | **242.0** |
  | **3D 圆进口·300mm 域（V4）** | **264.2** |
  | 轴对称·非预混平衡·二阶（最佳基准） | **215.0** |
  | 全域平面·非预混·二阶 | 463.5 |

  → **进口边界（圆分区 + 空气流动 + 文档温度）修正后，3D EDM 由 674 K 降到 242–264 K**，
  已接近非预混基准 215 K。

* **域敏感性结论**：300mm（实验尺寸）反而略差（264 vs 242 K），差 22 K。
  近轴径向分辨率几乎相同（都是 0.5 mm 起步，|y|<15 mm 内节点 23 vs 21），
  故差异**属约束（confinement）效应**：小域下伴流质量流量减半 → 卷吸受限 →
  火焰核心降温更慢（x/d=30 轴上 2091 K vs 1730 K，实验 1339 K）。
  **22 K 的域差远小于剩余模型误差（~250 K）**，两版域均可接受。

* **剩余误差归因（谱系不变，与 §11.9 一致）**：EDM 快化学 + 无辐射 + 无熄火 →
  ① 近场峰值高 200–580 K（x/d=15：2215 vs 实验 1633 K）；
  ② **火焰过短**：x/d=45 起 CFD 明显低于实验（1595 vs 1938 K）。
  要再降，需换模型（非预混平衡预期 ~215 K；需 GUI 建种子 case）。
* 产物：`results/cfd_box3d_round300.csv`、`cfd_box3d_round432.csv`、
  `results/station_rms_so_compare.csv`（已加入两行）、
  `results/figs/round_domain_compare.png`、`run/asym_report_round300.txt`、
  `run/slices_round300/`、`run/slices_round/`。

### 11.21 ★★ x/d=15 站位误差为何最大：定量归因（2026-09-16 17:25）

* **现象**：x/d=15 是所有站位 RMS 最大的（V3 573 K、V4 623 K），`ΔT_max = +582 K`。
* **逐站 T_max 对比（关键证据）**

  | 方法 | x/d=1 | 3 | **15** | 30 | 45 | 60 | 75 |
  |---|---:|---:|---:|---:|---:|---:|---:|
  | 实验 | 1893 | 1937 | **1633** | 1716 | 1938 | 1605 | 1188 |
  | 轴对称·非预混+βPDF（215K 基准） | 1831 | 1785 | **1763** | 1865 | 1833 | 1370 | 1098 |
  | 3D·EDM 300mm | 2094 | 2120 | **2215** | 2140 | 1595 | 1202 | 1031 |
  | 3D·EDM 432mm | 2093 | 2111 | **2199** | 2103 | 1642 | 1188 | 988 |

  → 非预混+βPDF 在 x/d=15 **只高 130 K**，EDM 高 **582 K**。两者差 **452 K**。

* **★ 归因分解（总 +582 K）**
  ```
  实验 1633 ──(+130 K 熄火/辐射)── 非预混平衡+βPDF 1763 ──(+452 K 缺 PDF 平均)── EDM 2215
  ```
  1. **主因：EDM 缺失混合分数脉动的 β-PDF 平均（≈452 K，占 78%）**
     EDM 解时均组分方程、反应速率用**平均量**求值（⟨ω⟩≈ω(⟨Y⟩,⟨T⟩)，一阶矩闭包），
     **不含任何标量脉动统计**。非预混方法是 ⟨T⟩=∫P(F)·T_eq(F)dF，
     天然把"时而富燃、时而贫燃"的混合状态一起平均，峰值被显著抹平。
  2. **次因：局部熄火 + 无辐射（≈130 K）** —— 平衡化学不可熄火 + 未算辐射的共同残留。
* **★ 为什么偏偏是 x/d=15？（直接因果，有数据）**

  | x/d | 1 | 2 | 3 | **15** | 30 | 45 | 60 | 75 |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|
  | 实验 T_rms [K] | 40 | 44 | 78 | **316** | 323 | 158 | 288 | 217 |
  | F_rms @T_max | .014 | .017 | .042 | **.162** | .145 | .098 | .063 | .041 |

  标量脉动 **F_rms 在 x/d=3→15 放大约 4 倍**（0.042→0.162），
  混合分数脉动的空间不均最强的站位，正是 PDF 效应最大、也正是一阶矩
  闭包失效最严重的地方 → **EDM 与非预混的偏差在此达到峰值 452 K**。
* **副产物（同一根因的另一面）**：x/d=15 烧太多 → 燃料提前耗尽 →
  **x/d=45 反而偏冷**（EDM 1595 vs 实验 1938 K，−343 K），即"火焰过短"。
  **近场过燃与下游欠燃是同一缺陷的两个表现**。
* **组分层面的实锤**：x/d=15 峰值处
  实验 Y_CH4=0.0186、**Y_O2=0.0577**（燃料与氧化剂共存未反应）；
  EDM Y_CH4=0.0201、**Y_O2=0.0117**（两者同时近零＝完全燃尽）。
  反应进度 α=(T−291)/(2220−291)：实验 **69.6%**，EDM **99.7%**。
* **解决路径**：换 **3D 非预混 + β-PDF**（预期该站 ΔT 由 582 → ~130 K，
  整体 RMS 由 264 K 降至 ~215 K 量级或更好）。注意：非预混**平衡**模型同样不可熄火，
  故剩余的 ~130 K（熄火+辐射）需要 **flamelet 带熄火 / EDC 有限速率** 才能进一步消除。
* 产物：`results/figs/x15_error_attribution.png`。

### 11.22 ★ 非预混"使能"必须经 GUI（复核确认）+ 3D pregui 备料（2026-09-16 23:10）

* **起因**：一度判断"有 `np_eq_seed.pdf` 就能脚本化 3D 非预混、不需 GUI"——**此判断错误，已更正**。
* **复核证据（`scripts/probe_np3d_a.py` / `probe_np3d_b.py`，日志同名 .log）**
  1. TUI `/define/models/species/non-premixed-combustion? yes`
     → `Error: Fuel species sum to 0 (unity sum is required)`
     （probe_np14.log 亦同）。**不是**"GUI 专属"，而是卡在燃料流组分未定义，
     但该定义**不在任何 settings 路径下**：
  2. dump `setup.models.species` → 只有 `{model, options}`，**无** fuel_stream /
     boundary_species 节点。
  3. dump `setup.materials.mixture['pdf-mixture']` → 20 个组分（ch4/n2/o2/h2o/h2/co/co2/
     oh/h/o/ho2/h2o2/ch2o/hono/c2h4/c2h6/hcooh/hco/cho/hoco）+ density=pdf 等，
     **也没有** fuel/oxidizer 流分数。
  → 结论：**使能必须经 Species Model 面板**；只有 **PDF 表读取**可脚本化
    （`s.file.read_pdf()`；注意 Write→Case **不内嵌**表）。
* **2D 种子 case 口径（回读实测）**：`species.model.option = 'non-premixed-combustion'`、
  **`energy.enabled = False`（绝热）**。
  ⚠️ `prep_np_pregui.py` 注释里写"非绝热"是**笔误**，以 run_np_eq.py 代码与实测为准（绝热）。
* **新脚本 `scripts/prep_np3d_pregui.py`**（3D 版前置，仿 2D 的 prep_np_pregui.py）：
  读 `mesh/box3d/compact_round300.msh` → k-e realizable + EWT → **energy Off** →
  3 进口 U/I/Dh → 4 壁面 → outlet 0 Pa → **硬校验回读** → 存 `run/np3d_pregui.cas.h5`。
  实测：3 进口校验全绿；壁面 thermal 报 `currently inactive`
  （**这正是 energy 已关闭的反证**，不是 bug）。
* **用户 GUI 步骤（约 2 分钟）**：打开 `run/np3d_pregui.cas.h5` →
  Species Model → Non-Premixed（Equilibrium + Beta PDF + Energy 保持 Off）→
  填燃料流 ch4 .15607/n2 .84393（**去 O2**）、氧化流 o2 .23574/h2o .006256/n2 .758 →
  OK → 另存 `run/np3d_seed.cas.h5`。
* **`render_slices.py` 两处改动（可复用）**
  1. 支持任意切片目录：`SLICE_DIR=run/slices_round300 SLICE_TAG=_round300 python scripts/render_slices.py`
     （原先写死 `run/slices` 与固定输出名，两版会互相覆盖）。
  2. **★ 伪影标注改为按数据判断**：原先写死"|y|>50mm 的红色区为 EDM 数值伪影、
     仅下侧、破坏 y 对称"——那是 V1 条带进口的情况。圆进口 V3/V4 实测
     |y|>50mm 上下侧 291.9/291.9、375.9/375.1 K **完全对称、无伪影**。
     现按 T>1000K 占比是否 <0.1% 自动切换标注，避免图件误导。
* 计算卡：`docs/CALC_CARD_3D_V5.md`；3D 云图已产出
  `results/figs/slices_{main,species,cross,y0}_round{300,432}.png`。

### 11.23 ★★ 三重证据归因：轴心超温 + 射流衰减（2026-09-16 23:20）

* **新脚本 `scripts/compare_species_rms.py`**：组分 + 混合分数逐站对标。
  **混合分数反算公式（已用实验自洽验证 r=0.9999，RMS 偏差 0.0070）**：
  ```
  Y_C = Y_CH4·(12.011/16.043) + Y_CO·(12.011/28.010) + Y_CO2·(12.011/44.009)
  F   = Y_C / Y_C,fuel ,   Y_C,fuel = 0.15607×(12.011/16.043) = 0.1170525
  ```
  （实验列 Y_* 为质量分数，各站 Ysum = 1.0000±0.004，口径无误）

* **逐站 RMS（V4 300mm，实验 r/d∈[-0.01,6.0] 口径）**

  | 量 | x1 | x2 | x3 | x15 | x30 | x45 | x60 | x75 | 均值 |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
  | T [K] | 94.8 | 91.6 | 196.8 | **622.5** | 459.1 | 236.7 | 255.5 | 104.7 | 257.7 |
  | F | .126 | .177 | .177 | **.157** | .076 | .112 | .065 | .032 | .115 |
  | O2 | .017 | .015 | .031 | .090 | .041 | .057 | .048 | .026 | .041 |
  | H2O | .008 | .007 | .015 | .049 | .025 | .026 | .020 | .009 | .020 |
  | CH4 | .020 | .029 | .026 | .018 | .011 | .001 | .000 | .000 | .013 |
  | CO2 | .010 | .008 | .017 | .054 | .040 | .019 | .028 | .015 | .024 |
  | CO | .004 | .006 | .006 | .012 | .018 | .019 | .001 | .000 | .008 |

* **★ 轴心（r/d=0）超温 — 决定性三方对比**

  | x/d | 1 | 3 | **15** | 30 | 45 | 60 | 75 |
  |---|---:|---:|---:|---:|---:|---:|---:|
  | 实验轴心 T [K] | 288 | 291 | **498** | 1339 | 1938 | 1605 | 1188 |
  | 非预混+βPDF（2D 轴对） | 294 | 317 | **713** | 1848 | 1833 | 1370 | 1098 |
  | 3D EDM 300mm | 295 | 328 | **1471** | 2091 | 1595 | 1202 | 1031 |

  物理判据：x/d=15 轴心实验 **F=0.908（富燃）+ Y_O2=0.174（有氧）却只有 498 K**
  → **混合了但没烧 = 局部熄火**；EDM 不可熄火 → 烧到 1471 K。
  → **轴心超温 ΔT=973 K 分解：缺 β-PDF 平均 758 K（78%）+ 熄火/辐射 215 K（22%）**。

* **★★ 新发现的独立误差源：射流中心线混合分数衰减过快**
  （此前 §11.21 把下游欠燃也归给"缺 PDF"，**此处修正**）

  | x/d | 3 | 15 | 30 | **45** | 60 | 75 |
  |---|---:|---:|---:|---:|---:|---:|
  | 实验 F_axis | 0.988 | 0.908 | 0.657 | **0.387** | 0.220 | 0.139 |
  | CFD F_axis | 0.997 | 0.984 | 0.538 | **0.185** | 0.119 | 0.094 |

  x/d≤15 CFD 衰减**偏慢**（0.984 vs 0.908），x/d≥30 **急剧过快**（0.185 vs 0.387）。
  → x/d=45 处燃料被过度稀释，**这才是"火焰过短"（EDM 1595 vs 实验 1938）的主因**，
    与化学模型无关。根源指向 **k-ε 圆射流衰减预测偏差**（经典 round-jet anomaly）
    + 燃烧热膨胀对流场的反馈。
  → 结论：误差有**两个独立来源**——①湍流混合/射流衰减（影响 x/d≥30）；
    ②缺 β-PDF 平均（影响 x/d=15 轴心与峰值）。换非预混只能解决 ②。
* 产物：`results/species_rms_round300.csv`、`results/figs/species_f_compare.png`、
  `results/figs/x15_axis_attribution.png`。

### 11.24 ★★★ 对照实验推翻「湍流模型误差」假设：根因收敛到 EDM（2026-09-16 23:55）

* **用户授权"自由计算"**（命中硬规则豁免①）后自主设计并执行的对照实验。
* **新脚本 `scripts/run_box3d_mix.py`**：3D 圆射流**等温惰性混合**（无燃烧）。
  与燃烧态（run_box3d_edm.py）**唯一差别就是是否燃烧**：
  energy **OFF**（等温）+ species transport（机理仅用于定义组分）+ **关闭 volumetric reactions**
  + 同网格 / 同进口 U·I·Dh / **同进口组分**（保证 F 场可比）/ 同湍流模型 / 同收敛口径。
  实测：一阶 5.09 s/步、二阶 4.66 s/步（比 EDM 6.15 s 快），300 二阶步。

* **★ 实验有效性验证（必做，已通过）—— `scripts/verify_mix_inert.py`**
  设置阶段 `volumetric reactions` 回读返回 None（`settings.get_var` 并非有效方法），
  故改用**物理层决定性判据**：惰性下 CH4 只能来自射流，则 Y_CH4 = 0.15637·w_jet，
  其中 w 由**元素守恒**（C/H + 归一化）反解（元素质量分数与反应无关）。

  | 站 | Y_CH4 实测 | 预测 | 比值 | Y_O2 实测 | 预测 | 比值 |
  |---|---|---:|---|---|---|---|
  | x/d=15 | 0.04666 | 0.04666 | **1.000** | 0.15996 | 0.15997 | **1.000** |
  | 30 | 0.01990 | 0.01990 | **1.000** | 0.20017 | 0.20017 | **1.000** |
  | 45 | 0.01352 | 0.01352 | **1.000** | 0.21152 | 0.21152 | **1.000** |
  | 60 | 0.01037 | 0.01037 | **1.000** | 0.21715 | 0.21715 | **1.000** |

  → 组分严格落在三股流混合面上 ⇒ **反应确实已关闭，惰性实验有效**。

* **★★ 核心结果：轴心混合分数衰减（r/d=0）**

  | x/d | 3 | **15** | 30 | 45 | 60 |
  |---|---:|---:|---:|---:|---:|
  | 实验（燃烧） | 0.988 | **0.908** | 0.657 | 0.387 | 0.220 |
  | **惰性混合（无燃烧）** | 0.973 | **0.395** | 0.173 | 0.118 | 0.090 |
  | 燃烧 EDM | 0.997 | **0.984** | 0.538 | 0.185 | 0.119 |

* **★★ 决定性判据：惰性解 vs 经典自由圆射流衰减律** `F_cl = K/(x/d − x0/d)`
  最小二乘拟合：**K = 5.43，x0/d ≈ −0.11**，x/d≥30 处偏差 ≤0.007。
  **文献经典值 K_d ≈ 5.4–6.2（Becker）** → **K=5.43 落在经典区间内**。

  > ⇒ **k-ε 的纯湍流混合预测是正确的**。**"k-ε 圆射流衰减过快"的假设被证伪**
  > （该假设由 §11.23 提出，此处更正）。

* **★ 修正后的误差归因（收敛到单一根因）**

  | 现象 | 证据 |
  |---|---|
  | 燃烧确实抑制射流混合（真实物理） | 惰性 x/d=45 → 0.118；实验燃烧 → 0.387 |
  | CFD 的抑制在 **x/d≤15 过强** | CFD 燃烧 0.984 vs 实验 0.908（惰性仅 0.395） |
  | CFD 的抑制在 **x/d≥30 过早消退** | CFD 燃烧 0.185 vs 实验 0.387 |
  | ⇒ 抑制效应**空间分布错误**，与 **EDM 火焰过短** 完全一致 | EDM 火焰在 x/d≈30–45 结束 |

  ⇒ **三处症状（x/d=15 轴心超温 +973 K、下游欠温 −343 K、F 场分布错误）
  指向同一个根因：EDM 燃烧模型**（不可熄火 + 火焰过短）。
  **§11.20/11.23 中"误差有两个独立来源（湍流混合 + 缺 PDF 平均）"的说法予以更正——
  湍流混合（k-ε）经对照实验证明不是误差源；剩下的只是"缺 β-PDF 平均"与
  "火焰过短"两个**表现**，同源于燃烧模型。**

* **★ 另一个有价值的旁证**：惰性混合的**温度场保持严格 291 K 等温**
  （energy off 的验证），轴心温度曲线是平直的——这也再次确认等温设置正确。
* 产物：`results/cfd_box3d_mix.csv`、`results/figs/mix_vs_burn.png`、
  `run/box3d_mix.cas.h5|.dat.h5`、`run/verify_mix_inert.log`；
  新脚本 `run_box3d_mix.py`、`verify_mix_inert.py`、`compare_mix_vs_burn.py`；
  `export_box3d_profiles.py` 的 FIELDS 增加 `n2`。
