"""3D 圆射流「等温惰性混合」对照实验（无燃烧）—— 分离射流衰减的两个可能原因。

★ 诊断目的
  观测事实：CFD 轴心混合分数在 x/d≤15 衰减偏慢、x/d≥30 急剧过快
            （x/d=45：CFD 0.185 vs 实验 0.387）→ 下游燃料被过度稀释。
  两个候选原因：
    (A) 湍流模型固有偏差（k-ε 圆射流 round-jet anomaly）
    (B) 燃烧热释放反馈（高温→低密度→加速→增强混合）
  本脚本给出"无燃烧、等温"的对照解：
    * 若本解 F_axis 衰减 ≈ 燃烧解 → 原因 (A) 为主（与化学/热释放无关）
    * 若本解明显慢于燃烧解     → 原因 (B) 为主

★ 与燃烧态（run_box3d_edm.py）的唯一差别
  energy OFF（等温，进口温度与壁面温度不生效）
  不启用 volumetric reactions（机理仅用于定义组分，不反应）
  其余全部相同：网格 / 进口 U·I·Dh / 进口组分 / 湍流模型 / 离散格式

用法：
  python scripts/run_box3d_mix.py --seg cold --n-cold 60
  python scripts/run_box3d_mix.py --resume --n-iter 300 --chunk 25 --seg seg01
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["AWP_ROOT252"] = r"D:\Program Files\ANSYS\2025R2\v252"
os.environ.setdefault("FLUENT_AUTOMATIC_TRANSCRIPT", "0")
sys.path.insert(0, str(ROOT / "scripts"))
import flamed_common as C  # noqa: E402
import run_np_eq as R      # noqa: E402

RUN = ROOT / "run"
MECH = ROOT / "mechanism"
MESH = ROOT / "mesh" / "box3d" / "compact_round300.msh"
Z3 = {"jet": "velocity-inlet-3", "pilot": "velocity-inlet-4",
      "coflow": "velocity-inlet-5"}
WALLS = ["wall-7", "wall-8", "wall-9", "wall-10"]
OUTLET = "pressure-outlet-6"
# ★ 进口组分与燃烧态完全一致（保证 F 场可比）
YS = {"jet": C.Y_JET, "pilot": C.Y_PILOT, "coflow": C.Y_COFLOW}
US = {"jet": (49.6, 0.0879, 0.0072), "pilot": (11.4, 0.1092, 0.0105),
      "coflow": (0.9, 0.0100, 0.30)}

TAG = "box3d_mix"
LOG = RUN / "log_box3d_mix.txt"
TRN = RUN / "trn_box3d_mix.txt"
CASE = RUN / f"{TAG}.cas.h5"
BACKUP = RUN / "backup_3d"


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def set_eq(s, species_on: bool):
    cmds = ["/solve/set/equations/flow yes", "/solve/set/equations/ke yes",
            "/solve/set/equations/epsilon yes",
            # ★ 等温：能量方程**始终关闭**
            "/solve/set/equations/energy no",
            f"/solve/set/equations/species {'yes' if species_on else 'no'}"]
    for e in cmds:
        try:
            s.execute_tui(e)
        except Exception:                                   # noqa: BLE001
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default="cold")
    ap.add_argument("--cold", action="store_true", help="首段：读网格并建场")
    ap.add_argument("--resume", action="store_true", help="续段")
    ap.add_argument("--n-cold", type=int, default=60)
    ap.add_argument("--n-iter", type=int, default=300)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--cores", type=int, default=10)
    ap.add_argument("--mesh", default=str(MESH))
    a = ap.parse_args()

    import ansys.fluent.core as pyfluent

    say("\n" + "=" * 78)
    say(time.strftime("%F %T"),
        f"3D 等温惰性混合（无燃烧）seg={a.seg} n_iter={a.n_iter} "
        f"resume={a.resume} cores={a.cores}")
    say("=" * 78)

    s = pyfluent.launch_fluent(
        mode="solver", dimension=3, precision="double",
        processor_count=a.cores, ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    say(f"  已启动 Fluent {s.get_fluent_version()}（{a.cores} 核）")
    if TRN.exists():
        TRN.unlink()
    s.transcript.start(file_name=str(TRN), write_to_stdout=False)
    time.sleep(1.0)

    bc = s.settings.setup.boundary_conditions

    if a.resume:
        s.settings.file.read_case_data(file_name=str(CASE))
        say(f"  续段：已读 {CASE.name} + data")
    else:
        t0 = time.time()
        s.settings.file.read_mesh(file_name=a.mesh)
        say(f"  读网格 OK（{time.time()-t0:.0f}s）")
        v = s.settings.setup.models.viscous
        v.model = "k-epsilon"
        v.k_epsilon_model = "realizable"
        v.near_wall_treatment.wall_treatment = "enhanced-wall-treatment"
        # ★★ 等温：关闭能量方程
        s.settings.setup.models.energy.enabled = False
        say("  k-ε realizable + EWT + 能量 **OFF**（等温）")
        try:
            s.tui.define.models.species.species_transport("yes")
            s.settings.setup.models.species.import_chemkin(
                kinetics_input_file=str(MECH / "ch4_2step_chem.inp"),
                thermodb_input_file=str(MECH / "ch4_2step_thermo.dat"),
                trans_prop=False,
            )
            say("  组分输运 + ch4_2step 机理导入 OK（仅用于定义组分）")
        except Exception as exc:                            # noqa: BLE001
            say(f"  机理导入 FAIL: {str(exc)[:250]}")
            s.exit()
            sys.exit(3)
        # ★★ 关闭体积反应：只做惰性混合
        for c in ("/define/models/species/volumetric-reactions? no",
                  "/define/models/species/volumetric-reactions no"):
            try:
                s.execute_tui(c)
                break
            except Exception:                               # noqa: BLE001
                continue
        rstate = None
        for path in ("setup/models/species/reactions",
                     "setup/models/species/volumetric_reactions"):
            try:
                rstate = s.settings.get_var(path)
                break
            except Exception:                               # noqa: BLE001
                continue
        say(f"  volumetric reactions 状态回读 = {rstate!r}")

        # ---- 进口：U / I / Dh / 组分（与燃烧态同值）；温度不设（等温）----
        for k in ("jet", "pilot", "coflow"):
            z = bc.velocity_inlet[Z3[k]]
            U, I, Dh = US[k]
            z.momentum.velocity.value = U
            z.turbulence.turbulence_specification = \
                "Intensity and Hydraulic Diameter"
            z.turbulence.turbulent_intensity = I
            z.turbulence.hydraulic_diameter = Dh
            smf = z.species.species_mass_fraction
            avail = list(smf.keys())
            want = {kk.lower(): vv for kk, vv in YS[k].items()}
            explicit = {kk: vv for kk, vv in want.items() if kk in avail}
            st = {kk: {"option": "value", "value": 0.0} for kk in avail}
            for kk, vv in explicit.items():
                st[kk] = {"option": "value", "value": vv}
            smf.set_state(st)
            back = smf.get_state()
            got = {kk: round(v2.get("value", 0), 5)
                   for kk, v2 in back.items() if v2.get("value", 0) > 1e-6}
            try:
                z.thermal.temperature.value = 291.0
            except Exception:                               # noqa: BLE001
                pass
            say(f"  {Z3[k]}: U={U} I={I} Dh={Dh} 组分={got}")

        # ---- 硬校验 ----
        bad = []
        for k in ("jet", "pilot", "coflow"):
            z = bc.velocity_inlet[Z3[k]]
            try:
                u = z.momentum.velocity_magnitude.value.get_state()
            except Exception:                               # noqa: BLE001
                u = z.momentum.velocity.value.get_state()
            ok = abs(float(u) - US[k][0]) < 1e-6
            say(f"  [校验] {Z3[k]:<20} U={u}(应 {US[k][0]})  {'✓' if ok else '✗'}")
            if not ok:
                bad.append(Z3[k])
        if bad:
            say(f"  ★★ 校验失败 {bad} → 中止")
            s.exit()
            sys.exit(5)

        try:
            bc.pressure_outlet[OUTLET].momentum.gauge_pressure.value = 0.0
            say(f"  {OUTLET} 0 Pa")
        except Exception as exc:                            # noqa: BLE001
            say(f"  outlet FAIL: {str(exc)[:120]}")

        try:
            s.settings.solution.initialization.hybrid_initialize()
            say("  hybrid init OK")
        except Exception as exc:                            # noqa: BLE001
            say(f"  hybrid init FAIL: {str(exc)[:150]}")

    # ---- 迭代 ----
    R.disable_residual_autostop(s)
    R.enable_pseudo_transient(s, scale=0.5)
    R.set_urf(s, 0.7)
    R.force_first_order(s)
    set_eq(s, species_on=True)
    say("  一阶起步（species on，能量 off；伪时间 + URF 0.7）")
    n1 = a.n_cold if not a.resume else 0
    if n1:
        t0 = time.time()
        s.settings.solution.run_calculation.iterate(iter_count=n1)
        say(f"  一阶 {n1} 步 OK（{(time.time()-t0)/n1:.2f} s/步）")

    if a.n_iter > 0:
        R.set_second_order(s)
        set_eq(s, species_on=True)
        say("  二阶")
        done = 0
        t0 = time.time()
        while done < a.n_iter:
            n = min(a.chunk, a.n_iter - done)
            s.settings.solution.run_calculation.iterate(iter_count=n)
            done += n
            # 轴心混合分数诊断（比温度更能反映混合）
            try:
                ls = s.settings.results.surfaces.line_surface
                if "clx" not in s.settings.results.surfaces.line_surface.get_state():
                    ls.create(name="clx")
                    ls["clx"] = {"p0": [0.0, 0.0, 0.0], "p1": [0.72, 0.0, 0.0]}
                fd = s.fields.field_data
                ch4 = fd.get_scalar_field_data(field_name="ch4",
                                              surfaces=["clx"], node_value=True)
                co = fd.get_scalar_field_data(field_name="co",
                                             surfaces=["clx"], node_value=True)
                co2 = fd.get_scalar_field_data(field_name="co2",
                                              surfaces=["clx"], node_value=True)
                say(f"  [混合 {done}/{a.n_iter}] Y_CH4_axis={list(ch4.values())[0][0]:.4f}  "
                    f"{(time.time()-t0)/done:.2f} s/步")
                _ = co, co2
            except Exception:                               # noqa: BLE001
                say(f"  [混合 {done}/{a.n_iter}] {(time.time()-t0)/done:.2f} s/步")

    s.settings.file.write_case(file_name=str(CASE))
    s.settings.file.write_data(file_name=str(RUN / f"{TAG}.dat.h5"))
    say(f"  已存 {CASE.name} / {TAG}.dat.h5")
    try:
        d = BACKUP / a.seg
        d.mkdir(parents=True, exist_ok=True)
        for f in (CASE, RUN / f"{TAG}.dat.h5"):
            shutil.copy2(f, d / f.name)
        say(f"  [backup] → {d}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  [backup] FAIL: {str(exc)[:120]}")

    try:
        s.exit()
    except Exception:                                       # noqa: BLE001
        pass
    say(f"===== SEG {a.seg} DONE =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
