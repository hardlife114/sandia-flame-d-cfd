"""全域 planar 二阶 vs 各基准的逐站温度 RMS 对比（口径与 accuracy_axisym_vs_planar 一致）。

口径：实验点 r∈[-0.01,6.0]（含负 r），CFD radial 剖面 r>=0 插值（负 r 外插=边缘值），
RMS[K] = sqrt(mean((CFD-EXP)^2))。
四方：planar_full_so（全域二阶，本次） / planar_full（全域一阶） /
      medium_so（轴对称二阶） / medium_full3k（轴对称一阶）。
产出：results/station_rms_so_compare.csv + 控制台表。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"

CASES = [
    ("全域平面·二阶(本次)", "cfd_np_eq_d_v5_planar_full_so.csv"),
    ("全域平面·一阶",       "cfd_np_eq_d_v5_planar_full.csv"),
    ("全域平面·加密网格",   "cfd_np_eq_d_v5_planar_full_dense.csv"),
    ("轴对称·二阶",         "cfd_np_eq_d_v5_medium_so.csv"),
    ("轴对称·一阶",         "cfd_np_eq_d_v5_medium_full3k.csv"),
    ("3D方管·EDM(热入口)",  "cfd_box3d_edm.csv"),
    ("轴对称·EDM(冷入口)",  "cfd_edm_d_v5_coarse_2step_c_fo.csv"),
    ("3D圆进口·300mm域",    "cfd_box3d_round300.csv"),
    ("3D圆进口·432mm域",    "cfd_box3d_round432.csv"),
]
STATIONS = [0.75, 1, 2, 3, 15, 30, 45, 60, 75]


def main():
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

    def station_rms(path, xd):
        if not (RES / path).exists():
            return None
        d = pd.read_csv(RES / path)
        ds = d[(d["profile"] == "radial") & np.isclose(d["x_over_d"].astype(float), xd)]
        if not len(ds):
            return None
        ds = ds.sort_values("r_over_d")
        rr = ds["r_over_d"].to_numpy(float)
        tt = ds["temperature"].to_numpy(float)
        er, eT = exp_station(xd)
        if len(er) == 0:
            return None
        ci = np.interp(er, rr, tt)
        return float(np.sqrt(np.mean((ci - eT) ** 2)))

    rows = []
    for name, path in CASES:
        row = {"case": name}
        vals = []
        for xd in STATIONS:
            r = station_rms(path, xd)
            row[f"x{xd}"] = r
            if r is not None:
                vals.append(r)
        row["mean"] = float(np.mean(vals)) if vals else float("nan")
        rows.append(row)

    out = pd.DataFrame(rows)
    dst = RES / "station_rms_so_compare.csv"
    out.to_csv(dst, index=False, encoding="utf-8-sig")

    hdr = f"{'case':<18}" + "".join(f"{f'x{xd}':>8}" for xd in STATIONS) + f"{'均值':>8}"
    print(hdr)
    for _, r in out.iterrows():
        line = f"{r['case']:<18}"
        for xd in STATIONS:
            v = r[f"x{xd}"]
            line += f"{v:8.0f}" if pd.notna(v) else f"{'—':>8}"
        line += f"{r['mean']:8.1f}"
        print(line)
    print(f"\n已写 {dst}")


if __name__ == "__main__":
    sys.exit(main())
