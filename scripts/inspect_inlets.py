"""回读进口边界条件实际值（3D box3d_edm case + 2D np_eq_seed 对照）。

用途：核查进口设置是否符合 Flame D 工况（速度/湍流/温度/组分），
重点检查 species_mass_fraction 总和是否归一（Fluent 对不归一的处理方式）。
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

RUN = ROOT / "run"
LOG = RUN / "inspect_inlets.log"

if LOG.exists():
    LOG.unlink()


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def dump_inlet(s, nm, mode: str):
    """mode: 'species'（组分输运，回读 species_mass_fraction）
             'fmean'（非预混，回读 mean_mixture_fraction）
             'none'（只回读速度/湍流/温度）"""
    bc = s.settings.setup.boundary_conditions
    try:
        z = bc.velocity_inlet[nm]
    except Exception as exc:                                # noqa: BLE001
        say(f"  {nm}: 不存在（{str(exc)[:80]}）")
        return
    U = I = Dh = T = None
    try:
        U = z.momentum.velocity.value.get_state()
    except Exception:                                       # noqa: BLE001
        try:
            U = z.momentum.velocity_magnitude.value.get_state()
        except Exception:                                   # noqa: BLE001
            pass
    try:
        I = z.turbulence.turbulent_intensity.get_state()
    except Exception:                                       # noqa: BLE001
        pass
    try:
        Dh = z.turbulence.hydraulic_diameter.get_state()
    except Exception:                                       # noqa: BLE001
        pass
    try:
        T = z.thermal.temperature.value.get_state()
    except Exception:                                       # noqa: BLE001
        pass
    say(f"  {nm}: U={U}  I={I}  Dh={Dh}  T={T}")
    if mode == "fmean":
        for key in ("mean_mixture_fraction", "mixture_fraction"):
            try:
                node = getattr(z.species, key)
                say(f"      {key} = {node.get_state()!r}")
                break
            except Exception:                               # noqa: BLE001
                continue
        return
    if mode != "species":
        return
    try:
        smf = z.species.species_mass_fraction.get_state()
        tot = 0.0
        for sp, v in sorted(smf.items()):
            val = v.get("value", 0.0) if isinstance(v, dict) else v
            tot += float(val)
            if abs(float(val)) > 1e-9:
                say(f"      {sp:<10} = {float(val):.6f}")
        say(f"      ---- 总和 = {tot:.6f}（{'★ 不归一！' if abs(tot-1) > 1e-4 else 'OK'}）")
    except Exception as exc:                                # noqa: BLE001
        say(f"      组分回读失败: {str(exc)[:120]}")


def main():
    import ansys.fluent.core as pyfluent

    say("=" * 74)
    say(time.strftime("%F %T"), "进口边界条件回读核查")
    say("=" * 74)

    # ---- 3D box3d_edm ----
    s = pyfluent.launch_fluent(
        mode="solver", dimension=3, precision="double",
        processor_count=2, ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    say("\n【3D 方管 box3d_edm】")
    s.settings.file.read_case(file_name=str(RUN / "box3d_edm.cas.h5"))
    try:
        st = s.settings.setup.models.species.get_state()
        say(f"  species 模型: {str(st)[:300]}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  species 状态读取失败: {str(exc)[:120]}")
    for nm in ("velocity-inlet-3", "velocity-inlet-4", "velocity-inlet-5"):
        dump_inlet(s, nm, "species")
    try:
        po = s.settings.setup.boundary_conditions.pressure_outlet["pressure-outlet-6"]
        say(f"  pressure-outlet-6: p_gauge={po.momentum.gauge_pressure.value.get_state()}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  出口回读失败: {str(exc)[:100]}")
    s.exit()

    # ---- 2D np_eq_seed 对照 ----
    s = pyfluent.launch_fluent(
        mode="solver", dimension=2, precision="double",
        processor_count=2, ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    say("\n【2D 轴对称 np_eq_seed（对照）】")
    s.settings.file.read_case(file_name=str(RUN / "np_eq_seed.cas.h5"))
    for nm in ("velocity-inlet-5", "velocity-inlet-6", "velocity-inlet-7"):
        dump_inlet(s, nm, "fmean")
    try:
        st = s.settings.setup.models.species.get_state()
        say(f"  species 模型: {str(st)[:200]}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  species 状态: {str(exc)[:120]}")
    s.exit()
    say("\n核查完成")


if __name__ == "__main__":
    main()
