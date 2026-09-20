"""误差预算分解：把总 RMS 拆到站位/分段，并给出关键标量偏差（诊断误差来源结构）。

产出：
  results/figs/error_budget.png   双联图：(a) 逐站 RMS 柱状（分段着色）
                                  (b) 轴线温度沿程（CFD vs 实验，标注中游误差区）
  results/error_budget.csv        逐站 RMS 表 + 分段均值 + 关键标量偏差
关键标量：峰值温度、峰位（火焰长度代理）、T_axis@x15/30/45、中心线峰值位置。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import use_cjk  # noqa: E402

use_cjk()
RES = ROOT / "results"
FIG = RES / "figs"
STATIONS = [0.75, 1, 2, 3, 15, 30, 45, 60, 75]
NEAR, MID, FAR = STATIONS[:4], STATIONS[4:7], STATIONS[7:]
RMAX = 6.0

CASES = [
    ("轴对称·二阶（基准）", "cfd_np_eq_d_v5_medium_so.csv", "#1f6fb4"),
    ("全域平面·二阶", "cfd_np_eq_d_v5_planar_full_so.csv", "#c0392b"),
]


def load_exp():
    t = pd.read_csv(RES / "tnf_flamed.csv")
    t = t[(t["flame"] == "D") & (t["kind"] == "Yave")].copy()
    for c in ("x_over_d", "r_over_d", "T"):
        t[c] = pd.to_numeric(t[c], errors="coerce")
    return t


def exp_radial(t, xd):
    e = t[np.isclose(t["x_over_d"], xd)]
    e = e[(e["r_over_d"] >= -0.01) & (e["r_over_d"] <= RMAX)]
    return e["r_over_d"].to_numpy(float), e["T"].to_numpy(float)


def exp_axis_T(t, xd):
    s = t[np.isclose(t["x_over_d"], xd)]
    if not len(s):
        return np.nan
    return float(s.loc[s["r_over_d"].abs().idxmin(), "T"])


def cfd_radial(d, xd):
    p = d[(d["profile"] == "radial") &
          np.isclose(d["x_over_d"].astype(float), xd)].sort_values("r_over_d")
    return p["r_over_d"].to_numpy(float), p["temperature"].to_numpy(float)


def cfd_axis_T(d, xd):
    c = d[d["profile"] == "centerline"]
    if not len(c):
        return np.nan
    i = int(np.argmin(np.abs(c["x_over_d"].to_numpy(float) - xd)))
    return float(c["temperature"].to_numpy(float)[i])


def station_rms(t, d, xd):
    rr, ee = exp_radial(t, xd)
    cr, ct = cfd_radial(d, xd)
    if len(rr) < 3 or len(cr) < 3:
        return np.nan
    ok = np.isfinite(rr) & np.isfinite(ee)
    rr, ee = rr[ok], ee[ok]
    m = (rr >= cr.min() - 1e-9) & (rr <= cr.max() + 1e-9)
    if m.sum() < 3:
        return np.nan
    ci = np.interp(rr[m], cr, ct)
    return float(np.sqrt(np.mean((ci - ee[m]) ** 2)))


def main():
    t = load_exp()
    data = {name: pd.read_csv(RES / path) for name, path, _ in CASES}
    for d in data.values():
        d["x_over_d"] = d["x_over_d"].astype(float)
        d["temperature"] = pd.to_numeric(d["temperature"], errors="coerce")

    # ---- 逐站 RMS 与分段 ----
    rms = {name: [station_rms(t, d, xd) for xd in STATIONS]
           for name, d in data.items()}
    seg_txt = []
    rows = []
    for name, vals in rms.items():
        a = np.array([v if v is not None else np.nan for v in vals], float)
        segs = (np.nanmean(a[:4]), np.nanmean(a[4:7]), np.nanmean(a[7:]))
        seg_txt.append((name, a, segs))
        for xd, v in zip(STATIONS, a):
            rows.append({"case": name, "x_over_d": xd, "rms_K": v})
    print(f"{'case':<20}" + "".join(f"{f'x{xd}':>8}" for xd in STATIONS)
          + f"{'近场':>8}{'中游':>8}{'远场':>8}{'总均值':>8}")
    for name, a, segs in seg_txt:
        line = f"{name:<20}" + "".join(f"{v:8.0f}" if np.isfinite(v) else f"{'—':>8}"
                                       for v in a)
        line += (f"{segs[0]:8.0f}{segs[1]:8.0f}{segs[2]:8.0f}"
                 f"{np.nanmean(a):8.1f}")
        print(line)

    # ---- 关键标量偏差 ----
    print("\n关键标量（CFD vs 实验）：")
    print(f"{'指标':<22}{'实验':>9}{'轴对称二阶':>11}{'偏差':>9}{'平面二阶':>10}{'偏差':>9}")
    scal = []

    def rec(label, e_val, a_val, p_val, unit=""):
        da = (a_val - e_val) / e_val * 100 if np.isfinite(e_val) and e_val else np.nan
        dp = (p_val - e_val) / e_val * 100 if np.isfinite(e_val) and e_val else np.nan
        print(f"{label:<22}{e_val:>9.1f}{a_val:>11.1f}{da:>8.1f}%{p_val:>10.1f}{dp:>8.1f}%")
        scal.append({"metric": label, "exp": e_val, "axisym_so": a_val,
                     "dev_axisym_pct": da, "planar_so": p_val, "dev_planar_pct": dp})

    # 中心线峰值与位置（火焰长度代理）
    for tag, name in (("axisym", "轴对称·二阶（基准）"), ("planar", "全域平面·二阶")):
        pass
    def cl_peak(d):
        c = d[d["profile"] == "centerline"].sort_values("x_over_d")
        x = c["x_over_d"].to_numpy(float)
        T = c["temperature"].to_numpy(float)
        i = int(np.argmax(T))
        return float(x[i]), float(T[i])

    # 实验中心线峰值
    xs_ = sorted(t["x_over_d"].dropna().unique())
    e_cl = [(float(x), exp_axis_T(t, x)) for x in xs_]
    e_cl = [(x, v) for x, v in e_cl if np.isfinite(v)]
    e_xpk, e_Tpk = max(e_cl, key=lambda p: p[1])
    a_xpk, a_Tpk = cl_peak(data["轴对称·二阶（基准）"])
    p_xpk, p_Tpk = cl_peak(data["全域平面·二阶"])
    rec("中心线峰值 T [K]", e_Tpk, a_Tpk, p_Tpk)
    rec("峰位 x/d", e_xpk, a_xpk, p_xpk)
    for xd in (15, 30, 45):
        rec(f"轴线 T @x/d={xd} [K]", exp_axis_T(t, xd),
            cfd_axis_T(data["轴对称·二阶（基准）"], xd),
            cfd_axis_T(data["全域平面·二阶"], xd))

    pd.DataFrame(rows).to_csv(RES / "error_budget.csv", index=False,
                              encoding="utf-8-sig")
    pd.DataFrame(scal).to_csv(RES / "error_budget_scalars.csv", index=False,
                              encoding="utf-8-sig")

    # ---- 图 ----
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.0))
    ax = axes[0]
    xpos = np.arange(len(STATIONS))
    w = 0.38
    segcol = ["#dfe6e9"] * 4 + ["#fdcb6e"] * 3 + ["#dfe6e9"] * 2
    for ax_ in (ax,):
        for i, xd in enumerate(STATIONS):
            ax_.axvspan(i - 0.5, i + 0.5, color=segcol[i], alpha=0.45, zorder=0)
    for k, (name, a, segs) in enumerate(seg_txt):
        ax.bar(xpos + (k - 0.5) * w, a, w, label=name,
               color=CASES[k][2], alpha=0.88)
    ax.set_xticks(xpos)
    ax.set_xticklabels([f"{xd:g}" for xd in STATIONS])
    ax.set_xlabel("x/d")
    ax.set_ylabel("逐站温度 RMS [K]")
    ax.set_title("(a) 逐站误差预算（黄=中游 15–45d，误差集中区）")
    ax.legend(fontsize=8.5)
    ax.grid(axis="y", alpha=0.3)

    ax = axes[1]
    for name, d in data.items():
        c = d[d["profile"] == "centerline"].sort_values("x_over_d")
        ax.plot(c["x_over_d"], c["temperature"], lw=1.8,
                color=[cc for n, _, cc in CASES if n == name][0], label=name)
    ax.plot([p[0] for p in e_cl], [p[1] for p in e_cl], "ks", ms=6,
            mfc="none", mew=1.3, label="TNF 实验")
    ax.axvspan(15, 45, color="#fdcb6e", alpha=0.25,
               label="中游敏感区（误差主贡献）")
    ax.set_xlabel("x/d")
    ax.set_ylabel("轴线温度 [K]")
    ax.set_title("(b) 轴线温度沿程（实验峰在 ~45d，CFD 峰偏前偏高）")
    ax.legend(fontsize=8.5)
    ax.grid(alpha=0.3)
    fig.suptitle("Flame D 误差来源结构：模型误差主导的中游区 + 峰值偏移", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out = FIG / "error_budget.png"
    fig.savefig(out, dpi=150)
    print(f"\n已写 {out}")


if __name__ == "__main__":
    sys.exit(main())
