"""3D 网格核验：读入 + mesh check + zone 统计（无迭代，不属大规模计算）。

用法: python scripts/verify_mesh3d.py <mesh 路径> [--cores 4]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["AWP_ROOT252"] = r"D:\Program Files\ANSYS\2025R2\v252"
os.environ.setdefault("FLUENT_AUTOMATIC_TRANSCRIPT", "0")

RUN = ROOT / "run"
LOG = RUN / "verify_mesh3d.log"
TRN = RUN / "trn_verify_mesh3d.txt"

if LOG.exists():
    LOG.unlink()
if TRN.exists():
    TRN.unlink()


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mesh")
    ap.add_argument("--cores", type=int, default=4)
    a = ap.parse_args()
    mesh = Path(a.mesh)
    if not mesh.is_absolute():
        mesh = ROOT / mesh

    import ansys.fluent.core as pyfluent

    say("=" * 74)
    say(time.strftime("%F %T"), f"3D 网格核验：{mesh.name}（{a.cores} 核）")
    say("=" * 74)
    say(f"  文件 {mesh}（{mesh.stat().st_size/1e6:.1f} MB）")

    s = pyfluent.launch_fluent(
        mode="solver", dimension=3, precision="double",
        processor_count=a.cores, ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    s.transcript.start(file_name=str(TRN), write_to_stdout=False)
    time.sleep(1.0)
    say(f"已启动 3D 求解器")

    t0 = time.time()
    try:
        s.settings.file.read_mesh(file_name=str(mesh))
        say(f"  read_mesh OK（{time.time()-t0:.0f}s）")
    except Exception as exc:                                # noqa: BLE001
        say(f"  read_mesh FAIL: {str(exc)[:300]}")
        s.exit()
        return

    try:
        s.execute_tui("/mesh/check")
        time.sleep(3.0)
        say("  /mesh/check 已执行")
    except Exception as exc:                                # noqa: BLE001
        say(f"  mesh check FAIL: {str(exc)[:200]}")

    try:
        zs = s.settings.setup.boundary_conditions.get_state()
        say(f"  BC 组: {sorted(zs.keys())}")
        for grp in ("velocity_inlet", "wall", "pressure_outlet"):
            try:
                names = getattr(s.settings.setup.boundary_conditions, grp).get_state()
                say(f"    {grp}: {sorted(names.keys())}")
            except Exception:                               # noqa: BLE001
                pass
    except Exception as exc:                                # noqa: BLE001
        say(f"  BC 读取 FAIL: {str(exc)[:150]}")

    say("\n-- 转录关键行 --")
    try:
        txt = TRN.read_text(encoding="utf-8", errors="replace")
        keep = [ln.strip() for ln in txt.splitlines()
                if any(k in ln for k in ("cells", "faces", "nodes", "Error",
                                         "minimum volume", "maximum volume",
                                         "Volume statistics", "Done", "invalid"))]
        for ln in keep[-40:]:
            say(f"  | {ln[:150]}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  转录读取 FAIL: {str(exc)[:120]}")

    try:
        s.transcript.stop()
    except Exception:                                       # noqa: BLE001
        pass
    s.exit()
    say("\n核验完成")


if __name__ == "__main__":
    main()
