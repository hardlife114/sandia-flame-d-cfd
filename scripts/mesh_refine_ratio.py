"""核查网格级间加密比是否严格（GCI 的前提）。

对 v1/v2/v3 每个规格：
  - 分别在若干采样位置给出局部 1D 间距
  - 计算 medium/coarse、fine/medium 的局部加密比（理想 = 1/sqrt2 ≈ 0.7071）
  - 用 h_eff = sqrt(V/N) 给出全局有效加密比（理想 = 1/sqrt2）

用法: python mesh_refine_ratio.py [--specs v3]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import flamed_common as C          # noqa: E402
from gen_mesh import build_axis    # noqa: E402

MM = 1e3
V_DOMAIN = 0.1055334               # 解析 pi*R^2*L，三级实测一致

R_SAMPLES = [1, 3.6, 5, 9.45, 15, 20, 30, 40, 50, 70, 100, 150]     # mm
X_SAMPLES = [5, 15, 30, 50, 80, 120, 200, 300, 450, 600]           # mm


def local_gap(ax: list[float], p: float) -> float:
    """在位置 p（单位=同 ax）处返回所在单元的间距。"""
    for i in range(len(ax) - 1):
        if ax[i] <= p <= ax[i + 1]:
            return ax[i + 1] - ax[i]
    return float("nan")


def cell_count(levels: dict, refine_key: str) -> dict:
    out = {}
    for lv, spec in levels.items():
        xs = build_axis(spec["axial"], spec.get("refine", 1.0) if refine_key
                        else 1.0)
        ys = build_axis(spec["radial"], spec.get("refine", 1.0) if refine_key
                        else 1.0)
        out[lv] = (len(xs) - 1) * (len(ys) - 1)
    return out


def axes_of(specs: dict, lv: str, key: str):
    s = specs[lv]
    rf = s.get("refine", 1.0)
    return build_axis(s["axial"], rf), build_axis(s["radial"], rf)


def report(name: str, specs: dict, levels=("coarse", "medium", "fine")):
    print("=" * 100)
    print(f"### {name}")
    ax = {}
    for lv in levels:
        ax[lv] = axes_of(specs, lv, None)
    # 单元数
    cnt = {lv: (len(ax[lv][0]) - 1) * (len(ax[lv][1]) - 1) for lv in levels}
    print("单元数:", {lv: cnt[lv] for lv in levels})
    if len(levels) == 3:
        print("单元数比 coarse:medium:fine = 1 : {:.3f} : {:.3f}  (理想 1:2:4)".format(
            cnt[levels[1]] / cnt[levels[0]], cnt[levels[2]] / cnt[levels[0]]))
    # h_eff
    h = {lv: math.sqrt(V_DOMAIN / cnt[lv]) for lv in levels}
    print("h_eff [mm]:", {lv: round(h[lv] * MM, 4) for lv in levels})
    if len(levels) == 3:
        print("h 级间比 (r21=h_medium/h_fine, r32=h_coarse/h_medium) = "
              "r21={:.4f}  r32={:.4f}   (理想 1.4142)".format(
                  h[levels[1]] / h[levels[2]], h[levels[0]] / h[levels[1]]))

    print("\n-- 径向局部间距 dr [mm] 与加密比 (理想 0.7071) --")
    hdr = f"{'r[mm]':>7} | " + " | ".join(f"{lv:>9}" for lv in levels)
    if len(levels) == 3:
        hdr += " | med/crs  fine/med"
    print(hdr)
    for r in R_SAMPLES:
        row = f"{r:>7.2f} | "
        vals = [local_gap(ax[lv][1], r * 1e-3) * MM for lv in levels]
        row += " | ".join(f"{v:>9.4f}" for v in vals)
        if len(levels) == 3:
            row += " | {:.4f}   {:.4f}".format(vals[1] / vals[0], vals[2] / vals[1])
        print(row)

    print("\n-- 轴向局部间距 dx [mm] 与加密比 (理想 0.7071) --")
    hdr = f"{'x[mm]':>7} | " + " | ".join(f"{lv:>9}" for lv in levels)
    if len(levels) == 3:
        hdr += " | med/crs  fine/med"
    print(hdr)
    for x in X_SAMPLES:
        row = f"{x:>7.1f} | "
        vals = [local_gap(ax[lv][0], x * 1e-3) * MM for lv in levels]
        row += " | ".join(f"{v:>9.4f}" for v in vals)
        if len(levels) == 3:
            row += " | {:.4f}   {:.4f}".format(vals[1] / vals[0], vals[2] / vals[1])
        print(row)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", nargs="+", default=["v3", "v4"])
    a = ap.parse_args()
    if "v1" in a.specs:
        report("v1 (原规格, 分段均匀)", C.MESH_SPECS,
               ("coarse", "medium", "fine"))
    if "v2" in a.specs:
        report("v2 (几何渐变 + 级间 1:1/sqrt2:1/2)", C.MESH_SPECS_V2,
               ("coarse", "medium", "fine"))
    if "v3" in a.specs:
        report("v3 (火焰带局部加密)", C.MESH_SPECS_V3,
               ("coarse", "medium", "fine"))
    if "v4" in a.specs:
        report("v4 (火焰带局部加密 + 双端锁定，级间严格)", C.MESH_SPECS_V4,
               ("coarse", "medium", "fine"))
    if "v5" in a.specs:
        report("v5 (v4 整场再加密 1.3x)", C.MESH_SPECS_V5,
               ("coarse", "medium", "fine"))


if __name__ == "__main__":
    main()
