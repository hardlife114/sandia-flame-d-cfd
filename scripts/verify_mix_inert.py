"""验证 run_box3d_mix 解是否真的是「惰性混合」（无反应）。

问题背景：设置阶段 `volumetric reactions` 状态回读返回 None（回读路径不对），
所以必须**独立验证**，否则整个对照实验无效。

判据（两条独立证据）
 ① 模型层：尝试多条路径回读 Fluent 内部的 reaction 开关状态。
 ② 物理层（决定性）：**CH4 消耗检验**
    惰性混合下 CH4 只能来自射流，故  Y_CH4 = 0.15637 · w_jet 。
    w_jet 由**元素守恒**反解（元素质量分数与反应无关，是真正的守恒标量）：
      用 (Y_C, Y_H) + 归一化解出 w_jet/w_pilot/w_coflow，
      再预测 Y_CH4_pred = 0.15637·w_jet 与实测比较。
    若 实测 ≈ 预测  → 惰性，实验有效
    若 实测 ≪ 预测  → CH4 被消耗，反应**未关闭**，实验无效

用法: python scripts/verify_mix_inert.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["AWP_ROOT252"] = r"D:\Program Files\ANSYS\2025R2\v252"
os.environ.setdefault("FLUENT_AUTOMATIC_TRANSCRIPT", "0")

RUN = ROOT / "run"
LOG = RUN / "verify_mix_inert.log"
CASE = RUN / "box3d_mix.cas.h5"

WC, WH, WO = 12.011, 1.008, 15.999
WCH4, WO2, WCO2, WH2O, WCO, WN2 = 16.043, 31.998, 44.009, 18.015, 28.010, 28.014

# 各组分中的元素质量分数
F_C = {"ch4": 4 * WC / WCH4, "co": WC / WCO, "co2": WC / WCO2}
F_H = {"ch4": 4 * WH / WCH4, "h2o": 2 * WH / WH2O}
F_O = {"o2": 2 * WO / WO2, "co2": 2 * WO / WCO2, "h2o": WO / WH2O, "co": WO / WCO}

# 三股流的元素质量分数（由进口组分算出）
STREAM = {
    "jet":    {"C": 0.15637 * 4 * WC / WCH4,
               "H": 0.15637 * 4 * WH / WCH4,
               "O": 0.19650 * 2 * WO / WO2},
    "pilot":  {"C": 0.1098 * WC / WCO2 + 0.00407 * WC / WCO,
               "H": 0.0942 * 2 * WH / WH2O,
               "O": 0.054 * 2 * WO / WO2 + 0.1098 * 2 * WO / WCO2
                    + 0.0942 * WO / WH2O + 0.00407 * WO / WCO},
    "coflow": {"C": 0.0,
               "H": 0.006256 * 2 * WH / WH2O,
               "O": 0.23574 * 2 * WO / WO2 + 0.006256 * WO / WH2O},
}
Y_CH4_JET = 0.15637


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    if LOG.exists():
        LOG.unlink()
    say("=" * 78)
    say(time.strftime("%F %T"), "验证 box3d_mix 是否真为惰性混合")
    say("=" * 78)

    import ansys.fluent.core as pyfluent

    s = pyfluent.launch_fluent(
        mode="solver", dimension=3, precision="double", processor_count=4,
        ui_mode="no_gui", start_transcript=False,
        start_watchdog=False, cleanup_on_exit=True,
    )
    s.settings.file.read_case_data(file_name=str(CASE))
    say(f"已读 {CASE.name}")

    say("\n【① 模型层：回读反应开关】")
    for path in ("setup/models/species/reactions",
                 "setup/models/species/volumetric_reactions",
                 "setup/models/species/reaction",
                 "setup/models/species/options/volumetric_reactions",
                 "setup/models/species/turb_chem_interaction"):
        try:
            v = s.settings.get_var(path)
            say(f"  {path} = {v!r}")
        except Exception as exc:                            # noqa: BLE001
            say(f"  {path}: <{str(exc)[:70]}>")
    try:
        say(f"  species.model.option = "
            f"{s.settings.setup.models.species.model.option.get_state()!r}")
    except Exception as exc:                                # noqa: BLE001
        say(f"  model.option: <{str(exc)[:70]}>")
    # TUI 查询（返回当前布尔值）
    for cmd in ("/define/models/species/volumetric-reactions?",
                "/define/models/species/reactions?"):
        try:
            r = s.execute_tui(cmd)
            say(f"  TUI {cmd} -> {str(r)[:200]}")
        except Exception as exc:                            # noqa: BLE001
            say(f"  TUI {cmd} FAIL: {str(exc)[:90]}")

    say("\n【② 物理层：CH4 消耗检验（决定性）】")
    say("  三股流元素质量分数：")
    for k, v in STREAM.items():
        say(f"    {k:<8} C={v['C']:.5f}  H={v['H']:.5f}  O={v['O']:.5f}")

    fields = ["ch4", "o2", "co2", "h2o", "co", "n2", "y-coordinate"]
    fd = s.fields.field_data
    ls = s.settings.results.surfaces.line_surface

    def sample(name, p0, p1):
        ls.create(name=name)
        ls[name] = {"p0": p0, "p1": p1}
        got = {}
        for f in fields:
            v = fd.get_scalar_field_data(field_name=f, surfaces=[name],
                                         node_value=True)
            got[f] = np.asarray(list(v.values())[0], dtype=float).ravel()
        return got

    say(f"\n  {'站':<10}{'Y_CH4实':>11}{'Y_CH4预':>11}{'比值':>9}"
        f"{'Y_O2实':>11}{'Y_O2预':>11}{'比值':>9}")
    for xd in (15, 30, 45, 60):
        x0 = xd * 0.0072
        g = sample(f"mx{xd}", [x0, 0.0, 0.0], [x0, 0.0432, 0.0])
        ys = g["y-coordinate"]
        i0 = int(np.argmin(np.abs(ys)))
        Yc = sum(coef * g[sp][i0] for sp, coef in F_C.items())
        Yh = sum(coef * g[sp][i0] for sp, coef in F_H.items())
        Yo = sum(coef * g[sp][i0] for sp, coef in F_O.items())
        # 解 w：Y_C = Σ w_i C_i, Y_H = Σ w_i H_i, Σ w_i = 1
        A = np.array([[STREAM["jet"]["C"], STREAM["pilot"]["C"], STREAM["coflow"]["C"]],
                      [STREAM["jet"]["H"], STREAM["pilot"]["H"], STREAM["coflow"]["H"]],
                      [1.0, 1.0, 1.0]])
        b = np.array([Yc, Yh, 1.0])
        try:
            w = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            say(f"  x/d={xd}: 元素矩阵奇异")
            continue
        wj, wp, wc = w
        pred_ch4 = Y_CH4_JET * wj
        pred_o2 = 0.19650 * wj + 0.054 * wp + 0.23574 * wc
        act_ch4, act_o2 = float(g["ch4"][i0]), float(g["o2"][i0])
        say(f"  {'x/d='+str(xd):<10}{act_ch4:>11.5f}{pred_ch4:>11.5f}"
            f"{(act_ch4/pred_ch4 if pred_ch4 > 1e-9 else float('nan')):>9.3f}"
            f"{act_o2:>11.5f}{pred_o2:>11.5f}"
            f"{(act_o2/pred_o2 if pred_o2 > 1e-9 else float('nan')):>9.3f}")
    say("\n  判据：比值 ≈ 1.0（如 0.9~1.1）→ 惰性混合有效；≪1 → CH4/O2 被消耗，反应未关")
    say(f"  元素反解权重合理性：w 应 ≥ 0 且和为 1（上面已用归一化约束求解）")

    try:
        s.exit()
    except Exception:                                       # noqa: BLE001
        pass
    say("\nverify_mix_inert 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
