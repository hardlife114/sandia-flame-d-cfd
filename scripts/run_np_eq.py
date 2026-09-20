"""flameD 非预混（Equilibrium + β-PDF）baseline 主驱动。

前置：run/np_eq_seed.cas.h5 —— 由 GUI 完成 Species 面板（Non-Premixed,
Equilibrium + Beta PDF + 非绝热 + Option A 流定义）后另存。GUI-only 校验
无法 headless 完成（fuel-stream unity-sum，见 run/probe_np1..14 探测记录）。

流程：
  1. 读种子 case，校验 np 模型已开（species.model.option）；
  2. 入口混合分数：jet f=1.0 / pilot f=0.27（文档值）/ coflow f=0，variance=0；
     幂等重申速度/温度/湍流给定；
  3. 数值协议与 EDM 同口径：一阶迎风 + 伪瞬态(conservative, scale 0.5) + URF 0.5；
  4. ~1500 步（跑满核），每 chunk 监控 T_max/T_axis/CO2_max @x/d=30；
  5. 导出 9 径向剖面 + 中心线 -> results/cfd_npeq_d_v5_coarse.csv；
  6. 存 run/np_eq_d_v5_coarse.cas.h5 / .dat.h5。

用法:
  python run_np_eq.py --cores 12
"""
from __future__ import annotations

import argparse
import csv as _csv
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["AWP_ROOT252"] = r"D:\Program Files\ANSYS\2025R2\v252"
os.environ.setdefault("FLUENT_AUTOMATIC_TRANSCRIPT", "0")

import flamed_common as C  # noqa: E402

RUN = ROOT / "run"
LOG = RUN / "run_np_eq.log"
TRN = RUN / "trn_np_eq.txt"

Z = {"jet": "velocity-inlet-5", "pilot": "velocity-inlet-6",
     "coflow": "velocity-inlet-7"}

# ---- 混合分数参数化（重要）----
# 绝热非预混模型的**入口温度由查表 T(f) 决定，不受温度 BC 控制**：
#   * 燃料流若含 O2 → 绝热模型把它当作"已平衡"，T(f=1) 会自燃到 ~1006 K（射流应为 294 K）→ 密度低 3.4 倍、
#     射流动量偏小、混合分数衰减过快、火焰过短（实测 x/d=45 只有 954 K，实验 1938 K）。
#   * 燃料流为"纯燃料+惰性"（不含 O2）→ T(f=1) = 燃料流温度 294 K ✓
# 因此燃料流改为"去掉 O2 的射流"：ch4 0.15607 / n2 0.84393（质量分数，CH4 与射流同值，
# 保证 Z_C 与射流相同 → f_jet = 1，TNF 文档的 f 值全部可直接用）。
# 该口径下 f_st = 0.2741，而文档 pilot f = 0.27 ≈ f_st（物理上正确）。
# 近似：射流自身 19.65% 的 O2 被忽略（换为 N2）—— 这是"必须绝热"约束下的代价。
INLETS = {
    "jet":    dict(U=49.6, I=0.0879, Dh=C.D_JET, T=C.T_JET, F=1.00),
    "pilot":  dict(U=11.4, I=0.1092, Dh=0.0105, T=C.T_PILOT, F=0.27),
    "coflow": dict(U=C.U_COFLOW, I=0.0100, Dh=0.30, T=C.T_COFLOW, F=0.0),
}
WALL_T = 500.0
X_RAD = [0.75, 1, 2, 3, 15, 30, 45, 60, 75]
FIELDS = ["temperature", "ch4", "o2", "co2", "h2o", "co"]


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


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


def last_residuals() -> dict:
    try:
        lines = TRN.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:                                       # noqa: BLE001
        return {}
    hdr = None
    for i, l in enumerate(lines):
        if "continuity" in l and "energy" in l and "iter" in l:
            hdr = (i, l.split())
    if hdr is None:
        return {}
    i0, names = hdr
    for l in reversed(lines[i0 + 1:]):
        s = l.split()
        if len(s) >= 8 and re.match(r"^\d+$", s[0]):
            out = {}
            for nm, v in zip(names[1:], s[1:]):
                try:
                    out[nm] = float(v)
                except ValueError:
                    break
            return out
    return {}


def res_str() -> str:
    rs = last_residuals()
    if not rs:
        return ""
    pick = [k for k in ("continuity", "x-velocity", "energy", "k", "epsilon",
                        "fvar") if k in rs]
    return "  残差 " + " ".join(f"{k}={rs[k]:.1e}" for k in pick)


