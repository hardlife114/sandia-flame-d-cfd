"""量化 3D 解的 y 对称性破缺：沿 x 逐站给出"偶对称误差"与"奇对称误差"。

判据（严格 y 对称解应满足）：
  T(x,y) = T(x,-y)      → 反对称分量 T_odd(y) = [T(y)-T(-y)]/2 ≡ 0
  v_y(x,y) = -v_y(x,-y) → 对称分量   v_even(y) = [v_y(y)+v_y(-y)]/2 ≡ 0
  v_x(x,y) = v_x(x,-y)  → 反对称分量 ≡ 0

产出：run/asym_report.txt + results/figs/asym_vs_x.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import use_cjk  # noqa: E402
import flamed_common as C  # noqa: E402

use_cjk()
D = C.D_JET
MM = 1e3
OUT = ROOT / "run" / "asym_report.txt"
FIG = ROOT / "results" / "figs"


def bin_profile(y, v, yedges):
    """把 (y,v) 分箱到 yedges，返回每箱均值。"""
    idx = np.clip(np.digitize(y, yedges) - 1, 0, len(yedges) - 2)
    s = np.bincount(idx, weights=v, minlength=len(yedges) - 1)
    n = np.bincount(idx, minlength=len(yedges) - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, s / np.maximum(n, 1), np.nan)


def main():
    f = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "run" / "slices" / "sz0.npz"
    if not f.exists():
        print(f"缺 {f}")
        return 1
    d = np.load(f)
    x, y = d["x-coordinate"] * MM, d["y-coordinate"] * MM
    T = d["temperature"]
    U = d["x-velocity"]
    V = d["y-velocity"]

    lines = []

    def say(*a):
        s = " ".join(str(t) for t in a)
        print(s, flush=True)
        lines.append(s)

    say("=" * 78)
    say("3D 解 y 对称性破缺量化（截面 z=0）")
    say("=" * 78)
    say(f"节点 {len(x)}　x {x.min():.0f}–{x.max():.0f} mm　y {y.min():.0f}–{y.max():.0f} mm")

    # 统一 y 分箱（1 mm），镜像配对
    # ★ 分箱范围按数据自适应（432mm 域与 300mm 域通用），且必须关于 0 对称
    ymax = float(np.ceil(np.nanmax(np.abs(y))))
    yb = np.arange(-ymax, ymax + 1e-9, 1.0)
    yc = 0.5 * (yb[:-1] + yb[1:])
    ny = len(yc)
    # 镜像索引：yc[i] ↔ yc[-1-i]
    mir = np.arange(ny - 1, -1, -1)
    assert np.allclose(yc, -yc[mir], atol=1e-9)

    # ★ 切片数据其实是**结构化网格节点**（nx 列 × ny 行）。用 1 mm 分箱会把
    #   样本打散（多数箱为空），导致只有极少数站位能算 → 改为**取整列 x**
    #   + **镜像插值配对**：不依赖网格是否严格对称，任意分布都能算。
    ux = np.unique(np.round(x, 6))
    stations = [5, 10, 15, 20, 30, 45, 60, 75, 90]      # x/d
    rows = []
    for xd in stations:
        x0 = xd * D * MM
        xcol = ux[int(np.argmin(np.abs(ux - x0)))]
        sel = np.abs(x - xcol) <= 1e-6
        if sel.sum() < 20:
            continue
        ys_, Ts_ = y[sel], T[sel]
        Us_, Vs_ = U[sel], V[sel]
        o = np.argsort(ys_)
        ys_, Ts_, Us_, Vs_ = ys_[o], Ts_[o], Us_[o], Vs_[o]
        Tm = np.interp(-ys_, ys_, Ts_)       # 镜像位置的 T(-y)
        Um = np.interp(-ys_, ys_, Us_)
        Vm = np.interp(-ys_, ys_, Vs_)
        T_odd = 0.5 * (Ts_ - Tm)             # 对称解应 ≡ 0
        U_odd = 0.5 * (Us_ - Um)
        V_even = 0.5 * (Vs_ + Vm)            # 反对称解应 ≡ 0
        core = np.abs(ys_) <= 100.0          # 只统计火焰核心带
        m = core & np.isfinite(T_odd) & np.isfinite(V_even)
        rows.append(dict(
            xd=xd, xmm=float(xcol), n=int(sel.sum()),
            T_rms=float(np.sqrt(np.nanmean(T_odd[m] ** 2))),
            T_max=float(np.nanmax(np.abs(T_odd[m]))),
            V_rms=float(np.sqrt(np.nanmean(V_even[m] ** 2))),
            V_mean=float(np.nanmean(V_even[m])),
            U_rms=float(np.sqrt(np.nanmean(U_odd[m] ** 2))),
            Tmax=float(np.nanmax(Ts_[core])) if core.any() else float("nan"),
            Vmean_all=float(np.nanmean(V_even[np.isfinite(V_even)])),
        ))

    say("\n【一、沿程对称性破缺（|y| ≤ 100 mm 核心带）】")
    say(f"  {'x/d':>5}{'x[mm]':>9}{'点数':>6}{'T反对称RMS[K]':>15}"
        f"{'T最大偏差[K]':>14}{'该站Tmax[K]':>13}"
        f"{'v_y对称均值[m/s]':>18}{'v_x反对称RMS':>14}")
    for r in rows:
        say(f"  {r['xd']:>5}{r['xmm']:>9.1f}{r['n']:>6}{r['T_rms']:>15.1f}"
            f"{r['T_max']:>14.1f}{r['Tmax']:>13.0f}"
            f"{r['V_mean']:>18.2f}{r['U_rms']:>14.2f}")

    # 全高 transverse 质量平衡（连续性：闭通道内 ∫v_y dy 应为 0）
    say("\n【二、全截面横向速度平衡（闭通道连续性检验）】")
    say(f"  {'x/d':>5}{'∫v_y dy 上/下半不对称[m/s·mm]':>38}{'v_y(y>0)均值':>16}{'v_y(y<0)均值':>16}")
    for xd in (15, 30, 45, 60, 75):
        x0 = xd * D * MM
        sel = np.abs(x - x0) <= 2.0
        if sel.sum() < 20:
            continue
        Vp = bin_profile(y[sel], V[sel], yb)
        up = np.nanmean(Vp[yc > 5])
        dn = np.nanmean(Vp[yc < -5])
        say(f"  {xd:>5}{up * ymax - (-dn) * ymax:>38.1f}{up:>16.2f}{dn:>16.2f}")

    # 远场（应 291 K 空气）
    say("\n【三、远场温度（|y| > 50 mm，应为 ~291 K）】")
    say(f"  {'x 区间[mm]':>16}{'上侧y>50 均值':>16}{'下侧y<-50 均值':>18}{'下侧>1000K占比':>18}")
    for a, b in ((100, 200), (200, 300), (300, 500), (500, 720)):
        s1 = (x >= a) & (x < b) & (y > 50)
        s2 = (x >= a) & (x < b) & (y < -50)
        if s1.sum() < 10:
            continue
        say(f"  {f'{a}-{b}':>16}{T[s1].mean():>16.1f}{T[s2].mean():>18.1f}"
            f"{(T[s2] > 1000).mean() * 100:>17.1f}%")

    OUT.write_text("\n".join(lines), encoding="utf-8")

    # ---- 图 ----
    fig, ax = plt.subplots(1, 3, figsize=(13.5, 3.9))
    xs = [r["xd"] for r in rows]
    ax[0].plot(xs, [r["T_rms"] for r in rows], "o-", color="#c0504d")
    ax[0].set_xlabel("x/d")
    ax[0].set_ylabel("T 反对称分量 RMS [K]")
    ax[0].set_title("(a) 温度对称性破缺沿程发展", fontsize=10)
    ax[0].grid(alpha=0.3, ls=":")

    ax[1].plot(xs, [r["V_mean"] for r in rows], "s-", color="#1f4e79")
    ax[1].axhline(0, color="k", lw=0.8, ls="--")
    ax[1].set_xlabel("x/d")
    ax[1].set_ylabel("v$_y$ 对称分量均值 [m/s]")
    ax[1].set_title("(b) 横向速度奇偶性破缺（对称解应=0）", fontsize=10)
    ax[1].grid(alpha=0.3, ls=":")

    # 剖面示例：x/d=45 与 75 的 T(y) 与 T(-y)
    for xd, col in ((15, "#2e75b6"), (45, "#c0504d"), (75, "#548235")):
        x0 = xd * D * MM
        sel = np.abs(x - x0) <= 2.0
        Tp = bin_profile(y[sel], T[sel], yb)
        ax[2].plot(yc, Tp, color=col, lw=1.2, label=f"x/d={xd}  T(y)")
        ax[2].plot(-yc, Tp, color=col, lw=0.9, ls="--", alpha=0.7,
                   label=f"x/d={xd}  T(-y) 镜像")
    ax[2].set_xlabel("y [mm]")
    ax[2].set_ylabel("T [K]")
    ax[2].set_title("(c) 温度剖面 vs 其镜像", fontsize=10)
    ax[2].legend(fontsize=7.5)
    ax[2].grid(alpha=0.3, ls=":")
    ax[2].set_xlim(-80, 80)
    fig.tight_layout()
    FIG.mkdir(parents=True, exist_ok=True)
    p = FIG / "asym_vs_x.png"
    fig.savefig(p, dpi=145)
    print(f"已写 {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
