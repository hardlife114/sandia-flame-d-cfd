"""生成 CFD vs TNF 实验对比图（纯 Python，秒级）。

输出 results/figs/cmp_<tag>.png：
  左列：径向温度剖面（CFD 实线 vs 实验散点），x/d = 0.75, 3, 15, 30, 45, 60
  右侧：中心线温度（CFD vs 实验）
  标题标注 RMS 与偏差，避免"看起来差不多"的误读。

用法:
  python plot_compare.py --cfd results/cfd_fast_coarse.csv --tag fast_coarse
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import flamed_common as C  # noqa: E402

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

TNF = ROOT / "results" / "tnf_flamed.csv"
FIGD = ROOT / "results" / "figs"
X_SHOW = [0.75, 3, 15, 30, 45, 60]


def load_tnf():
    rows = []
    with TNF.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["flame"] == "D" and r["kind"] == "Yave":
                rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfd", required=True)
    ap.add_argument("--tag", default="cfd")
    ap.add_argument("--flame", default="D")
    args = ap.parse_args()

    cfd_path = Path(args.cfd)
    if not cfd_path.is_absolute():
        cfd_path = ROOT / cfd_path
    if not cfd_path.exists():
        raise SystemExit(f"找不到 CFD 文件: {cfd_path}")

    tnf = load_tnf()
    cfd = list(csv.DictReader(cfd_path.open(encoding="utf-8")))
    say = print
    say(f"CFD 行数 = {len(cfd)}   TNF 行数 = {len(tnf)}")

    # ---- 组织 CFD
    rad = defaultdict(lambda: defaultdict(list))
    cl = defaultdict(list)
    for r in cfd:
        try:
            t = float(r["temperature"])
        except (TypeError, ValueError):
            continue
        if r.get("profile") == "centerline":
            cl[round(float(r["x_over_d"]), 2)].append(t)
        else:
            rad[round(float(r["x_over_d"]), 2)][float(r["r_over_d"])].append(t)

    prof = {k: (np.array(sorted(v)), np.array([np.mean(v[x]) for x in sorted(v)]))
            for k, v in rad.items()}

    # ---- 组织实验
    e_rad = defaultdict(list)
    e_cl = []
    for r in tnf:
        try:
            if r["point"] == "CL":
                e_cl.append((float(r["r_over_d"]), float(r["T"])))
            else:
                e_rad[round(float(r["x_over_d"]), 2)].append(
                    (float(r["r_over_d"]), float(r["T"])))
        except (TypeError, ValueError):
            continue

    nrow, ncol = 2, 3
    fig, axes = plt.subplots(nrow, ncol + 1, figsize=(17, 8.5),
                             gridspec_kw={"width_ratios": [1, 1, 1, 1.15]})
    rms_list = []
    for idx, xd in enumerate(X_SHOW):
        ax = axes[idx // ncol][idx % ncol]
        key = round(xd, 2)
        if key in e_rad:
            er = np.array([p[0] for p in e_rad[key]])
            et = np.array([p[1] for p in e_rad[key]])
            ax.plot(er, et, "o", color="#c0392b", ms=5, label="TNF Exp.", zorder=3)
        if key in prof:
            xs, ts = prof[key]
            ax.plot(xs, ts, "-", color="#1f6fb4", lw=2, label="CFD (EDM)")
            if key in e_rad:
                tc = np.interp(er, xs, ts)
                rms = float(np.sqrt(np.mean((tc - et) ** 2)))
                rms_list.append((xd, rms))
                ax.set_title(f"x/d = {xd}   RMS = {rms:.0f} K", fontsize=11)
        else:
            ax.set_title(f"x/d = {xd}   (CFD 缺)", fontsize=11)
        ax.set_xlabel("r/d")
        ax.set_ylabel("T [K]")
        ax.set_xlim(0, min(4.5, max(1, ax.get_xlim()[1])))
        ax.grid(alpha=.3)
        ax.legend(fontsize=8, loc="upper right")

    # ---- 中心线
    ax = axes[0][3]
    if e_cl:
        e_cl_s = sorted(e_cl)
        ax.plot([p[0] for p in e_cl_s], [p[1] for p in e_cl_s], "o-",
                color="#c0392b", ms=5, lw=1.6, label="TNF Exp.")
    if cl:
        cx = np.array(sorted(cl))
        ct = np.array([float(np.mean(cl[k])) for k in sorted(cl)])
        ax.plot(cx, ct, "-", color="#1f6fb4", lw=2, label="CFD (EDM)")
        ax.axvline(C.L_STOIC_D, ls="--", color="gray", lw=1)
    ax.set_xlabel("x/d")
    ax.set_ylabel("T [K]  (centerline)")
    ax.set_title("Centerline", fontsize=11)
    ax.grid(alpha=.3)
    ax.legend(fontsize=8)

    # ---- 汇总文本区
    ax = axes[1][3]
    ax.axis("off")
    txt = ["Comparison summary", ""]
    txt.append(f"CFD: {cfd_path.name}")
    txt.append("Model: global-chem + EDM")
    txt.append(f"CFD file: {cfd_path.name}")
    txt.append("")
    if rms_list:
        txt.append(f"{'x/d':>6} {'RMS(K)':>9}")
        for xd, rms in rms_list:
            txt.append(f"{xd:>6} {rms:>9.0f}")
        txt.append("")
        txt.append(f"mean RMS = {np.mean([r for _, r in rms_list]):.0f} K")
    txt.append("")
    txt.append("NOTE: flame established (EDM).")
    txt.append("Steady EDM has limit-cycle ext/reig.")
    txt.append("Near-field OK; mid-field hot.")
    ax.text(0.0, 1.0, "\n".join(txt), va="top", ha="left",
            family="monospace", fontsize=9.5)

    fig.suptitle(f"Sandia flameD: CFD vs TNF experiment  [{args.tag}]", y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    FIGD.mkdir(parents=True, exist_ok=True)
    out = FIGD / f"cmp_{args.tag}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print("written", out)
    if rms_list:
        print("RMS by x/d:", [(x, round(r)) for x, r in rms_list])


if __name__ == "__main__":
    main()
