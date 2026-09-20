"""3D 长方体通道燃烧（species transport + 2 步机理 + EDM），分段可续。

流程（首段 --phase cold）：
  读 3D 网格 → k-ε realizable+EWT → 能量 on → species transport + import_chemkin(2step)
  → 进口组分（Y_JET/Y_PILOT/Y_COFLOW + N2 余量）→ 热态入口 1100K → 壁面 300K
  → hybrid init → 冷流（species 方程 off，一阶）60 步 → 开 EDM + species on
续段（--phase edm --resume）：读 case+data → 迭代

用法：
  & $PY -u scripts\run_box3d_edm.py --phase cold --n-cold 60
  & $PY -u scripts\run_box3d_edm.py --phase edm --resume --n-iter 50
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
TAG = "box3d_edm"                       # 可被 --tag 覆盖（main 里重设）
LOG = RUN / f"log_{TAG}.txt"
TRN = RUN / f"trn_{TAG}.txt"
MESH = ROOT / "mesh" / "box3d" / "compact_round.msh"   # 可被 --mesh 覆盖
# （V3 起：全域圆射流进口，975,744 单元；伴流 r≤150mm + 空气 r>150mm 均 0.9 m/s）
BACKUP = RUN / "backup_3d"

Z3 = {"jet": "velocity-inlet-3", "pilot": "velocity-inlet-4",
      "coflow": "velocity-inlet-5",
      "air": "velocity-inlet-11"}          # ★ 伴流（r>150mm）以外的空气
WALLS = ["wall-7", "wall-8", "wall-9", "wall-10"]
HOT_T = 1100.0
# ★ 文档进口温度（V3 起全程使用，不再走"1100K 热态启动"临时值）
#   ★★ 命名避坑：main() 内 --hold 分支有同名局部变量 DOC_T，会遮蔽模块级常量
#      → 曾导致"local variable 'DOC_T' referenced before assignment"，进口温度与
#        组分**静默未设置**（速度已设）→ 必须用 INLET_DOC_T 这个不冲突的名字。
INLET_DOC_T = {"jet": C.T_JET, "pilot": C.T_PILOT, "coflow": C.T_COFLOW,
               "air": C.T_COFLOW}


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def set_eq(s, species_on: bool):
    for e in ("/solve/set/equations/flow yes", "/solve/set/equations/ke yes",
              "/solve/set/equations/epsilon yes", "/solve/set/equations/energy yes",
              f"/solve/set/equations/species {'yes' if species_on else 'no'}"):
        try:
            s.execute_tui(e)
        except Exception:                                   # noqa: BLE001
            pass


def set_eq_species(s):
    R.force_first_order(s)
    try:
        R.set_second_order(s)
    except Exception:                                       # noqa: BLE001
        pass


def backup(tag: str):
    try:
        BACKUP.mkdir(parents=True, exist_ok=True)
        d = BACKUP / tag
        d.mkdir(exist_ok=True)
        for f in (RUN / f"{TAG}.cas.h5", RUN / f"{TAG}.dat.h5"):
            if f.exists():
                shutil.copy2(f, d / f.name)
        say(f"  [backup] → run/backup_3d/{tag}/")
    except Exception as exc:                                # noqa: BLE001
        say(f"  [backup] FAIL: {str(exc)[:140]}")


def enable_edm(s) -> bool:
    """开 EDM（★顺序关键：必须先开 volumetric-reactions，turb-chem-interaction
    节点才会激活；反序会报 api-set-var: the object is not active）。"""
    for c in ("/define/models/species/volumetric-reactions? yes",
              "/define/models/species/volumetric-reactions yes"):
        try:
            s.execute_tui(c)
            break
        except Exception:                                   # noqa: BLE001
            continue
    ok = False
    for attempt in range(3):
        try:
            s.settings.setup.models.species.turb_chem_interaction.set_state(
                "eddy-dissipation")
            got = s.settings.setup.models.species.turb_chem_interaction.get_state()
            ok = "eddy" in str(got).lower() and "concept" not in str(got).lower()
            say(f"  turb_chem = {got!r}（{'OK' if ok else '需复查'}）")
            break
        except Exception as exc:                            # noqa: BLE001
            say(f"  设 EDM 第 {attempt+1} 次失败: {str(exc)[:140]}")
            time.sleep(2.0)
    return ok


def fix_outlet(s) -> None:
    """出口回流条件修正：默认 300 K + 全 0 组分（Fluent 会用末位组分补齐 →
    等效吸入**纯 N₂**）→ 改为环境空气 291 K + o2/h2o（与 coflow 同）。

    表压 0 Pa **不动**（p_abs = 101325 + 0 = 1 atm，正确）。幂等，可续算时重复调用。
    """
    try:
        po = s.settings.setup.boundary_conditions.pressure_outlet[
            "pressure-outlet-6"]
        po.thermal.backflow_total_temperature = C.T_COFLOW
        smf = po.species.backflow_species_mass_fraction
        avail = list(smf.keys())
        want = {kk.lower(): vv for kk, vv in C.Y_COFLOW.items()}
        stt = {kk: {"option": "value", "value": 0.0} for kk in avail}
        for kk, vv in want.items():
            if kk in stt:
                stt[kk] = {"option": "value", "value": vv}
        smf.set_state(stt)
        say(f"  出口回流条件已修正 → T={C.T_COFLOW} K + 空气 {want}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  出口回流条件修正 FAIL: {str(exc)[:160]}")


def main():
    global TAG, LOG, TRN, MESH          # ★ 必须在任何使用之前声明（曾因此 SyntaxError）
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["cold", "edm"], default="edm")
    ap.add_argument("--n-cold", type=int, default=60)
    ap.add_argument("--n-iter", type=int, default=50)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--cores", type=int, default=10)
    ap.add_argument("--autosave-every", type=int, default=25)
    ap.add_argument("--seg", default="", help="备份子目录名（如 seg03）")
    ap.add_argument("--hold", action="store_true",
                    help="★ 自持段：入口温度切回文档值（jet 294 / pilot 1880 / "
                         "coflow 291 K）后续算——对标实验的最终口径")
    ap.add_argument("--hot", type=float, default=0.0,
                    help="热态启动温度 [K]；0（默认）= 全程用文档温度"
                         "（jet 294 / pilot 1880 / coflow+air 291），不再启用临时值")
    ap.add_argument("--mesh", default=str(MESH), help="网格路径（默认 compact.msh）")
    ap.add_argument("--tag", dest="tag2", default=TAG, help="算例 tag（决定 log/case 名）")
    a = ap.parse_args()
    a.cores = max(1, min(a.cores, 10))

    TAG = a.tag2
    LOG = RUN / f"log_{TAG}.txt"
    TRN = RUN / f"trn_{TAG}.txt"
    MESH = Path(a.mesh)

    # 让被导入辅助函数的 say() 也写本日志（run_np_eq 已在模块级 import 为 R）
    R.LOG, R.TRN = LOG, TRN

    if LOG.exists() and not a.resume:
        LOG.unlink()

    import ansys.fluent.core as pyfluent

    say("\n" + "=" * 76)
    say(time.strftime("%F %T"), f"3D 燃烧 phase={a.phase} n={a.n_iter} "
        f"resume={a.resume} cores={a.cores} seg={a.seg}")
    say(f"===== SEG {a.seg or 'none'} START =====")
    say("=" * 76)

    s = pyfluent.launch_fluent(
        mode="solver", dimension=3, precision="double",
        processor_count=a.cores, ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    say(f"已启动 {s.get_fluent_version()}（3D，{a.cores} 核）")
    if TRN.exists():
        TRN.unlink()
    s.transcript.start(file_name=str(TRN), write_to_stdout=False)
    time.sleep(1.0)

    case = RUN / f"{TAG}.cas.h5"
    if a.resume and case.exists():
        s.settings.file.read_case_data(file_name=str(case))
        say(f"  续算：读 {case.name}+data")
        try:
            sp_state = s.settings.setup.models.species.turb_chem_interaction.get_state()
            say(f"  当前 turb_chem = {sp_state!r}")
        except Exception as exc:                            # noqa: BLE001
            say(f"  读 turb_chem FAIL: {str(exc)[:140]}")
        enable_edm(s)                                       # 幂等：确保 EDM 已设
        set_eq(s, species_on=True)
        set_eq_species(s)
        fix_outlet(s)                    # 幂等：出口回流 → 291 K + 空气

    # ---- ★ 自持段：入口温度切回文档值（对标实验的最终口径）----
    if a.hold:
        DOC_T = {"jet": C.T_JET, "pilot": C.T_PILOT, "coflow": C.T_COFLOW}
        bc = s.settings.setup.boundary_conditions
        for k in ("jet", "pilot", "coflow"):
            try:
                bc.velocity_inlet[Z3[k]].thermal.temperature.value = DOC_T[k]
            except Exception as exc:                        # noqa: BLE001
                say(f"  切回 {Z3[k]} 温度 FAIL: {str(exc)[:120]}")
        say(f">>> 自持段：入口温度已切回文档值 "
            f"jet={DOC_T['jet']} / pilot={DOC_T['pilot']} / coflow={DOC_T['coflow']} K")
    else:
        t0 = time.time()
        s.settings.file.read_mesh(file_name=str(MESH))
        say(f"  读网格 OK（{time.time()-t0:.0f}s）")

        v = s.settings.setup.models.viscous
        v.model = "k-epsilon"
        v.k_epsilon_model = "realizable"
        v.near_wall_treatment.wall_treatment = "enhanced-wall-treatment"
        s.settings.setup.models.energy.enabled = True
        say("  k-ε realizable + EWT + 能量 on")

        try:
            s.tui.define.models.species.species_transport("yes")
            s.settings.setup.models.species.import_chemkin(
                kinetics_input_file=str(MECH / "ch4_2step_chem.inp"),
                thermodb_input_file=str(MECH / "ch4_2step_thermo.dat"),
                trans_prop=False,
            )
            say("  组分输运 + ch4_2step 机理导入 OK")
        except Exception as exc:                            # noqa: BLE001
            say(f"  机理导入 FAIL: {str(exc)[:250]}")
            s.exit()
            sys.exit(3)

        bc = s.settings.setup.boundary_conditions
        YS = {"jet": C.Y_JET, "pilot": C.Y_PILOT, "coflow": C.Y_COFLOW,
              "air": C.Y_COFLOW}          # ★ 空气区与伴流同组分（实验：都是空气）
        US = {"jet": (49.6, 0.0879, 0.0072), "pilot": (11.4, 0.1092, 0.0105),
              "coflow": (0.9, 0.0100, 0.30),
              "air": (0.9, 0.0100, 0.30)}  # ★ 空气不是静止的：同伴流 0.9 m/s
        use_hot = a.hot and a.hot > 0
        # ★ 300mm 实验尺寸域（RCOF=1e9）没有单独的 air 区：伴流覆盖整个截面。
        #   必须按"网格里实际存在的分区"来设置，否则硬校验会对不存在的 zone 取值而崩。
        try:
            _zin = set(bc.velocity_inlet.keys())
        except Exception:                                   # noqa: BLE001
            _zin = set(Z3.values())
        ACTIVE = [k for k in ("jet", "pilot", "coflow", "air")
                  if Z3[k] in _zin]
        _miss = [k for k in ("jet", "pilot", "coflow", "air")
                 if k not in ACTIVE]
        say(f"  进口分区生效={ACTIVE}  网格缺失={_miss if _miss else '无'}")
        for _k in ("jet", "pilot", "coflow"):
            if _k not in ACTIVE:
                say(f"  ★★ 必需进口分区 {_k} 不存在 → 中止")
                s.exit()
                sys.exit(5)
        for k in ACTIVE:
            try:
                z = bc.velocity_inlet[Z3[k]]
                U, I, Dh = US[k]
                z.momentum.velocity.value = U
                z.turbulence.turbulence_specification = \
                    "Intensity and Hydraulic Diameter"
                z.turbulence.turbulent_intensity = I
                z.turbulence.hydraulic_diameter = Dh
                t_set = float(a.hot) if use_hot else INLET_DOC_T[k]
                z.thermal.temperature.value = t_set
                smf = z.species.species_mass_fraction
                avail = list(smf.keys())
                want = {kk.lower(): vv for kk, vv in YS[k].items()}
                explicit = {kk: vv for kk, vv in want.items() if kk in avail}
                tot = sum(explicit.values())
                st = {kk: {"option": "value", "value": 0.0} for kk in avail}
                for kk, vv in explicit.items():
                    st[kk] = {"option": "value", "value": vv}
                smf.set_state(st)
                back = smf.get_state()
                got = {kk: round(v2.get("value", 0), 5)
                       for kk, v2 in back.items() if v2.get("value", 0) > 1e-6}
                say(f"  {Z3[k]}: U={U} T={t_set} 组分显式={ {kk: round(vv,5) for kk,vv in explicit.items()} }"
                    f" 和={tot:.5f} → 回读={got} 和={sum(vv.get('value',0) for vv in back.values()):.5f}")
            except Exception as exc:                        # noqa: BLE001
                say(f"  {Z3[k]} FAIL: {str(exc)[:200]}")
        # ★★ 硬校验：设置后逐项回读，任一进口/壁面不符即**中止**（不允许"半设置"）
        bad = []

        def gval(node):
            """兼容两种节点结构：湍流节点无 .value 层，momentum/thermal 有。"""
            try:
                return node.value.get_state()
            except Exception:                               # noqa: BLE001
                try:
                    return node.get_state()
                except Exception:                           # noqa: BLE001
                    return None

        for k in ACTIVE:
            z = bc.velocity_inlet[Z3[k]]
            exp_u = US[k][0]
            exp_t = float(a.hot) if use_hot else INLET_DOC_T[k]
            got_u = gval(z.momentum.velocity_magnitude)
            got_t = gval(z.thermal.temperature)
            ok = (got_u is not None and abs(float(got_u) - exp_u) < 1e-6
                  and got_t is not None and abs(float(got_t) - exp_t) < 1e-6)
            say(f"  [校验] {Z3[k]:<20} U={got_u}(应 {exp_u})  "
                f"T={got_t}(应 {exp_t})  {'✓' if ok else '✗'}")
            if not ok:
                bad.append(Z3[k])
        for nm in WALLS:
            try:
                w = bc.wall[nm]
                w.thermal.thermal_bc = "Temperature"
                w.thermal.temperature.value = 300.0
            except Exception as exc:                        # noqa: BLE001
                say(f"  {nm} FAIL: {str(exc)[:120]}")
                bad.append(nm)
        say("  壁面 4 面 300K OK")
        if bad:
            say(f"  ★★ 进口/壁面设置校验失败：{bad} → 中止（不允许带错设置开局）")
            s.exit()
            sys.exit(5)

        R.force_first_order(s)
        R.enable_pseudo_transient(s, scale=0.5)
        R.set_urf(s, 0.5)
        R.disable_residual_autostop(s)

        t0 = time.time()
        try:
            s.settings.solution.initialization.hybrid_initialize()
            say(f"  hybrid init OK（{time.time()-t0:.0f}s）")
        except Exception as exc:                            # noqa: BLE001
            say(f"  init FAIL: {str(exc)[:250]}")
            s.exit()
            sys.exit(4)

        if a.phase == "cold":
            set_eq(s, species_on=False)
            say(f"\n>>> 冷流（species off）{a.n_cold} 步")
            done = 0
            t0 = time.time()
            while done < a.n_cold:
                n = min(a.chunk, a.n_cold - done)
                s.settings.solution.run_calculation.iterate(iter_count=n)
                done += n
                say(f"  [冷流 {done}/{a.n_cold}] {(time.time()-t0)/done:.2f} s/步")
            try:
                s.settings.file.write_case(file_name=str(case))
                s.settings.file.write_data(file_name=str(RUN / f"{TAG}.dat.h5"))
                say("  冷流 case+data 已存")
            except Exception as exc:                        # noqa: BLE001
                say(f"  存盘 FAIL: {str(exc)[:140]}")

        # 开 EDM + species（顺序见 enable_edm 注释）
        enable_edm(s)
        set_eq(s, species_on=True)
        set_eq_species(s)
        fix_outlet(s)
        say("  反应 + species 方程 + 二阶 已开")

    # ---- 迭代（本段）----
    say(f"\n>>> 迭代 {a.n_iter} 步")
    done = 0
    t0 = time.time()
    while done < a.n_iter:
        n = min(a.chunk, a.n_iter - done)
        s.settings.solution.run_calculation.iterate(iter_count=n)
        done += n
        if a.autosave_every > 0 and done % a.autosave_every == 0:
            try:
                s.settings.file.write_case(file_name=str(case))
                s.settings.file.write_data(file_name=str(RUN / f"{TAG}.dat.h5"))
                say(f"  [autosave] {done} 步已存")
            except Exception as exc:                         # noqa: BLE001
                say(f"  [autosave] FAIL: {str(exc)[:120]}")
        # 关键监测：最高温度（火焰是否建立）
        try:
            import numpy as np
            if "cl3d" not in R._SURFACES_MADE:
                s.tui.surface.line_surface("cl3d", 0.216, -0.05, 0.0, 0.216, 0.05, 0.0)
                R._SURFACES_MADE.add("cl3d")
            vals = s.fields.field_data.get_scalar_field_data(
                field_name="temperature", surfaces=["cl3d"], node_value=True)
            t = np.asarray(list(vals.values())[0], dtype=float).ravel()
            say(f"  [迭代 {done}/{a.n_iter}] T@30d: {t.min():.0f}..{t.max():.0f} K"
                f"  {(time.time()-t0)/max(done,1):.2f} s/步")
        except Exception:                                    # noqa: BLE001
            say(f"  [迭代 {done}/{a.n_iter}] {(time.time()-t0)/max(done,1):.2f} s/步")

    dt = time.time() - t0
    say(f"\n  本段 {done} 步用时 {dt:.0f}s（{dt/max(done,1):.2f} s/步）")

    try:
        s.settings.file.write_case(file_name=str(case))
        s.settings.file.write_data(file_name=str(RUN / f"{TAG}.dat.h5"))
        say(f"  已存 {TAG}.cas.h5 / .dat.h5")
        if a.seg:
            backup(a.seg)
    except Exception as exc:                                 # noqa: BLE001
        say(f"  存盘 FAIL: {str(exc)[:150]}")

    try:
        s.transcript.stop()
    except Exception:                                        # noqa: BLE001
        pass
    s.exit()
    say(f"===== SEG {a.seg or 'none'} DONE =====")
    say("完成")


if __name__ == "__main__":
    main()
