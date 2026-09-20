"""x/d=30 站：轴对称 vs 平面2D vs 实验 的精度对比（含全站 RMS 表）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"

t = pd.read_csv(RES / "tnf_flamed.csv")
t = t[(t["flame"] == "D") & (t["kind"] == "Yave")].copy()
for c in ("x_over_d", "r_over_d", "T"):
    t[c] = pd.to_numeric(t[c], errors="coerce")


def exp_station(xd):
    e = t[np.isclose(t["x_over_d"], xd)]
    e = e[(e["r_over_d"] >= -0.01) & (e["r_over_d"] <= 6.0)]
    er = e["r_over_d"].to_numpy(float)
    eT = e["T"].to_numpy(float)
    ok = np.isfinite(er) & np.isfinite(eT)
    return er[ok], eT[ok]


def feat(path, xd=30):
    if not os.path.exists(path):
        return None
    d = pd.read_csv(path)
    d30 = d[(d["profile"] == "radial") & np.isclose(d["x_over_d"].astype(float), xd)]
    if not len(d30):
        return None
    d30 = d30.sort_values("r_over_d")
    rr = d30["r_over_d"].to_numpy(float)
    tt = d30["temperature"].to_numpy(float)
    j = int(np.argmax(tt))
    axv = float(tt[np.argmin(np.abs(rr))])
    er, eT = exp_station(xd)
    ci = np.interp(er, rr, tt)
    dlt = ci - eT
    rms = float(np.sqrt(np.mean(dlt ** 2)))
    keep = eT >= 300
    rrms = float(np.sqrt(np.mean((dlt[keep] / eT[keep]) ** 2))) * 100 if keep.sum() else float("nan")
    return float(tt[j]), float(rr[j]), axv, rms, rrms


# ---- x/d=30 站对比 ----
er, eT = exp_station(30)
i = int(np.argmax(eT))
e_peak = (float(eT[i]), float(er[i]))
e_ax = float(eT[np.argmin(np.abs(er))])
m = feat(str(RES / "cfd_np_eq_d_v5_medium_full3k.csv"))
p = feat(str(RES / "cfd_np_eq_d_v5_planar_full.csv"))

print("=== x/d=30 站精度对比 ===")
print(f"{'':>16} {'T_axis':>8} {'T_max':>8} {'r@Tmax':>7} {'RMS[K]':>8} {'相对%':>7}")
print(f"{'实验':>16} {e_ax:8.1f} {e_peak[0]:8.1f} {e_peak[1]:7.2f} {'—':>8} {'—':>7}")
for lab, v in (("轴对称(真3000步)", m), ("平面2D(planar)", p)):
    if v is None:
        print(f"{lab:>16}   (CSV 未导出)")
        continue
    print(f"{lab:>16} {v[2]:8.1f} {v[0]:8.1f} {v[1]:7.2f} {v[3]:8.1f} {v[4]:7.1f}")

# ---- 全站 RMS 表 ----
print("\n=== 全站温度 RMS [K] ===")
print(f"{'x/d':>6} | {'轴对称':>8} {'平面2D':>8}")
ta, tb = [], []
for xd in (0.75, 1, 2, 3, 15, 30, 45, 60, 75):
    va = feat(str(RES / "cfd_np_eq_d_v5_medium_full3k.csv"), xd)
    vb = feat(str(RES / "cfd_np_eq_d_v5_planar_full.csv"), xd)
    sa = f"{va[3]:8.1f}" if va else "     —"
    sb = f"{vb[3]:8.1f}" if vb else "     —"
    if va:
        ta.append(va[3])
    if vb:
        tb.append(vb[3])
    print(f"{xd:6g} | {sa} {sb}")
print(f"{'均值':>6} | {np.mean(ta):8.1f} {(np.mean(tb) if tb else float('nan')):8.1f}")
