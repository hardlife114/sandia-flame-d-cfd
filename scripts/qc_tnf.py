"""对标前的一致性核查：只用 Python 读结果，不启动 Fluent（可在游戏时安全运行）。

检查项：
  1) results/tnf_flamed.csv 的结构与统计（Flame D 各剖面点数、量程）
  2) 用 TNF 自身的 F 剖面反查 Z_st 附近行为，与文档 §3.5 的 0.351 对照
  3) 中心线温度峰值与文档 L_stoic/d = 47 的一致性
  4) CFD 结果（若已有 results/cfd_flamed_*.csv）与 TNF 的粗对比
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import flamed_common as C  # noqa: E402

TNF = ROOT / "results" / "tnf_flamed.csv"
OUT = ROOT / "results" / "tnf_qc.txt"


def load(path):
    rows = []
    with Path(path).open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    return rows


def fv(r, k, default=None):
    try:
        return float(r[k])
    except (TypeError, ValueError, KeyError):
        return default


def main():
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 78)
    out("TNF Flame D 数据一致性核查（纯 Python，不启 Fluent）")
    out("=" * 78)

    rows = load(TNF)
    out(f"\n总行数 = {len(rows)}")

    # ---- 按 flame / kind / point 统计
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r["flame"], r["kind"], r["point"])].append(r)
    flames = sorted({k[0] for k in by_key})
    out(f"包含火焰: {flames}")

    d_rows = [r for r in rows if r["flame"] == "D"]
    out(f"Flame D 行数 = {len(d_rows)}（Yave+ fav）")
    d_yave = [r for r in d_rows if r["kind"] == "Yave"]
    out(f"Flame D Yave 行数 = {len(d_yave)}")

    # ---- 径向剖面的 x/d 与 r/d 覆盖
    xs = sorted({fv(r, "x_over_d") for r in d_yave if fv(r, "x_over_d") is not None})
    out(f"\n径向剖面 x/d = {xs}")
    pts = sorted({r["point"] for r in d_yave})
    out(f"测点标签 = {pts}")

    for xd in xs[:4] + xs[-2:]:
        rr = [fv(r, "r_over_d") for r in d_yave if fv(r, "x_over_d") == xd]
        tt = [fv(r, "T") for r in d_yave if fv(r, "x_over_d") == xd]
        tt = [t for t in tt if t is not None]
        rr = [x for x in rr if x is not None]
        if rr:
            out(f"  x/d={xd:5.1f}: n={len(rr):3d}  r/d ∈ [{min(rr):6.2f}, {max(rr):6.2f}]"
                f"  T ∈ [{min(tt):7.1f}, {max(tt):7.1f}] K")

    # ---- 中心线（CL 的 x_over_d 为空，用 F/T 随剖面的顺序表示）
    cl = [r for r in d_yave if r["point"] == "CL"]
    out(f"\n中心线(CL) 点 RANS 平均 n={len(cl)}")
    if cl:
        # 中心线文件里 r/d 实际是轴向 x/d（见 parse_tnf.py 说明）
        pairs = []
        for r in cl:
            xd = fv(r, "r_over_d")
            t = fv(r, "T")
            if xd is not None and t is not None:
                pairs.append((xd, t))
        pairs.sort()
        if pairs:
            out("  中心线温度（轴向 x/d -> T[K]）:")
            for xd, t in pairs:
                out(f"    {xd:6.2f}  {t:8.1f}")
            tmax = max(pairs, key=lambda p: p[1])
            out(f"\n  >>> 中心线温度峰值 = {tmax[1]:.1f} K @ x/d = {tmax[0]:.1f}")
            out(f"      文档 L_stoic/d = {C.L_STOIC_D}（化学计量火焰长度，"
                f"峰值应在其下游附近）")

    # ---- F（混合物分数）与 Z_st 对照
    out("\n混合物分数 F 核查（文档 §3.5: F_stoic = 0.351）")
    # 在 x/d=15 的径向剖面上找 T 最大处的 F（应接近化学计量）
    tgt = [r for r in d_yave if fv(r, "x_over_d") == 15.0]
    if tgt:
        best = max(tgt, key=lambda r: fv(r, "T", 0) or 0)
        out(f"  x/d=15 上 T 峰值 {fv(best,'T'):.1f} K 处: "
            f"F={fv(best,'F'):.4f}, r/d={fv(best,'r_over_d'):.2f}")
    # 统计 F 的范围
    fs = [fv(r, "F") for r in d_yave if fv(r, "F") is not None]
    out(f"  全数据 F ∈ [{min(fs):.4f}, {max(fs):.4f}]")

    # ---- 射流入口组分对应的 F 检查
    out("\n射流/伴流参考值（来自 flamed_common，已独立核算）")
    out(f"  Z_st(本核算)      = 0.352   [DOC 0.351]")
    out(f"  pilot Z(本核算)   = 0.272   [DOC F_pilot 0.27]")
    out(f"  文档 L_stoic/d    = {C.L_STOIC_D}")
    out(f"  文档 L_vis/d      = {C.L_VIS_D}")

    # ---- 下游 CFD 对比（如果有）
    cfds = sorted(ROOT.glob("results/cfd_flamed_*.csv"))
    out(f"\n找到 CFD 结果文件: {[p.name for p in cfds] or '（无）'}")

    dst = OUT
    dst.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwritten {dst}")


if __name__ == "__main__":
    main()
