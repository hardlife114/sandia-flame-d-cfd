"""切片云图渲染（读 run/slices/*.npz → results/figs/slices_*.png）。

产出：
  slices_main.png     z=0 平面温度云图（裁剪火焰区 + 全景）
  slices_species.png  z=0 平面 ch4/o2/co2 云图
  slices_cross.png    x/d=15/30/60 横截面温度云图
  slices_y0.png       y=0 平面（x–z）温度云图（验证 z 向均匀性）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from plot_style import use_cjk  # noqa: E402
import flamed_common as C  # noqa: E402

use_cjk()
RUN = ROOT / "run"
# ★ 支持从任意切片目录渲染：SLICE_DIR=run/slices_round300  python scripts/render_slices.py
SL = Path(os.environ.get("SLICE_DIR", str(RUN / "slices")))
if not SL.is_absolute():
    SL = ROOT / SL
TAG_OUT = os.environ.get("SLICE_TAG", "")
FIG = ROOT / "results" / "figs"
D = C.D_JET


def load(nm):
    p = SL / f"{nm}.npz"
    if not p.exists():
        return None
    z = np.load(p)
    return {k: z[k] for k in z.files}


def panel(ax, X, Y, T, xl, yl, title, vmin, vmax, cmap="jet"):
    """散点三角化云图（去重后 tri 化，避免重复点导致 Qhull 报错）。"""
    pts = np.column_stack([X, Y])
    _, idx = np.unique(np.round(pts, 6), axis=0, return_index=True)
    X, Y, T = X[idx], Y[idx], T[idx]
    tri = mtri.Triangulation(X, Y)
    m = ax.tricontourf(tri, T, levels=40, cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xlabel(xl)
    ax.set_ylabel(yl)
    ax.set_title(title, fontsize=10.5)
    ax.set_aspect("equal", adjustable="box")
    return m


def main():
    sz0 = load("sz0")
    sy0 = load("sy0")
    sx15 = load("sx15")
    sx30 = load("sx30")
    sx60 = load("sx60")
    if sz0 is None:
        print("缺 sz0.npz —— 先运行 extract_slices.py")
        return 1
    FIG.mkdir(parents=True, exist_ok=True)
    mm = 1e3

    # ---------- 主图：z=0 平面温度 ----------
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 8.6))
    X, Y, T = sz0["x-coordinate"] * mm, sz0["y-coordinate"] * mm, sz0["temperature"]
    # ★ 伪影/对称性判据改为**按实际数据判断**（V1 条带进口有伪影，V3/V4 圆进口已消失，
    #   写死的标注会误导）。口径与 analyze_asym 第三节一致。
    far = np.abs(Y) > 50.0
    hot_frac = float((T[far] > 1000.0).mean() * 100) if far.any() else 0.0
    up = T[(Y > 50.0)].mean() if (Y > 50.0).any() else float("nan")
    dn = T[(Y < -50.0)].mean() if (Y < -50.0).any() else float("nan")
    clean = hot_frac < 0.1
    note = ("★ |y|>50mm 无高温伪影，上下侧对称（%.1f / %.1f K），T>1000K 占比 %.1f%%"
            % (up, dn, hot_frac)) if clean else \
           ("⚠ |y|>50mm 存在伪影：T>1000K 占比 %.1f%%（应为 <0.1%%），"
            "上下侧 %.1f / %.1f K" % (hot_frac, up, dn))
    ax = axes[1]
    selp = np.abs(Y) <= 120
    m = panel(ax, X[selp], Y[selp], T[selp], "x [mm]", "y [mm]",
              "z = 0 平面 全景（|y| ≤ 120 mm）——" + note, 291, 2250)
    plt.colorbar(m, ax=ax, label="T [K]", pad=0.01)
    ax.axhline(50, color="w", ls=":", lw=1.0)
    ax.axhline(-50, color="w", ls=":", lw=1.0)
    if not clean:
        ax.text(20, 95, "伪影区", color="w", fontsize=9)
    sel = (np.abs(Y) <= 40.0)
    ax = axes[0]
    m = panel(ax, X[sel], Y[sel], T[sel], "x [mm]", "y [mm]",
              "★ 火焰区（|y| ≤ 40 mm，可信区）—— 轴向发展与双火焰片结构",
              291, 2250)
    plt.colorbar(m, ax=ax, label="T [K]", pad=0.01)
    for xd in (15, 30, 60):
        axes[0].axvline(xd * C.D_JET * mm, color="w", ls="--", lw=0.8)
    fig.tight_layout()
    p = FIG / f"slices_main{TAG_OUT}.png"
    fig.savefig(p, dpi=145)
    print(f"已写 {p}")

    # ---------- 组分云图（z=0 平面，火焰区）----------
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
    for ax, (f, tt, cm) in zip(axes, (("ch4", "CH₄ 质量分数", "viridis"),
                                      ("o2", "O₂ 质量分数", "plasma"),
                                      ("co2", "CO₂ 质量分数", "inferno"))):
        Z = sz0[f]
        vmax = max(float(np.percentile(Z[sel], 99.5)), 1e-6)
        m = panel(ax, X[sel], Y[sel], Z[sel], "x [mm]", "y [mm]", tt,
                  0.0, vmax, cmap=cm)
        plt.colorbar(m, ax=ax, pad=0.01)
    fig.suptitle("z = 0 平面 组分场（|y| ≤ 40 mm）", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    p = FIG / f"slices_species{TAG_OUT}.png"
    fig.savefig(p, dpi=145)
    print(f"已写 {p}")

    # ---------- 横截面 ----------
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))
    for ax, (s, xd) in zip(axes, ((sx15, 15), (sx30, 30), (sx60, 60))):
        if s is None:
            continue
        Yc, Zc, Tc = s["y-coordinate"] * mm, s["z-coordinate"] * mm, s["temperature"]
        selc = (np.abs(Yc) <= 60) & (np.abs(Zc) <= 60)
        m = panel(ax, Yc[selc], Zc[selc], Tc[selc], "y [mm]", "z [mm]",
                  f"x/d = {xd} 横截面（T_max={Tc.max():.0f} K）", 291, 2250)
        plt.colorbar(m, ax=ax, label="T [K]", pad=0.01)
    fig.suptitle("横截面（y–z）温度云图 —— 火焰横向结构", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    p = FIG / f"slices_cross{TAG_OUT}.png"
    fig.savefig(p, dpi=145)
    print(f"已写 {p}")

    # ---------- y=0 平面（x–z）----------
    if sy0 is not None:
        fig, ax = plt.subplots(figsize=(11.5, 4.2))
        Xz, Zz, Tz = sy0["x-coordinate"] * mm, sy0["z-coordinate"] * mm, sy0["temperature"]
        selz = np.abs(Zz) <= 60
        m = panel(ax, Xz[selz], Zz[selz], Tz[selz], "x [mm]", "z [mm]",
                  "y = 0 平面（x–z）温度云图 —— 验证沿 z 的均匀性（|z| ≤ 60 mm）",
                  291, 2250)
        plt.colorbar(m, ax=ax, label="T [K]", pad=0.01)
        fig.tight_layout()
        p = FIG / f"slices_y0{TAG_OUT}.png"
        fig.savefig(p, dpi=145)
        print(f"已写 {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
