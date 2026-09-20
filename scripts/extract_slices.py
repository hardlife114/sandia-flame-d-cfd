"""从 3D 解提取切片场数据（iso-surface 方式），导出为盘存文件供渲染。

切片：
  sz0   z=0 平面（x–y 剖面，轴向发展）★主剖面
  sy0   y=0 平面（x–z 剖面，验证 z 向均匀性）
  sx15/sx30/sx60  横截面（y–z，x/d=15/30/60）

场：temperature, ch4, o2, co2, h2o
产出：run/slices/<name>.npz（含 x/y/z 坐标与各场）
"""
from __future__ import annotations

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
OUT = RUN / "slices"
LOG = RUN / "slices.log"
CASE = RUN / "box3d_edm.cas.h5"
FIELDS = ["temperature", "ch4", "o2", "co2", "h2o",
          "x-velocity", "y-velocity", "z-velocity", "velocity-magnitude"]
COORDS = ["x-coordinate", "y-coordinate", "z-coordinate"]

if LOG.exists():
    LOG.unlink()
OUT.mkdir(exist_ok=True)


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


SLICES = [
    ("sz0", "z-coordinate", 0.0),
    ("sy0", "y-coordinate", 0.0),
    ("sx15", "x-coordinate", 15 * C.D_JET),
    ("sx30", "x-coordinate", 30 * C.D_JET),
    ("sx60", "x-coordinate", 60 * C.D_JET),
    ("sx100", "x-coordinate", 100 * C.D_JET),
]


def main():
    import argparse

    import numpy as np
    import ansys.fluent.core as pyfluent

    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["all"], default="all")
    ap.add_argument("--tag", default=None,
                    help="case 名（不含 .cas.h5），默认 box3d_edm")
    ap.add_argument("--case", default=None, help="case 完整路径（优先于 --tag）")
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--out", default=None, help="输出目录（默认 run/slices）")
    a = ap.parse_args()

    case = Path(a.case) if a.case else RUN / f"{a.tag or 'box3d_edm'}.cas.h5"
    if a.out:
        global OUT
        OUT = Path(a.out)
        OUT.mkdir(parents=True, exist_ok=True)

    say("=" * 70)
    say(time.strftime("%F %T"), "3D 解切片提取（settings API 建面）")
    say("=" * 70)

    s = pyfluent.launch_fluent(
        mode="solver", dimension=3, precision="double",
        processor_count=a.procs, ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    s.settings.file.read_case_data(file_name=str(case))
    say(f"  已读 {case.name}")

    # ★ 用 settings API 建 iso 面（TUI 的 iso-surface 会静默失败）
    surfs = s.settings.results.surfaces.iso_surface
    for nm, field, val in SLICES:
        try:
            surfs.create(name=nm)
            surfs[nm] = {"field": field, "iso_values": [val]}
            say(f"  建面 {nm}（{field}={val:.4f}）OK")
        except Exception as exc:                            # noqa: BLE001
            say(f"  建面 {nm} FAIL: {str(exc)[:160]}")

    try:
        info = s.fields.field_info.get_surfaces_info()
        say(f"  已注册面: {sorted(info.keys())}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  面注册表读取 FAIL: {str(exc)[:120]}")

    fd = s.fields.field_data
    got = 0
    for nm, field, val in SLICES:
        dat = {}
        try:
            for f in FIELDS + COORDS:
                v = fd.get_scalar_field_data(field_name=f, surfaces=[nm],
                                             node_value=True)
                dat[f] = np.asarray(list(v.values())[0], dtype=float).ravel()
            n = len(dat["temperature"])
            np.savez_compressed(OUT / f"{nm}.npz", **dat)
            say(f"  {nm}: {n} 点（T {dat['temperature'].min():.0f}-"
                f"{dat['temperature'].max():.0f} K, |U|max="
                f"{dat['velocity-magnitude'].max():.1f} m/s）-> {nm}.npz")
            got += 1
        except Exception as exc:                            # noqa: BLE001
            say(f"  {nm} 提取 FAIL: {str(exc)[:200]}")

    say(f"\n共导出 {got}/{len(SLICES)} 个切片")
    s.exit()
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
