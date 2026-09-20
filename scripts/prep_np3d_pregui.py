"""生成 3D 非预混 baseline 的 GUI 前置 case：除 Species Model 面板外全部设好。

背景（重要）：非预混模型的**使能**必须经 GUI —— Fluent 的 fuel-stream unity-sum
校验挡住 TUI/settings 路径（TUI 报 "Fuel species sum to 0 (unity sum is required)"，
已 probe 14 次；且 setup.models.species 下只有 {model, options}，没有 fuel/oxidizer
流定义字段，materials/mixture/pdf-mixture 里也没有）。
→ 只有 **PDF 表读取** 可脚本化，使能必须点一次 GUI（同 2D 时的工作流）。

本脚本把其余全部设置完成并存 run/np3d_pregui.cas.h5。
用户只需：打开该 case -> Species Model -> Non-Premixed Combustion
  （Equilibrium + Beta PDF + 关闭能量方程=绝热 + 燃料流/氧化流分数，见下）
  -> OK -> 另存为 run/np3d_seed.cas.h5

GUI 面板里要填的流分数（与 2D np_eq_seed 完全同口径）：
  燃料流 (Fuel Stream)：   ch4 = 0.15607, n2 = 0.84393      （去掉 O2！见下）
  氧化流 (Oxidizer Stream)：o2 = 0.23574, h2o = 0.006256, n2 = 0.75800
  ★ 燃料流必须"去掉 O2"：绝热模型把含 O2 的燃料流当已平衡 → T(f=1) 自燃到 ~1006 K，
    射流密度低 3.4 倍、火焰过短（实测 x/d=45 只有 954 K）。代价：射流自身 19.65% 的 O2
    被忽略（换为 N2，保证 Z_C 与射流相同 → f_jet = 1，文档 f 值可直接用）。
  该口径下 f_st = 0.2741，文档 pilot f = 0.27 ≈ f_st（物理正确）。

用法: python scripts/prep_np3d_pregui.py
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
LOG = RUN / "prep_np3d_pregui.log"
MESH = ROOT / "mesh" / "box3d" / "compact_round300.msh"

# 3D 300mm 域（圆进口）的 zone 编号
Z = {"jet": "velocity-inlet-3", "pilot": "velocity-inlet-4",
     "coflow": "velocity-inlet-5"}
OUTLET = "pressure-outlet-6"
WALLS = ["wall-7", "wall-8", "wall-9", "wall-10"]
INLETS = {
    "jet":    dict(U=49.6, I=0.0879, Dh=0.0072, T=294.0),
    "pilot":  dict(U=11.4, I=0.1092, Dh=0.0105, T=1880.0),
    "coflow": dict(U=0.9, I=0.0100, Dh=0.30, T=291.0),
}
WALL_T = 300.0          # ★ 绝热模型下 energy 关闭，壁面热边界实际不生效


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    if LOG.exists():
        LOG.unlink()
    say("=" * 78)
    say(time.strftime("%F %T"), "prep_np3d_pregui 开始（3D 300mm 非预混前置）")
    say("=" * 78)
    if not MESH.exists():
        say(f"FAIL: 网格不存在 {MESH}")
        return 1

    import ansys.fluent.core as pyfluent

    s = pyfluent.launch_fluent(
        mode="solver", dimension=3, precision="double", processor_count=4,
        ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    say(f"已启动 {s.get_fluent_version()}（4 核）")
    s.file.read_case(file_name=str(MESH))
    say(f"网格读取 OK: {MESH.name}")

    # 基础模型（与 2D np_eq_seed 同口径）
    v = s.settings.setup.models.viscous
    v.model = "k-epsilon"
    v.k_epsilon_model = "realizable"
    v.near_wall_treatment.wall_treatment = "enhanced-wall-treatment"
    # ★ 能量方程关闭 = 绝热非预混（与 2D np_eq_seed 一致，已回读确认 energy=False）
    s.settings.setup.models.energy.enabled = False
    say("基础设置 OK（k-e realizable + EWT + 能量关闭=绝热）")

    bc = s.settings.setup.boundary_conditions
    for k, d in INLETS.items():
        z = bc.velocity_inlet[Z[k]]
        z.momentum.velocity.value = d["U"]
        z.turbulence.turbulence_specification = "Intensity and Hydraulic Diameter"
        z.turbulence.turbulent_intensity = d["I"]
        z.turbulence.hydraulic_diameter = d["Dh"]
        try:
            z.thermal.temperature.value = d["T"]        # 绝热下不生效，先写上
        except Exception:                                # noqa: BLE001
            pass
        say(f"  {Z[k]}: U={d['U']}, I={d['I']}, Dh={d['Dh']}, T={d['T']} K")

    for nm in WALLS:
        try:
            w = bc.wall[nm]
            w.thermal.thermal_bc = "Temperature"
            w.thermal.t.value = WALL_T
        except Exception as exc:                         # noqa: BLE001
            say(f"  {nm} 设置 FAIL: {str(exc)[:100]}")
    say(f"  壁面 4 面 {WALL_T} K（绝热下 thermal 不生效）")

    try:
        bc.pressure_outlet[OUTLET].momentum.gauge_pressure.value = 0.0
        say(f"  {OUTLET}: 0 Pa")
    except Exception as exc:                             # noqa: BLE001
        say(f"  outlet 设置 FAIL: {str(exc)[:150]}")

    # 硬校验：逐项回读
    bad = []
    for k, d in INLETS.items():
        z = bc.velocity_inlet[Z[k]]
        try:
            u = z.momentum.velocity.value.get_state()
            dh = z.turbulence.hydraulic_diameter.get_state()
            ok = abs(float(u) - d["U"]) < 1e-6 and abs(float(dh) - d["Dh"]) < 1e-9
        except Exception:                                # noqa: BLE001
            try:
                u = z.momentum.velocity.get_state()
                dh = z.turbulence.hydraulic_diameter.get_state()
                ok = abs(float(u) - d["U"]) < 1e-6 and abs(float(dh) - d["Dh"]) < 1e-9
            except Exception as exc:                     # noqa: BLE001
                ok = False
                u = dh = f"<{str(exc)[:40]}>"
        say(f"  [校验] {Z[k]:<20} U={u}(应 {d['U']})  Dh={dh}(应 {d['Dh']})  "
            f"{'✓' if ok else '✗'}")
        if not ok:
            bad.append(Z[k])
    if bad:
        say(f"  ★★ 校验失败 {bad} → 中止")
        s.exit()
        return 5

    out = RUN / "np3d_pregui.cas.h5"
    s.settings.file.write_case(file_name=str(out))
    say(f"已保存 {out}")

    try:
        s.exit()
    except Exception:                                    # noqa: BLE001
        pass
    say("\nprep 完成 —— 下一步：GUI 打开该 case，Species Model 选 Non-Premixed，"
        "另存为 run/np3d_seed.cas.h5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
