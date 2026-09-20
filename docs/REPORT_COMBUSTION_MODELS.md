# 燃烧模型对比试验报告（Flame D）

**日期**：2026-09-12  
**初场**：`run/edm_coarse_2step_c_only_fo`（EDM + 两步 WD，已点燃，T_max@x/d=30≈2223 K）  
**脚本**：`scripts/switch_model.py`；日志 `run/switch_model.log`、`run/run_edm.log`

---

## 1. 试验矩阵

| # | 模型 | 机理 | 初场 | 步数 | 结果 |
|---|---|---|---|---:|---|
| 0 | **EDM**（基准） | 2-step WD（Ea 48.4/24 kcal） | 从零点火 | 2500 | ✅ **燃烧** T≈2220 K |
| 1 | **EDC** | 同上（case 内机理） | EDM 场 | 1500 | ❌ **250 步内熄火** → 320 K |
| 2 | **finite-rate/eddy-dissipation** | 同上 | EDM 场 | 2000 | ❌ **250 步内熄火** → ~310–359 K |
| 3 | **EDC** | 重导入 **relaxed**（Ea 20/15 kcal） | EDM 场 | 1500 | ❌ 熄火 → ~303 K |
| 4 | **EDC** | 重导入 **ultra**（Ea 12/8 kcal） | EDM 场 | 800 | ❌ 熄火 → ~323 K |
| 5 | **EDM→EDC**（从零） | ultra（12/8） | 冷场，EDM 200 步点着后切 EDC | 1200 | ❌ EDC 200 步内熄火 |

`state=eddy-dissipation` 允许值实测：`finite-rate/no-tci` / `finite-rate/eddy-dissipation` / `eddy-dissipation` / `eddy-dissipation-concept`。

EDC 默认常数：`volume_fraction_constant=2.1377`，`time_scale_constant=0.40825`，`chemistry_solver=stiff-solver`。

---

## 2. 结论

1. **在本机 Fluent 2025 R2 headless + 全局两步机理下，只有纯 EDM 能维持 Sandia D 的燃烧场。**
2. **EDC 与 finite-rate/EDM 一旦切换，均在约 200–250 步内吹熄**，且与活化能（放宽到 12 kcal/mol）**无关**。
3. 因此熄火主因**不是 Arrhenius 太慢**这么简单，更可能是：
   - EDC 细结构刚性积分在本环境/本网格上与全局机理不兼容；
   - 或 `finite-rate/eddy-dissipation` 的 min(有限速率, EDM) 实现下有限速率项把源项压到近零；
   - 重导入机理后 `turb_chem` 曾回落为 `finite-rate/no-tci`，虽随后设回 EDC，仍不能排除机理-场耦合异常。
4. **生产算例 D/E/F 继续使用纯 EDM + 两步 WD 机理**（已恢复 `mechanism/ch4_2step_chem.inp`）。
5. 若要 EDC/有限速率路径，下一步应：
   - 用 **GRI 3.0** 从 EDM 场续算（12.6 s/步，需并行死锁防护）；
   - 或查 transcript 中 EDC 化学迭代是否真正执行；
   - 或 GUI 中核对 EDC/源项面板设置。

---

## 3. 产物

| 文件 | 说明 |
|---|---|
| `results/cfd_edm_coarse_2step_c_only_fo_edc.csv` | EDC 熄火后剖面 |
| `results/cfd_edm_coarse_2step_c_only_fo_finite-rate-edm.csv` | 混合模型熄火后剖面 |
| `results/cfd_edm_d_edc_relaxed_relaxed.csv` | relaxed-Ea EDC |
| `results/cfd_edc_ultra_ultra.csv` | ultra-Ea EDC |
| `mechanism/ch4_2step_wd_chem.inp` | 生产用 WD 两步（备份） |
| `mechanism/ch4_2step_relaxed_*` / `_ultra_*` | 诊断用低活化能机理 |
| `scripts/switch_model.py` | 模型切换工具（含 `--reimport-mech`） |

---

## 4. 对研究报告的修订意见

在 `REPORT_SANDIA_DEF.md` §3 增加：

> **燃烧模型敏感性（2026-09-12 补充）**：在已点燃的 EDM 场上切换为 EDC 或 finite-rate/EDM，  
> 均在数百步内全局熄火；将两步机理活化能降至 12 kcal/mol 仍如此。  
> **全局化学 + 本环境 headless 下，纯 EDM 是唯一能维持燃烧的湍流-化学耦合模型。**  
> D/E/F 主结果均基于 EDM；EDC/有限速率结果不可用。详见 `REPORT_COMBUSTION_MODELS.md`。
