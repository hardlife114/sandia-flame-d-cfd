"""3D 结果导出：z=0 平面沿 y 的横截面剖面（与 2D CSV 列名兼容）。

用法: python scripts/export_box3d_profiles.py [--case run/box3d_edm.cas.h5]
产出: results/cfd_box3d_<tag>.csv
列：profile, x_over_d, r_over_d(=y/d), x_m, y_m, temperature, ch4, o2, co2, h2o, co
"""
from __future__ import annotations

import argparse
import csv as _csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["AWP_ROOT252"] = r"D:\Program Files\ANSYS\2025R2\v252"
os.environ.setdefault("FLUENT_AUTOMATIC_TRANSCRIPT", "0")
sys.path.insert(0, str(ROOT / "scripts"))
import flamed_common as C  # noqa: E402

RUN = ROOT / "run"
STATIONS = [0.75, 1, 2, 3, 15, 30, 45, 60, 75]
FIELDS = ["temperature", "ch4", "o2", "co2", "h2o", "co", "n2"]


def line_vals(s, nm, fields):
    import numpy as np
    out = {}
    for f in fields:
        try:
            out[f] = np.asarray(list(s.fields.field_data.get_scalar_field_data(
                field_name=f, surfaces=[nm], node_value=True).values())[0],
                dtype=float).ravel()
        except Exception:                                   # noqa: BLE001
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=str(RUN / "box3d_edm.cas.h5"))
    ap.add_argument("--tag", default="box3d_edm")
    a = ap.parse_args()

    import ansys.fluent.core as pyfluent
    s = pyfluent.launch_fluent(
        mode="solver", dimension=3, precision="double",
        processor_count=4, ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    s.settings.file.read_case_data(file_name=a.case)
    print(f"已读 {Path(a.case).name}")

    d = C.D_JET
    rows = []
    for xd in STATIONS:
        nm = f"b{xd}".replace(".", "p")
        x0 = xd * d
        try:
            s.tui.surface.line_surface(nm, x0, -6 * d, 0.0, x0, 6 * d, 0.0)
        except Exception:                                   # noqa: BLE001
            pass
        vals = line_vals(s, nm, FIELDS + ["y-coordinate", "x-coordinate"])
        ys = vals.get("y-coordinate")
        xs = vals.get("x-coordinate")
        if ys is None:
            print(f"  x/d={xd}: 线提取失败")
            continue
        n = len(ys)
        print(f"  x/d={xd:>5}: n={n} y/d∈[{ys.min()/d:.2f},{ys.max()/d:.2f}]")
        for i in range(n):
            rec = {"profile": "radial", "x_over_d": xd, "r_over_d": ys[i] / d,
                   "x_m": float(xs[i]) if xs is not None else x0,
                   "y_m": float(ys[i])}
            for f in FIELDS:
                if f in vals and i < len(vals[f]):
                    rec[f] = float(vals[f][i])
            rows.append(rec)

    # 中心线（y=0，沿 x）
    try:
        s.tui.surface.line_surface("clx", 0.0, 0.0, 0.0, C.L_DOMAIN, 0.0, 0.0)
        vals = line_vals(s, "clx", FIELDS + ["x-coordinate"])
        xs = vals.get("x-coordinate")
        if xs is not None:
            for i in range(len(xs)):
                rec = {"profile": "centerline", "x_over_d": xs[i] / d,
                       "r_over_d": 0.0, "x_m": float(xs[i]), "y_m": 0.0}
                for f in FIELDS:
                    if f in vals and i < len(vals[f]):
                        rec[f] = float(vals[f][i])
                rows.append(rec)
            print(f"  中心线: n={len(xs)}")
    except Exception as exc:                                # noqa: BLE001
        print(f"  中心线失败: {str(exc)[:150]}")

    dst = ROOT / "results" / f"cfd_{a.tag}.csv"
    cols = ["profile", "x_over_d", "r_over_d", "x_m", "y_m"] + FIELDS
    with dst.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for rec in rows:
            w.writerow(rec)
    print(f"已写 {dst}（{len(rows)} 行）")

    s.exit()


if __name__ == "__main__":
    main()
