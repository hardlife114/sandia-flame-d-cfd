# 算例归档：np_eq_d_v5_medium_so

> 归档时间：2026-09-20 19:55:41　代码版本：`26b8ac5` (v0.1.0)　分支：`main`　**工作区有未提交改动**

## 复现标准

按本清单可在本机重跑出同一结果。复现所需全部要素如下：

| 要素 | 内容 |
|---|---|
| 代码版本 | commit `26b8ac58f87c1296120297059d3aabf0edead36d` |
| 环境 | Fluent 2025 R2  / 10 核 |
| 网格 | `mesh/v5/medium.msh` （19.5 MB，sha256 `fb7123eb7c185ea7…`） |
| 算例定义 | `run/np_eq_d_v5_medium_so.cas.h5` （3.2 MB，sha256 `0f792a5897d8e55e…`） — 内含网格指针与全部模型/边界/求解设置 |
| 收敛场 | `run/np_eq_d_v5_medium_so.dat.h5` （25.6 MB，sha256 `03e1a3420919ddc8…`） — 仅用于复核，非复现必需 |
| 驱动日志 | `run/log_np_eq_d_v5_medium_so.txt` |

## 网格生成命令

```bash
# 见 scripts/gen_mesh_box3d.py / gen_mesh.py，目标：mesh/v5/medium.msh
```

## 边界条件（逐项回读记录，非回忆）


日志原始记录（去重后全文，供独立核对）：

```text
velocity-inlet-5: f=1.0 OK（键 mean_mixture_fraction，回读={'option': 'value', 'value': 1.0}）
velocity-inlet-6: f=0.27 OK（键 mean_mixture_fraction，回读={'option': 'value', 'value': 0.27}）
velocity-inlet-7: f=0.0 OK（键 mean_mixture_fraction，回读={'option': 'value', 'value': 0}）
```

## 求解设置与阶段序列

| 项 | 值 |
|---|---|
| 冷流步数 | None |
| 反应步数 | 3000 |
| 分段 | None 段 × None 步 |
| URF | 0.5 |
| 二阶离散方程数 | 5 |
| 单步耗时中位 | 0.57 s |

## 复现步骤

```bash
# 1) 检出该版本代码
git checkout 26b8ac5

# 2) 重建网格（若未随备份携带 .msh）
#    命令见上「网格生成命令」

# 3) 用归档的 case 直接续算，或从头重跑：
#    推荐：直接读回算例定义
#    run/np_eq_d_v5_medium_so.cas.h5 内含网格与全部设置
```