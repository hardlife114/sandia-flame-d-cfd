"""生成非预混 baseline 的 GUI 前置 case：除 Species 面板外全部设好。

背景：非预混模型的使能校验（fuel-stream unity-sum）必须经 GUI 的
Species Model 面板（TUI/settings 多路尝试均被挡，见 probe_np1..14 与
run/probe_np*.log）。按项目 flamelet-import 的既有模式：GUI 只点一次，
之后 headless。本脚本把其余全部设置完成并存
  run/np_eq_pregui.cas.h5

用户只需：打开该 case -> Species Model -> Non-Premixed Combustion
（Equilibrium + Beta PDF + 非绝热 + 燃料流/氧化流分数）-> OK -> 另存为
run/np_eq_seed.cas.h5。

用法:
  python prep_np_pregui.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["AWP_ROOT252"] = r"D:\Program Files\ANSYS\2025R2\v252"
os.environ.setdefault("FLUENT_AUTOMATIC_TRANSCRIPT", "0")

import flamed_common as C  # noqa: E402

RUN = ROOT / "run"
LOG = RUN / "prep_np_pregui.log"

Z = {"jet": "velocity-inlet-5", "pilot": "velocity-inlet-6",
     "coflow": "velocity-inlet-7", "lip": "wall-3", "rim": "wall-4"}
INLETS = {
    "jet":    dict(U=49.6, I=0.0879, Dh=C.D_JET, T=C.T_JET),
    "pilot":  dict(U=11.4, I=0.1092, Dh=0.0105, T=C.T_PILOT),
    "coflow": dict(U=C.U_COFLOW, I=0.0100, Dh=0.30, T=C.T_COFLOW),
}
WALL_T = 500.0


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    if LOG.exists():
        LOG.unlink()
    say("=" * 78)
    say(time.strftime("%F %T"), "prep_np_pregui 开始")
    say("=" * 78)

    import ansys.fluent.core as pyfluent

    s = pyfluent.launch_fluent(
        mode="solver", dimension=2, precision="double",
        processor_count=4, ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    mesh = ROOT / "mesh" / "v5" / "coarse.msh"
    s.file.read_case(file_name=str(mesh))
    s.settings.setup.general.solver.two_dim_space = "axisymmetric"
    v = s.settings.setup.models.viscous
    v.model = "k-epsilon"
    v.k_epsilon_model = "realizable"
    v.near_wall_treatment.wall_treatment = "enhanced-wall-treatment"
    s.settings.setup.general.operating_conditions.operating_pressure = C.P_OP
    s.settings.setup.models.energy.enabled = True
    say("基础设置 OK（k-e realizable + EWT + 能量 + 操作压）")

    bc = s.settings.setup.boundary_conditions
    for k, d in INLETS.items():
        z = bc.velocity_inlet[Z[k]]
        z.momentum.velocity.value = d["U"]
        z.turbulence.turbulence_specification = "Intensity and Hydraulic Diameter"
        z.turbulence.turbulent_intensity = d["I"]
        z.turbulence.hydraulic_diameter = d["Dh"]
        z.thermal.temperature.value = d["T"]
        say(f"  {Z[k]}: U={d['U']}, I={d['I']}, Dh={d['Dh']}, T={d['T']} K")

    for k in ("lip", "rim"):
        w = bc.wall[Z[k]]
        w.thermal.thermal_bc = "Temperature"
        w.thermal.t.value = WALL_T
    wf = None
    for nm in ("wall-10", "wall-farfield"):
        try:
            wf = bc.wall[nm]
            break
        except Exception:                                   # noqa: BLE001
            continue
    if wf is not None:
        wf.thermal.thermal_bc = "Temperature"
        wf.thermal.t.value = 300.0
        say("  外缘壁面 wall-10: 300 K")
    try:
        bc.pressure_outlet["pressure-outlet-9"].momentum.gauge_pressure.value = 0.0
        say("  outlet: 0 Pa")
    except Exception as exc:                                # noqa: BLE001
        say(f"  outlet 设置 FAIL: {str(exc)[:150]}")

    # 混合初始化（给 GUI 后的续算一个合理初场）
    try:
        s.settings.solution.initialization.hybrid_initialize()
        say("  hybrid init OK")
    except Exception as exc:                                # noqa: BLE001
        say(f"  hybrid init FAIL: {str(exc)[:150]}")

    out = RUN / "np_eq_pregui.cas.h5"
    s.settings.file.write_case(file_name=str(out))
    say(f"已保存 {out}")

    try:
        s.exit()
    except Exception:                                       # noqa: BLE001
        pass
    say("\nprep 完成")


if __name__ == "__main__":
    main()
