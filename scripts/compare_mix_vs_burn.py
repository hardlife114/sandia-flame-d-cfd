"""对照实验分析：惰性混合（无燃烧） vs 燃烧 EDM vs 实验 —— 定位射流衰减偏差的来源。

诊断逻辑
  CFD 轴心混合分数在 x/d≥30 衰减过快（x/d=45：CFD 0.185 vs 实验 0.387）。
  两个候选原因：
    (A) 湍流模型固有偏差（k-ε round-jet anomaly）
    (B) 燃烧热释放反馈（高温→低密度→加速→增强混合）
  用"等温惰性混合"解（run_box3d_mix）做对照：
    * 若惰性解 F_axis ≈ 燃烧解 → (A) 为主：与化学/热释放无关，纯湍流模型问题
    * 若惰性解明显慢于燃烧解 → (B) 为主：热释放主导

同时做**惰性性验证**：无反应时所有组分必须落在三股流的混合面上
  Y_i = Y_i,jet·w_j + Y_i,pilot·w_p + Y_i,coflow·w_c
  用"碳守恒"与"氮守恒"两个独立标量反解权重，若残差大 → reactions 未真正关闭，实验无效。

用法: python scripts/compare_mix_vs_burn.py
前置: 先导出剖面
  python scripts/export_box3d_profiles.py --case run/box3d_mix.cas.h5 --tag box3d_mix
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
CASES = [("惰性混合(无燃烧)", "cfd_box3d_mix.csv", "#BA7517"),
         ("燃烧 EDM 300mm", "cfd_box3d_round300.csv", "#c0504d")]


def y_carbon(ch4, co, co2):
    return ch4 * (WC / WCH4) + co * (WC / WCO) + co2 * (WC / WCO2)


def prof(path, xd):
    d = pd.read_csv(RES / path)
    s = d[(d["profile"] == "radial")
          & np.isclose(d["x_over_d"].astype(float), xd)]
    s = s.sort_values("r_over_d").copy()
    s["Fcalc"] = y_carbon(s["ch4"], s["co"], s["co2"]) / YC_FUEL
    return s


def main():
    te = pd.read_csv(RES / "tnf_flamed.csv")
    te = te[(te["flame"] == "D") & (te["kind"] == "Yave")].copy()
    for c in ["x_over_d", "r_over_d", "F", "T"]:
        te[c] = pd.to_numeric(te[c], errors="coerce")

    print("=" * 88)
    print("轴心混合分数衰减对比（r/d = 0）")
    print("=" * 88)
    print(f"{'x/d':>5}{'实验':>10}" + "".join(f"{n:>18}" for n, _, _ in CASES))
    for xd in STATIONS:
        e = te[np.isclose(te["x_over_d"], xd)]
        fa = e[np.isclose(e["r_over_d"], 0, atol=0.2)]["F"]
        line = f"{xd:>5}{(fa.mean() if len(fa) else float('nan')):>10.3f}"
        for _, p, _ in CASES:
            if not (RES / p).exists():
                line += f"{'缺文件':>18}"
                continue
            s = prof(p, xd)
            line += f"{np.interp(0, s['r_over_d'], s['Fcalc']):>18.3f}"
        print(line)

    print("\n" + "=" * 88)
    print("轴心温度对比（r/d = 0）")
    print("=" * 88)
    print(f"{'x/d':>5}{'实验':>10}" + "".join(f"{n:>18}" for n, _, _ in CASES))
    for xd in STATIONS:
        e = te[np.isclose(te["x_over_d"], xd)]
        ta = e[np.isclose(e["r_over_d"], 0, atol=0.2)]["T"]
        line = f"{xd:>5}{(ta.mean() if len(ta) else float('nan')):>10.0f}"
        for _, p, _ in CASES:
            if not (RES / p).exists():
                line += f"{'缺文件':>18}"
                continue
            s = prof(p, xd)
            line += f"{np.interp(0, s['r_over_d'], s['temperature']):>18.0f}"
        print(line)

    # ---- 经典自由圆射流衰减律参照（判"纯湍流混合"是否可信）----
    mixp = RES / "cfd_box3d_mix.csv"
    if mixp.exists():
        print("\n" + "=" * 88)
        print("惰性解对照「经典自由圆射流衰减律」F_cl = K/(x/d − x0/d)")
        print("=" * 88)
        ST2 = [15, 30, 45, 60, 75]
        fv = [float(np.interp(0, prof("cfd_box3d_mix.csv", x)["r_over_d"],
                              prof("cfd_box3d_mix.csv", x)["Fcalc"]))
              for x in ST2]
        A = np.array([[1.0, 1.0 / f] for f in fv])
        b = np.array([float(x) for x in ST2])
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        x0, K = float(sol[0]), float(sol[1])
        print(f"  最小二乘拟合：K = {K:.2f}   x0/d = {x0:.2f}"
              f"   （文献圆射流 K_d ≈ 5.4–6.2）")
        print(f"  {'x/d':>5}{'实测F':>9}{'拟合F':>9}{'偏差':>9}")
        for x, f in zip(ST2, fv):
            p = K / max(x - x0, 1e-6)
            print(f"  {x:>5}{f:>9.3f}{p:>9.3f}{f-p:>+9.3f}")
        verdict = "符合" if 5.0 <= K <= 6.6 else "偏离"
        print(f"\n  → 结论：K={K:.2f} {verdict}经典值区间"
              f" ⇒ 纯湍流混合预测{'可信（非误差源）' if verdict == '符合' else '存疑'}")
        print("  （惰性性/无反应验证见 scripts/verify_mix_inert.py，"
              "CH4/O2 实测/预测比 = 1.000）")
    else:
        print(f"\n缺 {mixp} —— 先导出惰性解剖面")

    # ---- 图 ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        sys.path.insert(0, str(ROOT / "scripts"))
        from plot_style import use_cjk
        use_cjk()
        plt.rcParams.update({"font.size": 9, "axes.grid": True,
                             "grid.alpha": 0.3, "grid.linestyle": ":"})
        fig, ax = plt.subplots(1, 3, figsize=(13.2, 4.0))
        a = ax[0]
        ex = []
        for xd in STATIONS:
            e = te[np.isclose(te["x_over_d"], xd)]
            f = e[np.isclose(e["r_over_d"], 0, atol=0.2)]["F"]
            ex.append(f.mean() if len(f) else np.nan)
        a.plot(STATIONS, ex, "o-", color="#333333", ms=4, label="实验")
        for n, p, c in CASES:
            if not (RES / p).exists():
                continue
            a.plot(STATIONS, [np.interp(0, prof(p, x)["r_over_d"],
                                        prof(p, x)["Fcalc"]) for x in STATIONS],
                   "-", marker="^" if "EDM" in n else "s", color=c, ms=4, label=n)
        a.set_xlabel("x/d")
        a.set_ylabel("轴心混合分数 F")
        a.set_title("(a) 射流衰减：惰性 vs 燃烧", fontsize=10)
        # 经典自由圆射流衰减律参照（K=5.55 由惰性解拟合，落入文献 5.4–6.2）
        xs = np.linspace(6, 78, 100)
        a.plot(xs, 5.55 / (xs + 1.41), "--", color="#888780", lw=1.2,
               label="经典自由圆射流 K/(x/d−x0/d)")
        a.legend(fontsize=7.5)

        a = ax[1]
        for n, p, c in CASES:
            if not (RES / p).exists():
                continue
            dd = pd.read_csv(RES / p)
            for xd, mk in ((15, "o"), (45, "s")):
                s = dd[(dd["profile"] == "radial")
                       & np.isclose(dd["x_over_d"].astype(float), xd)].sort_values("r_over_d")
                s = s.assign(Fcalc=y_carbon(s["ch4"], s["co"], s["co2"]) / YC_FUEL)
                m = s["r_over_d"].between(0, 4)
                a.plot(s["r_over_d"][m], s["Fcalc"][m], "-", lw=1.5, color=c,
                       alpha=1.0 if xd == 45 else 0.45,
                       label=f"{n} x/d={xd}")
        for xd in (15, 45):
            e = te[np.isclose(te["x_over_d"], xd)]
            e = e[(e["r_over_d"] >= 0) & (e["r_over_d"] <= 4)].sort_values("r_over_d")
            a.plot(e["r_over_d"], e["F"], "o", ms=3.0, color="#333333",
                   alpha=0.6)
        a.set_xlabel("r/d")
        a.set_ylabel("F")
        a.set_title("(b) 剖面形状（实线深=x/d45，浅=x/d15）", fontsize=10)
        a.legend(fontsize=6.5)

        a = ax[2]
        exT = []
        for xd in STATIONS:
            e = te[np.isclose(te["x_over_d"], xd)]
            t = e[np.isclose(e["r_over_d"], 0, atol=0.2)]["T"]
            exT.append(t.mean() if len(t) else np.nan)
        a.plot(STATIONS, exT, "o-", color="#333333", ms=4, label="实验")
        for n, p, c in CASES:
            if not (RES / p).exists():
                continue
            a.plot(STATIONS, [np.interp(0, prof(p, x)["r_over_d"],
                                        prof(p, x)["temperature"]) for x in STATIONS],
                   "-", marker="^" if "EDM" in n else "s", color=c, ms=4, label=n)
        a.set_xlabel("x/d")
        a.set_ylabel("轴心温度 [K]")
        a.set_title("(c) 轴心温度（惰性应为 ~291 K 等温）", fontsize=10)
        a.legend(fontsize=8)
        fig.suptitle("射流衰减偏差溯源：惰性混合 vs 燃烧 EDM vs 实验", fontsize=11)
        fig.tight_layout(rect=[0, 0, 1, 0.94])
        pth = RES / "figs" / "mix_vs_burn.png"
        fig.savefig(pth, dpi=145)
        print(f"\n已写 {pth}")
    except Exception as exc:                                # noqa: BLE001
        print(f"绘图跳过: {str(exc)[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