_SURFACES_MADE: set = set()


def _ensure_line(s, nm, x0, y0, x1, y1):
    """线面只建一次；重复创建会刷 'Surface name ... already exists' 错。"""
    if nm in _SURFACES_MADE:
        return
    s.tui.surface.line_surface(nm, x0, y0, x1, y1)
    _SURFACES_MADE.add(nm)


def core_T(s, tag):
    import numpy as np
    nm = "rad30d"
    try:
        _ensure_line(s, nm, 30 * C.D_JET, 0.0, 30 * C.D_JET, C.R_DOMAIN)
    except Exception as exc:                                # noqa: BLE001
        say(f"  [{tag}] 建线失败: {str(exc)[:130]}")
        return None
    vals = line_vals(s, nm, ["temperature", "co2", "y-coordinate"])
    t = vals.get("temperature")
    if t is None:
        say(f"  [{tag}] 读温度失败")
        return None
    co2 = vals.get("co2")
    ys = vals.get("y-coordinate")
    tmax = float(t.max())
    # T_axis 取 y=0 处（线点顺序不保证从 y=0 起，必须按坐标找）
    if ys is not None:
        taxis = float(t[int(np.argmin(np.abs(ys)))])
    else:
        taxis = float(t[0])
    co2max = float(co2.max()) if co2 is not None else float("nan")
    rmax = float(ys[int(np.argmax(t))] / C.D_JET) if ys is not None else float("nan")
    say(f"  [{tag}] @x/d=30: T_max={tmax:.1f} K, T_axis={taxis:.1f} K, "
        f"CO2_max={co2max:.4g}, r@Tmax={rmax:.2f}d{res_str()}")
    return tmax, taxis, co2max


def outlet_points_T(s, rd_list):
    """出口线（x = L_DOMAIN）上若干个 r/d 点的温度。

    稳态判据用：多个点各自的变化都要 < 阈值，比"单点平均"更严格。
    """
    import numpy as np
    nm = "outlet_plane"
    try:
        _ensure_line(s, nm, C.L_DOMAIN, 0.0, C.L_DOMAIN, C.R_DOMAIN)
    except Exception:                                       # noqa: BLE001
        pass
    vals = line_vals(s, nm, ["temperature", "y-coordinate"])
    t = vals.get("temperature")
    y = vals.get("y-coordinate")
    if t is None or y is None or len(t) == 0:
        return {}
    y = np.asarray(y, dtype=float)
    tt = np.asarray(t, dtype=float)
    out = {}
    for q in rd_list:
        i = int(np.argmin(np.abs(y / C.D_JET - q)))
        out[q] = float(tt[i])
    return out


def _conv_truth(node) -> object:
    """0.30.5 的 check_convergence 回读返回的是**对象**不是 bool：
    需要再取 .value（子节点）或对该对象 get_state() 拿真值。"""
    for getter in (lambda: node.value.get_state(),
                   lambda: node.value,
                   lambda: node.get_state()):
        try:
            v = getter()
            if isinstance(v, bool):
                return v
        except Exception:                                   # noqa: BLE001
            continue
    return "UNKNOWN"


def disable_residual_autostop(s):
    """关闭残差自动判稳（check_convergence）。

    默认开启时，iterate(N) 在残差满足绝对判据（0.001）后提前返回，
    导致"跑 N 步"实际只跑了少量步（实测 medium 3000 步只到 395 步）。
    关闭后 iterate(N) 必跑满 N 步，步数才可控。
    ★ 赋值后必须回读真值（check_convergence 回读是对象不是 bool），
      否则"关闭"可能只是没报错而已。
    """
    n_off, states = 0, {}
    try:
        eqs = s.settings.solution.monitor.residual.equations
        for name in eqs.get_state():
            try:
                eqs[name].check_convergence = False
            except Exception:                               # noqa: BLE001
                pass
            states[name] = _conv_truth(eqs[name].check_convergence)
            if states[name] is False:
                n_off += 1
    except Exception as exc:                                # noqa: BLE001
        say(f"  关闭残差判稳失败: {str(exc)[:160]}")
    say(f"  残差判稳回读: {states}")
    if n_off < len(states):
        say(f"  ★ FAIL: 仅 {n_off}/{len(states)} 个方程确认为 False，判据未关干净！")
    else:
        say(f"  已确认关闭 {n_off}/{len(states)} 个方程的残差自动判稳（回读全 False）")


