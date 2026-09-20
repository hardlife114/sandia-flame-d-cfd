# 算例归档：box3d_mix

> 归档时间：2026-09-20 19:55:36　代码版本：`26b8ac5` (v0.1.0)　分支：`main`　**工作区有未提交改动**

## 复现标准

按本清单可在本机重跑出同一结果。复现所需全部要素如下：

| 要素 | 内容 |
|---|---|
| 代码版本 | commit `26b8ac58f87c1296120297059d3aabf0edead36d` |
| 环境 | Fluent —  / — 核 |
| 网格 | `mesh/box3d/compact_round300.msh` （160.2 MB，sha256 `1c16e29936266838…`） |
| 算例定义 | `run/box3d_mix.cas.h5` （21.6 MB，sha256 `bf3d4b4f47d54756…`） — 内含网格指针与全部模型/边界/求解设置 |
| 收敛场 | `run/box3d_mix.dat.h5` （129.8 MB，sha256 `e9a70ddf58933001…`） — 仅用于复核，非复现必需 |
| 驱动日志 | `run/log_box3d_mix.txt` |

## 网格生成命令

```bash
python scripts/gen_mesh_box3d.py --compact --round --half-mm 150 --dmin 0.5 --dmax 10 --out mesh/box3d/compact_round300.msh
```

## 边界条件（逐项回读记录，非回忆）


日志原始记录（去重后全文，供独立核对）：

```text
velocity-inlet-3: U=49.6 I=0.0879 Dh=0.0072 组分={'ch4': 0.15637, 'o2': 0.1965}
velocity-inlet-4: U=11.4 I=0.1092 Dh=0.0105 组分={'co': 0.00407, 'co2': 0.1098, 'h2o': 0.0942, 'o2': 0.054}
velocity-inlet-5: U=0.9 I=0.01 Dh=0.3 组分={'h2o': 0.00626, 'o2': 0.23574}
[校验] velocity-inlet-3     U=49.6(应 49.6)  ✓
[校验] velocity-inlet-4     U=11.4(应 11.4)  ✓
[校验] velocity-inlet-5     U=0.9(应 0.9)  ✓
```

## 求解设置与阶段序列

| 项 | 值 |
|---|---|
| 冷流步数 | 60 |
| 反应步数 | 300 |
| 分段 | 1 段 × None 步 |
| URF | None |
| 二阶离散方程数 | None |
| 单步耗时中位 | 4.66 s |

## 复现步骤

```bash
# 1) 检出该版本代码
git checkout 26b8ac5

# 2) 重建网格（若未随备份携带 .msh）
#    命令见上「网格生成命令」

# 3) 用归档的 case 直接续算，或从头重跑：
#    推荐：直接读回算例定义
#    run/box3d_mix.cas.h5 内含网格与全部设置
```