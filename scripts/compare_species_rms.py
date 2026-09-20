"""组分 + 混合分数逐站对标（3D 圆进口 vs Sandia Flame D 实验）。

目的：把 x/d=15 的误差归因从"温度单一证据"升级为**温度 + 组分 + 混合分数**
三重证据 —— 若 CFD 的混合分数场与实验吻合，则证明"湍流混合预测正确，
问题出在湍流-化学耦合（缺 β-PDF 平均）"。

口径：与 station_rms_so_compare.py 一致
  实验点 r/d ∈ [-0.01, 6.0]；CFD radial 剖面 r≥0 插值（负 r 外插=边缘值）。
  RMS = sqrt(mean((CFD-EXP)^2))

混合分数定义（★ 已用实验数据自洽验证，r=0.9999）：
  以碳元素为基准，F = Y_C / Y_C,fuel
  Y_C = Y_CH4·(12.011/16.043) + Y_CO·(12.011/28.010) + Y_CO2·(12.011/44.009)
  Y_C,fuel = 0.15607 × (12.011/16.043) = 0.1170525
  （氧化流无碳 → Y_C,ox = 0）

产出：results/species_rms_round300.csv + 控制台表 + results/figs/species_f_compare.png

用法: python scripts/compare_species_rms.py [cfd_csv_tag]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"

WC, WCO2, WCO, WCH4 = 12.011, 44.009, 28.010, 16.043
YC_FUEL = 0.15607 * (WC / WCH4)
STATIONS = [1, 2, 3, 15, 30, 45, 60, 75]
# 实验列名 -> CFD csv 列名
SPECIES = [("Y_O2", "o2"), ("Y_H2O", "h2o"), ("Y_CH4", "ch4"),
           ("Y_CO2", "co2"), ("Y_CO", "co")]


def y_carbon(ch4, co, co2):
    return ch4 * (WC / WCH4) + co * (WC / WCO) + co2 * (WC / WCO2)


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "cfd_box3d_round300.csv"

    te = pd.read_csv(RES / "tnf_flamed.csv")
    te = te[(te["flame"] == "D") & (te["kind"] == "Yave")].copy()
    for c in ["x_over_d", "r_over_d", "F", "T", "Y_O2", "Y_H2O",
              "Y_CH4", "Y_CO2", "Y_CO"]:
        te[c] = pd.to_numeric(te[c], errors="coerce")

    cache: dict = {}

    def cfd(xd):
        if xd not in cache:
            d = pd.read_csv(RES / tag)
            s = d[(d["profile"] == "radial")
                  & np.isclose(d["x_over_d"].astype(float), xd)]
            s = s.sort_values("r_over_d")
            cache[xd] = s
        return cache[xd]

    def cfd_field(xd, name):
        s = cfd(xd)
        rr = s["r_over_d"].to_numpy(float)
        if name == "F":
            ct = y_carbon(s["ch4"], s["co"], s["co2"]) / YC_FUEL
            ct = ct.to_numpy(float)
        elif name == "T":
            ct = s["temperature"].to_numpy(float)
        else:
            ct = s[name].to_numpy(float)
        return rr, ct

    def station_rms(exp_col, cfd_name):
        vals = []
        for xd in STATIONS:
            e = te[np.isclose(te["x_over_d"], xd)]
            e = e[(e["r_over_d"] >= -0.01) & (e["r_over_d"] <= 6.0)]
            er = e["r_over_d"].to_numpy(float)
            ev = e[exp_col].to_numpy(float)
            m = np.isfinite(er) & np.isfinite(ev)
            if m.sum() == 0:
                vals.append(np.nan)
                continue
            rr, ct = cfd_field(xd, cfd_name)
            vals.append(float(np.sqrt(np.mean(
                (np.interp(er[m], rr, ct) - ev[m]) ** 2))))
        return np.array(vals)

    rows = [("温度 T", "T", "T", "K"),
            ("混合分数 F", "F", "F", "—")]
    for ec, cn in SPECIES:
        rows.append((ec.replace("Y_", ""), ec, cn, "—"))

    out, table = [], {}
    for lab, ec, cn, unit in rows:
        v = station_rms(ec, cn)
        table[lab] = v
        out.append({"quantity": lab, "unit": unit,
                    **{f"x{x}": (v[i] if np.isfinite(v[i]) else None)
                       for i, x in enumerate(STATIONS)},
                    "mean": float(np.nanmean(v))})

    for r in out:
        r["mean"] = r["mean"]

    print("=" * 96)
    print(f"逐站 RMS（{tag}）")
    print("=" * 96)
    print(f"{'量':<12}" + "".join(f"{'x'+str(x):>9}" for x in STATIONS)
          + f"{'均值':>10}")
    for r in out:
        line = f"{r['quantity']:<12}"
        for x in STATIONS:
            v = r.get(f"x{x}")
            line += (f"{v:>9.3f}" if v is not None and r["unit"] == "K"
                     else (f"{v:>9.4f}" if v is not None else f"{'—':>9}"))
        line += (f"{r['mean']:>10.1f}" if r["unit"] == "K"
                 else f"{r['mean']:>10.4f}")
        print(line)
    print("\n口径：实验 r/d∈[-0.01,6.0]，CFD 插值；RMS[K] 或 RMS[质量分数]")
    dst = RES / "species_rms_round300.csv"
    pd.DataFrame(out).to_csv(dst, index=False, encoding="utf-8-sig")
    print(f"\n已写 {dst}")

    # ---- 图：混合分数与组分剖面对比 ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        sys.path.insert(0, str(ROOT / "scripts"))
        from plot_style import use_cjk
        use_cjk()
        fig, ax = plt.subplots(2, 3, figsize=(13.0, 6.8))
        panels = [("F", "混合分数 F"), ("T", "温度 T [K]"), ("o2", "Y_O2"),
                  ("h2o", "Y_H2O"), ("co2", "Y_CO2"), ("ch4", "Y_CH4")]
        expcol = {"F": "F", "T": "T", "o2": "Y_O2", "h2o": "Y_H2O",
                  "co2": "Y_CO2", "ch4": "Y_CH4"}
        for k, (cn, lab) in enumerate(panels):
            a = ax.ravel()[k]
            for xd, col, mk in ((15, "#c0504d", "o"), (30, "#1f4e79", "s"),
                                (45, "#548235", "^")):
                e = te[np.isclose(te["x_over_d"], xd)].sort_values("r_over_d")
                e = e[(e["r_over_d"] >= 0) & (e["r_over_d"] <= 4)]
                a.plot(e["r_over_d"], e[expcol[cn]], mk, ms=3.2, color=col,
                       alpha=0.85, label=f"实验 x/d={xd}" if k == 0 else None)
                rr, ct = cfd_field(xd, cn)
                m = rr <= 4
                a.plot(rr[m], ct[m], "-", lw=1.3, color=col)
            a.set_xlabel("r/d")
            a.set_ylabel(lab)
            a.set_title(lab.split()[0] + "：点=实验，线=CFD", fontsize=10)
            if k == 0:
                a.legend(fontsize=7.5)
        fig.suptitle("3D 圆进口 EDM（300mm 域）· 混合分数与组分对标 Sandia Flame D",
                     fontsize=11)
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        p = RES / "figs" / "species_f_compare.png"
        fig.savefig(p, dpi=145)
        print(f"已写 {p}")
    except Exception as exc:                                # noqa: BLE001
        print(f"绘图跳过: {str(exc)[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