def force_first_order(s):
    try:
        ds = s.settings.solution.methods.spatial_discretization.discretization_scheme
        for key in list(ds.get_state().keys()):
            if key in ("pressure",):
                continue
            try:
                ds.set_state({key: "first-order-upwind"})
            except Exception:                               # noqa: BLE001
                pass
        say(f"  离散格式: {ds.get_state()}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  force_first_order FAIL: {str(exc)[:180]}")


def set_second_order(s):
    """动量/湍流/混合分数切二阶迎风（压力保持二阶）——降低数值扩散。"""
    try:
        ds = s.settings.solution.methods.spatial_discretization.discretization_scheme
        n_ok = 0
        for key in list(ds.get_state().keys()):
            if key in ("pressure",):
                continue
            try:
                ds.set_state({key: "second-order-upwind"})
                n_ok += 1
            except Exception:                               # noqa: BLE001
                pass
        say(f"  二阶迎风切换 OK（{n_ok} 个方程）: {ds.get_state()}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  set_second_order FAIL: {str(exc)[:180]}")


def enable_pseudo_transient(s, scale=1.0):
    try:
        s.settings.solution.methods.pseudo_time_method.formulation.coupled_solver = \
            "global-time-step"
        say("  pseudo_time formulation = global-time-step")
    except Exception as exc:                                # noqa: BLE001
        say(f"  pseudo formulation FAIL: {str(exc)[:160]}")
    try:
        pts = s.settings.solution.run_calculation.pseudo_time_settings
        pts.time_step_method.time_step_method = "automatic"
        pts.time_step_method.length_scale_methods = "conservative"
        pts.time_step_method.time_step_size_scale_factor = float(scale)
        say(f"  pseudo dt: automatic/conservative scale={scale}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  pseudo_time_settings FAIL: {str(exc)[:180]}")


def set_urf(s, urf: float):
    if urf <= 0:
        return
    try:
        ctr = s.settings.solution.controls.under_relaxation
        st = {}
        for k in list(ctr.get_state().keys()):
            lk = k.lower()
            if ("energy" in lk) or ("temperature" in lk) or ("fvar" in lk):
                st[k] = urf
            elif lk in ("k", "epsilon") or ("kinetic" in lk) or ("dissipation" in lk):
                st[k] = min(0.7, urf + 0.2)
        if st:
            ctr.set_state(st)
            say(f"  URF(settings): {st}")
            return
        say(f"  URF settings API 无可控量，尝试 TUI")
    except Exception as exc:                                # noqa: BLE001
        say(f"  URF settings 不可用（{str(exc)[:90]}），尝试 TUI")
    ok, fail = [], []
    for eq in ("energy", "k", "epsilon", "fvar", "fmean"):
        try:
            s.execute_tui(f"/solve/set/under-relaxation/{eq} {urf}")
            ok.append(eq)
        except Exception:                                   # noqa: BLE001
            fail.append(eq)
    say(f"  URF(TUI) urf={urf}: 成功={ok} 失败={fail}")


