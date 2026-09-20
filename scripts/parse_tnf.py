"""解析 TNF pmCDEF 实验数据（Sandia/TUD piloted CH4/air, Flame D）。

数据来源：refs/tnf/pmCDEF.zip -> pmCDEFarchives/pmD.stat/
  文件命名  DXX.Yave / DXX.Yfav / DXX.Ycnd
    XX = 测点编号: 01 02 03 075 15 30 45 60 75 表示 x/d
         CL = 中心线轴向剖面
  Yave = Reynolds 平均, Yfav = Favre 平均, Ycnd = 条件平均(按 F 分箱)

列（表头行给出，注意 Yfav 无 TNDR 列）：
  r/d  F  Frms  T(K)  Trms  YO2 YO2rms  YN2 YN2rms  YH2 YH2rms  YH2O YH2Orms
  YCH4 YCH4rms  YCO YCOrms  YCO2 YCO2rms  YOH YOHrms  YNO YNOrms  YCOLIF YCOrms [TNDR]

用法:
  python parse_tnf.py --list
  python parse_tnf.py --dump D15 --kind Yave
  python parse_tnf.py --export results/tnf_flamed.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TNFR = ROOT / "refs" / "tnf" / "pmCDEF" / "pmCDEFarchives"


def profile_files():
    """返回 {flame: {point: {kind: path}}}"""
    out = {}
    for flame_dir in sorted(TNFR.glob("pm*.stat")):
        flame = flame_dir.name.split(".")[0].replace("pm", "")
        pts = {}
        for f in sorted(flame_dir.iterdir()):
            if "." not in f.name:
                continue
            stem, kind = f.name.rsplit(".", 1)
            # stem 形如 D15 / DCL / DCLcnst
            if not stem.startswith(flame):
                continue
            point = stem[len(flame):]
            pts.setdefault(point, {})[kind] = f
        out[flame] = pts
    return out


def read_profile(path: Path):
    """读一个剖面文件，返回 (columns, rows)。表头在含 'r/d' 的那一行。"""
    lines = path.read_text(encoding="latin-1").splitlines()
    hdr_i = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("r/d"):
            hdr_i = i
            break
    if hdr_i is None:
        raise ValueError(f"未找到表头: {path}")
    cols = lines[hdr_i].split()
    # 处理重复列名（如两个 YCOrms）
    seen = {}
    uniq = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            uniq.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            uniq.append(c)
    rows = []
    for ln in lines[hdr_i + 1:]:
        s = ln.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) != len(cols):
            continue
        try:
            vals = [float(x) for x in parts]
        except ValueError:
            continue
        rows.append(vals)
    return uniq, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dump")
    ap.add_argument("--kind", default="Yave")
    ap.add_argument("--flame", default="D")
    ap.add_argument("--export")
    args = ap.parse_args()

    files = profile_files()
    if args.list:
        for flame, pts in files.items():
            print(f"\nflame {flame}:")
            for p, kinds in sorted(pts.items(), key=lambda kv: kv[0]):
                print(f"  {p:8s} {sorted(kinds)}")
        return

    if args.dump:
        path = files[args.flame][args.dump][args.kind]
        cols, rows = read_profile(path)
        print(f"# {path.relative_to(ROOT)}")
        print(f"# {len(cols)} 列, {len(rows)} 行")
        print("  " + "  ".join(f"{c:>10s}" for c in cols))
        for r in rows[:20]:
            print("  " + "  ".join(f"{v:10.5g}" for v in r))
        if len(rows) > 20:
            print(f"  ... 共 {len(rows)} 行")
        return

    if args.export:
        dst = Path(args.export)
        if not dst.is_absolute():
            dst = ROOT / dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["flame", "point", "x_over_d", "kind", "r_over_d",
                        "F", "F_rms", "T", "T_rms", "Y_O2", "Y_N2", "Y_H2O",
                        "Y_CH4", "Y_CO", "Y_CO2", "Y_OH", "Y_H2", "Y_NO",
                        "Y_CO_LIF"])
            for flame, pts in files.items():
                for p, kinds in sorted(pts.items()):
                    if p == "CLcnst":
                        continue
                    if p == "CL":
                        xd = None
                    elif len(p) == 3:      # 075 -> 0.75, 15 -> 1.5, 30 -> 3.0
                        xd = float(p) / 100.0
                    elif len(p) == 2:      # 01 -> 1, 02 -> 2
                        xd = float(p)
                    else:
                        continue
                    for kind in ("Yave", "Yfav"):
                        path = kinds.get(kind)
                        if path is None:
                            continue
                        try:
                            cols, rows = read_profile(path)
                        except Exception as exc:            # noqa: BLE001
                            print("skip", path.name, exc)
                            continue
                        idx = {c: i for i, c in enumerate(cols)}

                        def g(row, *names):
                            for n in names:
                                if n in idx:
                                    return row[idx[n]]
                            return ""

                        for r in rows:
                            w.writerow([
                                flame, p, "" if xd is None else xd, kind,
                                g(r, "r/d"), g(r, "F"), g(r, "Frms"),
                                g(r, "T(K)"), g(r, "Trms"),
                                g(r, "YO2"), g(r, "YN2"), g(r, "YH2O"),
                                g(r, "YCH4"), g(r, "YCO"), g(r, "YCO2"),
                                g(r, "YOH"), g(r, "YH2"), g(r, "YNO"),
                                g(r, "YCOLIF"),
                            ])
        print("written", dst)
        return

    ap.print_help()


if __name__ == "__main__":
    main()
