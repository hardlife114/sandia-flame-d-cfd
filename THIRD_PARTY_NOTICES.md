# Third-Party Notices

本仓库中**除下列材料外**的全部内容（本项目自行编写的仿真脚本、网格生成器、
后处理与分析工具、文档，以及本项目生成的图件）均按根目录 `LICENSE` 中的
**MIT License** 授权。

下列材料来自第三方，遵循其自身条款，**不在 MIT 授权范围内**。

---

## 1. GRI-Mech 3.0 化学机理

| 文件 | 说明 |
|---|---|
| `mechanism/grimech30_chem.inp` | 反应机理 |
| `mechanism/grimech30_thermo.dat` | 热力学数据 |
| `mechanism/grimech30_transport.dat` | 输运数据 |

**来源**：Gas Research Institute (GRI)。由加州大学伯克利分校、斯坦福大学、
德克萨斯大学奥斯汀分校与 SRI International 共同开发。

**条款**：免费供研究与**非商业**用途使用。使用方应致谢 GRI-Mech 3.0 并引用开发者。
权威条款见 <http://combustion.berkeley.edu/gri-mech/>，其效力优先于本仓库的 MIT 授权。

> 说明：本仓库同时提供的 `ch4_1step_*`、`ch4_2step_*` 机理为本项目自行编写的简化机理，
> 属 MIT 授权范围。

## 2. TNF 实验数据 —— Sandia Flame D

| 文件 | 说明 |
|---|---|
| `results/tnf_flamed.csv` | 实验测得的温度、组分、混合分数剖面 |

**来源**：Sandia National Laboratories，"Piloted CH4/Air Flames C, D, E and F"
（Barlow & Frank），经 **International Workshop on Measurement and Computation of
Turbulent Nonpremixed Flames (TNF)** 公开分发。

**条款**：公开发布供模型验证使用。使用方应引用原始实验文献。
MIT 授权**不适用**于该数据；请遵循 TNF 工作组的使用条款。

## 3. ANSYS Fluent

本仓库**不分发** ANSYS 软件。全部仿真结果由正版授权的 **ANSYS Fluent 2025 R2** 产生。
仓库中的脚本通过 PyFluent API 驱动求解器，PyFluent 由 ANSYS, Inc. 按其自身许可分发。

---

## 再分发提示

若您转分发本仓库，请保留本文件，以免第三方材料被误认为 MIT 授权。