def collect_profiles(s, verbose: bool = True) -> list[dict]:
    rows: list[dict] = []
    d = C.D_JET
    for xd in X_RAD:
        nm2 = f"r{str(xd).replace('.', 'p')}"
        try:
            s.tui.surface.line_surface(nm2, xd * d, 0.0, xd * d, C.R_DOMAIN)
        except Exception as exc:                            # noqa: BLE001
            say(f"  x/d={xd}: 建线失败 {str(exc)[:120]}")
            continue
        vals = line_vals(s, nm2, FIELDS + ["x-coordinate", "y-coordinate"])
        ys = vals.get("y-coordinate")
        xs = vals.get("x-coordinate")
        if ys is None:
            continue
        n = len(ys)
        if verbose:
            say(f"  x/d={xd:>5}: n={n} r/d∈[{ys.min() / d:.2f},{ys.max() / d:.2f}] "
                f"T∈[{vals['temperature'].min():.0f},{vals['temperature'].max():.0f}] K")
        for i in range(n):
            rec = {"profile": "radial", "x_over_d": xd, "r_over_d": ys[i] / d,
                   "x_m": float(xs[i]) if xs is not None else xd * d,
                   "y_m": float(ys[i])}
            for f in FIELDS:
                if f in vals and i < len(vals[f]):
                    rec[f] = float(vals[f][i])
            rows.append(rec)
    try:
        s.tui.surface.line_surface("cl", 0.0, 0.0, C.L_DOMAIN, 0.0)
        vals = line_vals(s, "cl", FIELDS + ["x-coordinate"])
        xs = vals.get("x-coordinate")
        if xs is not None:
            for i in range(len(xs)):
                rec = {"profile": "centerline", "x_over_d": xs[i] / d,
                       "r_over_d": 0.0, "x_m": float(xs[i]), "y_m": 0.0}
                for f in FIELDS:
                    if f in vals and i < len(vals[f]):
                        rec[f] = float(vals[f][i])
                rows.append(rec)
            if verbose:
                say(f"  中心线: n={len(xs)}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  中心线失败: {str(exc)[:150]}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=str(RUN / "np_eq_seed.cas.h5"))
    ap.add_argument("--n-iter", type=int, default=1500)
    ap.add_argument("--chunk", type=int, default=100)
    ap.add_argument("--min-steps", type=int, default=0,
                    help="早停前至少跑的步数（防 T_max 假平台导致早停）")
    ap.add_argument("--conv-tol", type=float, default=1e-3,
                    help="稳态判据：各点温度的相对变化阈值（0.1%% = 1e-3）")
    ap.add_argument("--out-pts", default="0,2,4,6,8,10,15,20,30",
                    help="出口线上取样点的 r/d 列表（逗号分隔）")
    ap.add_argument("--cores", type=int, default=10)
    ap.add_argument("--urf", type=float, default=0.5)
    ap.add_argument("--pseudo-scale", type=float, default=0.5)
    ap.add_argument("--tag", default="np_eq_d_v5_coarse")
    ap.add_argument("--mesh-msh", default="",
                    help="用 replace_mesh 换网格（保留非预混设置），如 mesh/v5/medium.msh")
    ap.add_argument("--resume", default="",
                    help="从既有解续算：给上一轮的 tag（如 np_eq_d_v5_medium_full3k），"
                         "读取其 case+data 后跳过换网格/初始化，直接继续迭代")
    ap.add_argument("--planar", action="store_true",
                    help="关闭轴对称（平面 2D 测试）：axis-8 改 symmetry，"
                         "two_dim_space=planar；配合 --resume 从轴对称解出发松弛到平面解")
    ap.add_argument("--pdf", default="",
                    help="PDF 查询表文件名（run/ 下，默认 np_eq_seed.pdf；"
                         "全域平面用 planar_seed.pdf）")
    ap.add_argument("--so-step", type=int, default=0,
                    help="在该步数后把动量/湍流/混合分数切二阶迎风（0=全程一阶）")
    ap.add_argument("--so-at-start", action="store_true",
                    help="启动即切二阶（前台分段接力的第 2+ 段用），"
                         "跳过 force_first_order 与切换延时")
    ap.add_argument("--autosave-every", type=int, default=0,
                    help="每 N 步自动 write_data 到 <tag>_as.dat.h5"
                         "（进程被外部击杀时最多损失 N 步；0=关闭）")
    ap.add_argument("--resume-data", default="",
                    help="--resume 读 case 后，再用此 data 文件覆盖流场"
                         "（配合 autosave 续命，如 xxx_as.dat.h5）")
    args = ap.parse_args()

    # ★ 并行上限：不论传入多少，最多 10 核（留 2 核给系统，用户指定）
    args.cores = max(1, min(int(args.cores), 10))

    # ★ 日志/转录按 tag 分文件：避免多会话争用同一文件（PermissionError）
    global LOG, TRN
    LOG = RUN / f"log_{args.tag}.txt"
    TRN = RUN / f"trn_{args.tag}.txt"
    if LOG.exists():
        LOG.unlink()

    seed = Path(args.seed)
    if not seed.exists() and not args.resume:
        say(f"FAIL: 种子 case 不存在: {seed}")
        sys.exit(2)

    import ansys.fluent.core as pyfluent

    say("\n" + "=" * 78)
    say(time.strftime("%F %T"),
        f"flameD 非预混(Equilibrium+βPDF) baseline  seed={seed.name} "
        f"n={args.n_iter} cores={args.cores} urf={args.urf} "
        f"pseudo_scale={args.pseudo_scale}")
    say("=" * 78)

    s = pyfluent.launch_fluent(
        mode="solver", dimension=2, precision="double",
        processor_count=args.cores,
        ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    say(f"已启动 {s.get_fluent_version()}（{args.cores} 核）")
    if TRN.exists():
        TRN.unlink()
    s.transcript.start(file_name=str(TRN), write_to_stdout=False)
    time.sleep(1.0)

    if args.resume:
        # ---- 续算：读上一轮 case+data，跳过换网格与初始化 ----
        # 兼容三种写法：tag 名 / run\xxx / 绝对路径
        cand = args.resume
        cands = [Path(cand + ".cas.h5"),
                 ROOT / "run" / f"{cand}.cas.h5",
                 Path(cand),
                 ROOT / cand]
        rcase = next((c for c in cands if c.exists()), None)
        if rcase is None:
            say("FAIL: 续算文件不存在，尝试过: " + "；".join(str(c) for c in cands))
            try:
                s.exit()
            except Exception:                               # noqa: BLE001
                pass
            sys.exit(2)
        s.settings.file.read_case_data(file_name=str(rcase))
        say(f"  续算：已读 {rcase.name} + data（跳过换网格/初始化）")
        if args.resume_data:
            p = RUN / args.resume_data
            if p.exists():
                s.settings.file.read_data(file_name=str(p))
                say(f"  续算：data 覆盖自 {p.name}")
            else:
                say(f"  WARN: --resume-data 不存在，沿用原 data: {p}")
    else:
        s.file.read_case(file_name=str(seed))

        # 换网格（保持非预混模型/边界流定义不变）—— 用于网格无关性验证
        if args.mesh_msh:
            msh = ROOT / args.mesh_msh
            say(f"  替换网格 -> {msh}")
            try:
                s.settings.file.replace_mesh(file_name=str(msh))
                time.sleep(2.0)
                say("  换网格 OK（zone 拓扑需与种子 case 一致）")
            except Exception as exc:                        # noqa: BLE001
                say(f"  换网格失败: {str(exc)[:220]}")
                try:
                    s.exit()
                except Exception:                           # noqa: BLE001
                    pass
                sys.exit(5)
        say(f"种子 case 读取 OK: {seed.name}")

    opt = None
    try:
        opt = s.settings.setup.models.species.model.option.get_state()
    except Exception as exc:                                # noqa: BLE001
        say(f"  读取模型状态 FAIL: {str(exc)[:200]}")
    say(f"  species.model.option = {opt!r}")
    if opt != "non-premixed-combustion":
        say("FAIL: 种子 case 的非预混模型未激活，请重做 GUI 步骤后另存种子 case")
        try:
            s.exit()
        except Exception:                                   # noqa: BLE001
            pass
        sys.exit(3)

    bc = s.settings.setup.boundary_conditions
    # 全域平面网格的镜像入口：存在才设置（planar_seed 场景）
    planar_extra = []
    for nm in ("velocity-inlet-14", "velocity-inlet-15"):
        try:
            bc.velocity_inlet[nm].momentum.velocity.value  # 探活
            planar_extra.append(nm)
        except Exception:                                   # noqa: BLE001
            pass
    if planar_extra:
        say(f"  [planar-full] 检测到镜像入口 {planar_extra}，将同步设置")
    for k, d in INLETS.items():
        targets = [Z[k]] + [nm for nm in planar_extra
                            if nm.endswith("-14") and k == "pilot"
                            or nm.endswith("-15") and k == "coflow"]
        for tgt in targets:
            z = bc.velocity_inlet[tgt]
            z.momentum.velocity.value = d["U"]
            z.turbulence.turbulence_specification = "Intensity and Hydraulic Diameter"
            z.turbulence.turbulent_intensity = d["I"]
            z.turbulence.hydraulic_diameter = d["Dh"]
            # 绝热非预混模型不求解能量方程 → 入口的 thermal 节点 inactive，跳过
            try:
                z.thermal.temperature.value = d["T"]
                thermal_ok = True
            except Exception:                               # noqa: BLE001
                thermal_ok = False
            if not thermal_ok and k == "jet":
                say("  （绝热模式：能量方程关闭，入口热边界不适用 → 跳过温度设置）")
            # mean_mixture_fraction 是**结构化设置** {'option':'value','value':x}
            # （实测 get_state() 返回该结构）。用标量 set_state(1.0) 不报错但不生效，
            # 必须按 option/value 两级写，然后回读确认。
            f_ok = False
            for cand in ("mean_mixture_fraction", "mixture_fraction"):
                try:
                    node = getattr(z.species, cand)
                    try:
                        node.option = "value"
                        node.value = d["F"]
                    except Exception:                       # noqa: BLE001
                        node.set_state({"option": "value", "value": d["F"]})
                    back = node.get_state()
                    val = back.get("value") if isinstance(back, dict) else back
                    if val is None or abs(float(val) - d["F"]) > 1e-6:
                        say(f"  {tgt}: f 回读异常 {back} → 再试 set_state")
                        node.set_state({"option": "value", "value": d["F"]})
                        back = node.get_state()
                    say(f"  {tgt}: f={d['F']} OK（键 {cand}，回读={back}）")
                    f_ok = True
                    break
                except Exception as exc:                    # noqa: BLE001
                    last = str(exc)[:150]
            if not f_ok:
                say(f"  {tgt} f={d['F']} FAIL: {last}")
                for cand in ("mixture_fraction_variance", "variance", "pvar"):
                    try:
                        node = getattr(z.species, cand, None)
                        if node is not None:
                            try:
                                node.option = "value"
                                node.value = 0.0
                            except Exception:               # noqa: BLE001
                                node.set_state({"option": "value", "value": 0.0})
                            say(f"  {tgt}: {cand}=0 OK（回读={node.get_state()}）")
                            break
                    except Exception:                       # noqa: BLE001
                        continue
    say("入口 BC OK（速度/湍流/温度/混合分数）")

    # PDF 查询表：Write→Case **不包含**该表（Fluent 会提示 "pdf table ... has not been
    # saved to disk"），必须用 Write→PDF 单独存成 .pdf。这里用 settings API 自动读回：
    #   s.file.read_pdf(file_name=...)   ← 实测可用，读表后 hybrid_initialize() 直接通过
    pdf = ROOT / "run" / (args.pdf if args.pdf else "np_eq_seed.pdf")
    if pdf.exists():
        try:
            s.file.read_pdf(file_name=str(pdf))
            say(f"  已读入 PDF 查询表: {pdf.name} ({pdf.stat().st_size / 1e6:.1f} MB)")
        except Exception as exc:                            # noqa: BLE001
            say(f"  读 PDF 表失败: {str(exc)[:180]}")
    else:
        say(f"  WARN: 找不到 {pdf}，若 case 未内嵌表格则会初始化失败")

    if args.resume:
        say("  续算：跳过初始化（沿用 data 中的流场/温度场）")
    else:
        try:
            s.settings.solution.initialization.hybrid_initialize()
            say("  初始化 OK")
        except Exception as exc:                            # noqa: BLE001
            msg = str(exc)
            say(f"  初始化失败: {msg[:200]}")
            if "PDF" in msg:
                say("  ★ 缺 PDF 查询表。请在 GUI 里：Species → Table → Calculate PDF Table，")
                say("     然后 File → Write → PDF 存成 run/np_eq_seed.pdf（不是 Write → Case）")
            try:
                s.exit()
            except Exception:                               # noqa: BLE001
                pass
            sys.exit(4)
        core_T(s, "初始化")

    if args.so_at_start:
        say("  [so-at-start] 接力模式：启动即二阶，跳过一阶强制")
        set_second_order(s)
    else:
        force_first_order(s)
    enable_pseudo_transient(s, scale=args.pseudo_scale)
    set_urf(s, args.urf)
    disable_residual_autostop(s)

    if args.planar:
        say("  [planar] axis-8 → symmetry（平面 2D 不允许 axis 边界）")
        s.execute_tui("/mesh/modify-zones/zone-type axis-8 symmetry")
        gone = False
        for _ in range(10):                             # 状态更新可能有延迟
            time.sleep(1.0)
            try:
                ax = bc.axis.get_state()
                gone = not (isinstance(ax, dict) and "axis-8" in ax)
            except Exception:                           # 组已 inactive = 成功
                gone = True
            if gone:
                break
        if gone:
            say("  [planar] axis-8 → symmetry OK")
        else:
            say("  [planar] FAIL: axis-8 未切换成功，平面模式无效，退出")
            try:
                s.exit()
            except Exception:                           # noqa: BLE001
                pass
            sys.exit(6)
        s.settings.setup.general.solver.two_dim_space = "planar"
        say(f"  [planar] two_dim_space = "
            f"{s.settings.setup.general.solver.two_dim_space.get_state()}")
        say("  [planar] 注意：平面射流铺展规律与圆射流不同，结果用于检验轴对称假设的影响")

    rd_pts = [float(x) for x in str(args.out_pts).split(",") if x.strip()]
    conv_tol = args.conv_tol
    say(f"\n>>> 主迭代 {args.n_iter} 步（稳态判据：出口线 r/d={rd_pts} 共 {len(rd_pts)} 点"
        f" + T_max@x/d=30（峰区），各相对变化 < {conv_tol*100:g}%）")
    done = 0
    hist = {}                                       # {r/d: [T,...]} 出口 9 点
    hist_core: list = []                            # T_max@x/d=30（峰区，收敛最慢）
    so_switched = (args.so_step <= 0) or args.so_at_start
    t0 = time.time()
    while done < args.n_iter:
        n = min(args.chunk, args.n_iter - done)
        if (not so_switched) and done >= args.so_step:
            set_second_order(s)
            so_switched = True
        s.settings.solution.run_calculation.iterate(iter_count=n)
        done += n
        if args.autosave_every > 0 and done % args.autosave_every == 0:
            try:
                s.settings.file.write_data(
                    file_name=str(RUN / f"{args.tag}_as.dat.h5"))
                say(f"  [autosave] {done} 步 → {args.tag}_as.dat.h5")
            except Exception as exc:                        # noqa: BLE001
                say(f"  [autosave] FAIL: {str(exc)[:120]}")
        r = core_T(s, f"迭代 {done}/{args.n_iter}")
        pT = outlet_points_T(s, rd_pts)
        for q, v in pT.items():
            hist.setdefault(q, []).append(v)
        if r is not None:
            hist_core.append(float(r[0]))

        # 稳态判据：出口 9 点 + 峰区 T_max，每条序列最近 3 次采样相对变化都 < conv_tol
        series = list(hist.items())
        if hist_core:
            series.append(("Tmax@x30", hist_core))
        if series and done >= args.min_steps:
            ok = True
            maxrel, worst = 0.0, None
            for q, h in series:
                if len(h) < 3:
                    ok = False
                    continue
                w = h[-min(3, len(h)):]
                span = max(w) - min(w)
                mean = abs(sum(w) / len(w))
                rel = span / max(mean, 1e-9)
                if rel > maxrel:
                    maxrel, worst = rel, q
                if rel >= conv_tol:
                    ok = False
            if len(hist) < len(rd_pts):
                ok = False
            if ok:
                say(f"  ** 稳态：出口 {len(hist)} 点 + 峰区 T_max 最近 3 次采样全部相对变化 "
                    f"< {conv_tol*100:g}%（最大 {maxrel*100:.3f}% @ {worst}），"
                    f"已跑 {done} 步")
                break
            wtxt = f"{worst}" if worst is not None else "样本不足"
            say(f"     [稳态未达：{len(hist)} 点+Tmax，最大相对变化 {maxrel*100:.2f}% "
                f"@ {wtxt}，已跑 {done} 步]")
    dt = time.time() - t0
    say(f"  用时 {dt:.0f}s ({dt / max(done, 1):.3f} s/步) done={done}")

    r = core_T(s, "最终")
    ok = bool(r and r[0] > 1500.0 and r[2] > 0.05)
    say(f"\n>>> 判定：{'**火焰建立**' if ok else '**未建立/异常**'} "
        f"(T_max>1500 且 CO2_max>0.05 @x/d=30)")

    out = RUN / f"{args.tag}.cas.h5"
    dat = RUN / f"{args.tag}.dat.h5"
    try:
        s.settings.file.write_case(file_name=str(out))
        s.settings.file.write_data(file_name=str(dat))
        say(f"  已存 {out.name} / {dat.name}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  存 case/dat 失败: {str(exc)[:200]}")

    say("\n>>> 导出剖面对标")
    rows = collect_profiles(s)
    dst = ROOT / "results" / f"cfd_{args.tag}.csv"
    cols = ["profile", "x_over_d", "r_over_d", "x_m", "y_m"] + FIELDS
    with dst.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for rec in rows:
            w.writerow(rec)
    say(f"  已写 {dst} ({len(rows)} 行)")

    try:
        s.transcript.stop()
    except Exception:                                       # noqa: BLE001
        pass
    try:
        s.exit()
    except Exception:                                       # noqa: BLE001
        pass
    say("\n完成")


if __name__ == "__main__":
    main()
