"""flameD 网格收敛性（GCI）与精度对比。

输入：v4 三级网格的 CFD 剖面 CSV（同物理设置、只变网格）。
输出：
  * results/gci_flamed.csv      —— 各量化指标的 GCI 表
  * results/figs/gci_flamed.png —— 收敛曲线 + GCI 柱状图

方法（Roache, 1994/1998）：
  令 φ1/φ2/φ3 为细/中/粗网格上的同一标量，ε21 = φ2-φ1，ε32 = φ3-φ2，
  r21 = h2/h1，r32 = h3/h2（h 用有效网格尺度 h_eff = sqrt(V_domain/N_cells)）。
  表观阶数 p 由下式迭代求解：

      p = (1/ln r21) * | ln|ε32/ε21| + ln( (r21^p - 1) / (r32^p - 1) ) |

  细网格 GCI（安全因子 Fs = 1.25，工程推荐）：

      GCI_fine = Fs * |ε21/φ1| / (r21^p - 1)

  并要求渐近区指标 AR = ε32/ε21 接近 r21^p（偏离越小越可信）。
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import flamed_common as C          # noqa: E402
from gen_mesh import build_axis    # noqa: E402
from plot_style import use_cjk     # noqa: E402

CJK = use_cjk()

FIG = ROOT / "results" / "figs"
V_DOMAIN = 0.1055334               # pi*R^2*L，三级实测一致
FS = 1.25


# ---------------------------------------------------------------- 指标提取
def radial_at(df: pd.DataFrame, xd: float, col: str = "temperature",
              rmax: float = 4.5) -> np.ndarray:
    d = df[(df["profile"] == "radial") &
           np.isclose(df["x_over_d"].astype(float), xd) &
           (df["r_over_d"] >= -1e-9) & (df["r_over_d"] <= rmax)]
    return d.sort_values("r_over_d")[col].to_numpy(float)


def metrics_of(df: pd.DataFrame, stations) -> dict:
    """注意：稳态解呈极限环时，**场平均**与**量平均**只在**线性泛函**上等价。
    "径向 T 的最大值"是非线性的（峰值位置在振荡，场平均会把峰抹平，且偏差随网格不同），
    因此 GCI 的量化指标改用固定空间位置的取值与径向积分。
    """
    m = {}
    for xd in stations:
        d = df[(df["profile"] == "radial") &
               np.isclose(df["x_over_d"].astype(float), xd) &
               (df["r_over_d"] >= -1e-9) & (df["r_over_d"] <= 4.5)
               ].sort_values("r_over_d")
        if not len(d):
            continue
        rr = d["r_over_d"].to_numpy(float)
        tstd = d["T_std"].to_numpy(float) if "T_std" in d.columns else None
        for rq in (0.0, 1.0, 1.5, 2.0, 3.0):
            if rr.min() - 1e-9 <= rq <= rr.max() + 1e-9:
                m[f"T@x/d={xd:g},r/d={rq:g}"] = float(
                    np.interp(rq, rr, d["temperature"]))
                if tstd is not None:
                    m[f"SE_T@x/d={xd:g},r/d={rq:g}"] = float(
                        np.interp(rq, rr, tstd))
                if "co2" in d.columns:
                    m[f"CO2@x/d={xd:g},r/d={rq:g}"] = float(
                        np.interp(rq, rr, d["co2"]))
        # 线性泛函：径向积分（对平均与求和的交换是线性的）
        tv = d["temperature"].to_numpy(float)
        m[f"intT@x/d={xd:g}"] = float(
            np.sum(0.5 * (tv[1:] + tv[:-1]) * np.diff(rr)))
        # 供参考（非线性）
        m[f"Tmax@x/d={xd:g}"] = float(d["temperature"].max())
    cl = df[df["profile"] == "centerline"].sort_values("x_over_d")
    if len(cl):
        m["T_cl@x/d=30"] = float(np.interp(30.0, cl["x_over_d"], cl["temperature"]))
        m["T_cl@x/d=45"] = float(np.interp(45.0, cl["x_over_d"], cl["temperature"]))
        i = int(np.argmax(cl["temperature"].to_numpy(float)))
        m["x/d_cl_peak"] = float(cl["x_over_d"].to_numpy(float)[i])
    return m


def rms_vs_tnf(cfd: pd.DataFrame, tnf: pd.DataFrame, stations) -> dict:
    """与 plot_cmp_detail.py 完全相同的 RMS 口径（插值到实验 r/d）。"""
    out = {}
    for xd in stations:
        ed = tnf[np.isclose(tnf["x_over_d"].astype(float), xd) &
                 (tnf["r_over_d"] >= -0.01)]
        cr = cfd[(cfd["profile"] == "radial") &
                 np.isclose(cfd["x_over_d"].astype(float), xd) &
                 (cfd["r_over_d"] >= -0.01)].sort_values("r_over_d")
        if not len(ed) or not len(cr):
            continue
        rr = ed["r_over_d"].to_numpy(float)
        tt = ed["T"].to_numpy(float)
        msk = (rr <= 4.5) & (rr >= cr["r_over_d"].min() - 1e-9) & \
              (rr <= cr["r_over_d"].max() + 1e-9)
        if msk.sum() < 3:
            continue
        ci = np.interp(rr[msk], cr["r_over_d"], cr["temperature"])
        out[xd] = float(np.sqrt(np.mean((ci - tt[msk]) ** 2)))
    return out


# ---------------------------------------------------------------- GCI
def apparent_order(phi1, phi2, phi3, r21, r32, tol=1e-10, itmax=200):
    e21, e32 = phi2 - phi1, phi3 - phi2
    if e21 == 0 or e32 == 0:
        return None, e21, e32
    if e32 / e21 <= 0:
        return None, e21, e32                      # 非单调 -> 不在渐近区
    p = 2.0
    for _ in range(itmax):
        rhs = (abs(math.log(abs(e32 / e21)))
               + abs(math.log((r21 ** p - 1.0) / (r32 ** p - 1.0))))
        p_new = rhs / math.log(r21)
        if abs(p_new - p) < tol:
            p = p_new
            break
        p = p_new
    return p, e21, e32


def gci_table(phis: dict, h: dict) -> pd.DataFrame:
    """phis: {label: {metric: value}}，label 顺序 = 细, 中, 粗。"""
    lv = list(phis.keys())
    r21 = h[lv[1]] / h[lv[0]]
    r32 = h[lv[2]] / h[lv[1]]
    rows = []
    common = [k for k in phis[lv[0]]
              if not k.startswith("SE_") and all(k in phis[x] for x in lv)
              and not k.startswith("x/d_")]
    for k in common:
        p1, p2, p3 = (phis[x][k] for x in lv)
        p, e21, e32 = apparent_order(p1, p2, p3, r21, r32)
        row = {"metric": k, "fine": p1, "medium": p2, "coarse": p3,
               "eps21": e21, "eps32": e32, "r21": r21, "r32": r32}
        if p is None or p <= 0:
            row.update({"p": float("nan"), "phi_ext": float("nan"),
                        "gci_fine_pct": float("nan"), "AR": float("nan"),
                        "AR_ideal": float("nan"), "note": "非单调/零差，不在渐近区"})
        else:
            phi_ext = (r21 ** p * p1 - p2) / (r21 ** p - 1.0)
            gci = FS * abs(e21 / p1) / (r21 ** p - 1.0) * 100.0
            row.update({"p": p, "phi_ext": phi_ext, "gci_fine_pct": gci,
                        "AR": e32 / e21, "AR_ideal": r21 ** p, "note": ""})
        rows.append(row)
    return pd.DataFrame(rows)


def cells_of(specs: dict, lv: str) -> int:
    s = specs[lv]
    rf = s.get("refine", 1.0)
    xs = build_axis(s["axial"], rf)
    ys = build_axis(s["radial"], rf)
    return (len(xs) - 1) * (len(ys) - 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", default="v4")
    ap.add_argument("--tag", default="v4")
    ap.add_argument("--coarse", default=None)
    ap.add_argument("--medium", default=None)
    ap.add_argument("--fine", default=None)
    ap.add_argument("--flame", default="D")
    ap.add_argument("--avg", action="store_true",
                    help="读周期平均场 cfd_..._avg.csv（稳态解呈极限环时必须用）")
    ap.add_argument("--pattern", default="",
                    help="自定义文件模板，用 {lv} 占位，如 "
                         "'results/cfd_np_eq_d_v5_{lv}.csv'")
    ap.add_argument("--stations", nargs="+", type=float,
                    default=[15, 30, 45, 60])
    a = ap.parse_args()

    suf = "_avg" if a.avg else ""
    if a.pattern:
        stem = a.pattern
    else:
        stem = (f"results/cfd_edm_{a.flame.lower()}_{a.specs}_{{lv}}"
                f"_2step_c_only_fo{suf}.csv")
    paths = {"fine": a.fine or stem.format(lv="fine"),
             "medium": a.medium or stem.format(lv="medium"),
             "coarse": a.coarse or stem.format(lv="coarse")}
    df = {}
    for lv, rel in paths.items():
        p = Path(rel) if Path(rel).is_absolute() else ROOT / rel
        if not p.exists():
            raise SystemExit(f"缺文件: {p}")
        df[lv] = pd.read_csv(p)
        print(f"读入 {lv:6} {p.name}  ({len(df[lv])} 行)")

    specs = {"v1": C.MESH_SPECS, "v2": C.MESH_SPECS_V2,
             "v3": C.MESH_SPECS_V3, "v4": C.MESH_SPECS_V4,
             "v5": C.MESH_SPECS_V5}[a.specs]
    ncell = {lv: cells_of(specs, lv) for lv in ("coarse", "medium", "fine")}
    h = {lv: math.sqrt(V_DOMAIN / ncell[lv]) for lv in ncell}
    print("\n单元数:", ncell)
    print("h_eff [mm]:", {k: round(v * 1e3, 4) for k, v in h.items()})
    print(f"r21 = {h['medium']/h['fine']:.4f}   r32 = {h['coarse']/h['medium']:.4f}")

    phis = {lv: metrics_of(df[lv], a.stations)
            for lv in ("fine", "medium", "coarse")}
    tab = gci_table(phis, h)
    out_csv = ROOT / "results" / f"gci_{a.tag}{'_avg' if a.avg else ''}.csv"
    tab.to_csv(out_csv, index=False)

    pd.set_option("display.width", 200)
    print("\n================ GCI ================")
    show = tab.copy()
    for c in ("fine", "medium", "coarse", "eps21", "eps32", "phi_ext"):
        show[c] = show[c].map(lambda v: f"{v:.5g}")
    for c in ("r21", "r32", "p", "AR", "AR_ideal"):
        show[c] = show[c].map(lambda v: f"{v:.4f}")
    show["gci_fine_pct"] = show["gci_fine_pct"].map(lambda v: f"{v:.3f}%")
    print(show.to_string(index=False))
    print(f"\n已写 {out_csv}")

    # 采样不确定度（8 个样本、约 2.8 个极限环周期）：
    # 与网格间差值同量级时必须先加采样，否则 GCI 无意义
    print("\n--- 采样不确定度（T_std = 单样本脉动 σ；SEM = σ/√N，N=8）---")
    for xd in a.stations:
        k = f"SE_T@x/d={xd:g},r/d=1.5"
        vals = {lv: phis[lv].get(k) for lv in ("coarse", "medium", "fine")}
        if all(v is not None for v in vals.values()):
            print(f"  x/d={xd:>3g}  r/d=1.5  T 单样本脉动 σ = "
                  + ", ".join(f"{lv}:{val:.0f} K" for lv, val in vals.items())
                  + "   （N=8 → SEM≈σ/√8≈"
                  + ", ".join(f"{val/math.sqrt(8):.0f}" for val in vals.values())
                  + " K）")

    # ---------------- 与实验对比的精度
    tnf_all = pd.read_csv(ROOT / "results" / "tnf_flamed.csv")
    tnf = tnf_all[(tnf_all["flame"] == a.flame.upper()) &
                  (tnf_all["kind"] == "Yave")].copy()
    tnf["r_over_d"] = tnf["r_over_d"].astype(float)
    tnf["x_over_d"] = tnf["x_over_d"].astype(float)
    print("\n=========== 温度 RMS vs TNF [K] ===========")
    hdr = f"{'x/d':>6} | " + " | ".join(f"{lv:>8}" for lv in
                                        ("coarse", "medium", "fine"))
    print(hdr)
    rms = {lv: rms_vs_tnf(df[lv], tnf, a.stations)
           for lv in ("coarse", "medium", "fine")}
    for xd in a.stations:
        row = f"{xd:>6g} | " + " | ".join(
            f"{rms[lv].get(xd, float('nan')):>8.0f}" for lv in
            ("coarse", "medium", "fine"))
        print(row)
    for lv in ("coarse", "medium", "fine"):
        v = [x for x in rms[lv].values() if x == x]
        print(f"  mean RMS {lv:6} = {np.mean(v):.1f} K")

    # ---------------- 图
    FIG.mkdir(parents=True, exist_ok=True)
    hs = [h["coarse"], h["medium"], h["fine"]]
    fig, ax = plt.subplots(1, 3, figsize=(13.5, 3.9))
    mk = ["o", "s", "^", "D"]
    for i, xd in enumerate(a.stations):
        k = f"T@x/d={xd:g},r/d=1.5"
        if k not in phis["fine"]:
            continue
        ys = [phis[lv][k] for lv in ("coarse", "medium", "fine")]
        ax[0].plot(hs, ys, mk[i % 4] + "-", ms=6, lw=1.4, label=f"x/d={xd:g}")
        if tab.loc[tab["metric"] == k, "phi_ext"].notna().any():
            ext = float(tab.loc[tab["metric"] == k, "phi_ext"].iloc[0])
            ax[0].axhline(ext, ls=":", color="gray", lw=0.9, alpha=0.6)
    ax[0].set_xlabel("h_eff [m]")
    ax[0].set_ylabel("T @ r/d=1.5 [K]")
    ax[0].set_title("(a) 网格收敛（固定 r/d=1.5；虚线 = Richardson 外推）")
    ax[0].invert_xaxis()
    ax[0].grid(alpha=0.3)
    ax[0].legend(fontsize=8)

    g = tab[tab["metric"].str.startswith("intT")]
    ax[1].bar(range(len(g)), g["gci_fine_pct"].to_numpy(float),
              color="#1f6fb4", alpha=0.85)
    ax[1].axhline(5.0, color="#c0392b", ls="--", lw=1,
                  label="5% 判据")
    ax[1].set_xticks(range(len(g)))
    ax[1].set_xticklabels([m.split("=")[-1] for m in g["metric"]],
                          fontsize=8)
    ax[1].set_xlabel("x/d")
    ax[1].set_ylabel("GCI$_{fine}$ [%]")
    ax[1].set_title("(b) 细网格 GCI（径向积分温度 T；<5% 视为网格无关）")
    ax[1].grid(alpha=0.3, axis="y")
    ax[1].legend(fontsize=8)

    x = np.arange(len(a.stations))
    w = 0.26
    for j, lv in enumerate(("coarse", "medium", "fine")):
        vals = [rms[lv].get(xd, np.nan) for xd in a.stations]
        ax[2].bar(x + (j - 1) * w, vals, w, label=lv)
    ax[2].set_xticks(x)
    ax[2].set_xticklabels([f"{xd:g}" for xd in a.stations])
    ax[2].set_xlabel("x/d")
    ax[2].set_ylabel("RMS(T) [K]")
    ax[2].set_title("(c) 与 TNF 实验的温度 RMS")
    ax[2].grid(alpha=0.3, axis="y")
    ax[2].legend(fontsize=8)
    fig.suptitle(f"flameD 网格收敛性 ({a.tag})", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    outp = FIG / f"gci_{a.tag}{'_avg' if a.avg else ''}.png"
    fig.savefig(outp, dpi=130)
    plt.close(fig)
    print(f"已写 {outp}")


if __name__ == "__main__":
    main()
