"""生成 flameD 三个入口的 Fluent profile 文件与 CSV 汇总。

速度剖面取自 SandiaPilotDoc21.pdf §VELOCITY BOUNDARY CONDITIONS 的
TUD 实测剖面（r/D, <U>, <u'u'> 表），Release 2.1 现行版本。

湍流入口量：按面积加权把实测 <u'u'> 折算成湍流强度 I，
再交给 Fluent 用 "Intensity and Hydraulic Diameter" 方式给定，
避免在 2D profile 中同时携带 k/epsilon 带来的格式风险。
"""
from __future__ import annotations

import math

import flamed_common as C

# TUD 实测剖面： (r/D, <U> m/s, <u'u'> m^2/s^2)
TUD_PROFILE = [
    (0.0000, 62.95, 6.13),
    (0.0694, 62.54, 6.23),
    (0.1388, 61.36, 8.27),
    (0.2083, 59.21, 12.45),
    (0.2777, 56.73, 15.93),
    (0.3472, 53.34, 20.66),
    (0.4166, 48.80, 24.50),
    (0.4861, 41.99, 37.40),
    (0.5000, 0.00, 0.00),
    (0.5555, 3.45, 0.322),
    (0.6250, 11.46, 1.736),
    (0.6944, 15.18, 1.484),
    (0.7638, 15.45, 1.586),
    (0.8333, 15.15, 1.797),
    (0.9027, 15.97, 1.360),
    (0.9722, 15.56, 1.476),
    (1.0416, 15.42, 1.410),
    (1.1111, 15.04, 1.546),
    (1.1805, 14.25, 1.875),
    (1.2300, 10.96, 1.508),
    (1.2400, 0.00, 0.000),
    (1.3194, 1.04, 0.009),
    (1.3888, 1.01, 0.007),
    (1.4583, 1.07, 0.007),
    (2.1041, 1.02, 0.006),
]

CMU = 0.09


def _integrate(rows, r_lo, r_hi):
    """对表格在 [r_lo, r_hi] (单位 r/D) 上做面积加权积分。"""
    n = 4000
    d = (r_hi - r_lo) / n
    sum_u = sum_uu = sum_a = 0.0
    for k in range(n):
        rc = r_lo + (k + 0.5) * d
        # 线性插值
        u = uu = 0.0
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            if a[0] <= rc <= b[0] and b[0] > a[0]:
                t = (rc - a[0]) / (b[0] - a[0])
                u = a[1] + t * (b[1] - a[1])
                uu = a[2] + t * (b[2] - a[2])
                break
        a_ring = rc * d                     # 面积权重 ~ r dr
        sum_u += u * a_ring
        sum_uu += uu * a_ring
        sum_a += a_ring
    return sum_u / sum_a, sum_uu / sum_a


def _write_prof(path, name, points, fields):
    """写 Fluent profile 文件。points: [(val_field0, val_field1, ...)]"""
    with path.open("w", encoding="ascii") as fh:
        fh.write(f"(({name} point {len(points)})\n")
        for p in points:
            for fi, val in zip(fields, p):
                fh.write(f" ({fi} {val:.6e})\n")
        fh.write(")\n")


def main():
    C.DIR_PROF.mkdir(parents=True, exist_ok=True)
    rows = TUD_PROFILE

    # ---- 主射流：面积加权校验与湍流强度
    u_jet, uu_jet = _integrate(rows, 0.0, 0.5)
    i_jet = math.sqrt(max(uu_jet, 0.0)) / u_jet
    scale = C.U_JET_BULK / u_jet
    print("=== 主射流 (TUD 实测剖面, 0 <= r/D <= 0.5) ===")
    print(f"  剖面面积加权体均 U_bulk = {u_jet:.2f} m/s")
    print(f"  文档 [DOC] 体均 = {C.U_JET_BULK} m/s (Re={C.RE_D:.0f})")
    print(f"  -> 归一化系数 {scale:.4f}，使入口质量流量与文档一致")
    print(f"  面积加权 <u'u'> = {uu_jet:.2f} m^2/s^2 -> u' = {math.sqrt(uu_jet):.2f} m/s")
    print(f"  湍流强度 I = {i_jet*100:.1f} %   水力直径 D_h = 7.2 mm")

    # 速度剖面点：只到 r/D = 0.5（射流出口壁面），并归一到文档体均速度
    # 表中坐标为 r/D，故 r = (r/D) * D_JET
    pts = [(rd * C.D_JET, u * scale) for (rd, u, _uu) in rows if rd <= 0.5]
    _write_prof(C.DIR_PROF / "jet.prof", "jet-axial-velocity",
                pts, ["y", "u"])
    print(f"  写出 profiles/jet.prof  ({len(pts)} 点, "
          f"y 覆盖 0 -> {pts[-1][0]*1e3:.2f} mm)")

    # 均匀速度备选
    _write_prof(C.DIR_PROF / "jet_uniform.prof", "jet-uniform-axial-velocity",
                [(0.0, C.U_JET_BULK), (C.R_JET, C.U_JET_BULK)], ["y", "u"])
    print("  写出 profiles/jet_uniform.prof (均匀 49.6 m/s 备选)")

    # ---- pilot：均匀，湍流强度由实测平台区 u' 估算
    u_pilot_meas, uu_pilot = _integrate(rows, 0.6944, 1.1805)
    i_pilot = math.sqrt(max(uu_pilot, 0.0)) / C.U_PILOT_BULK
    dh_pilot = C.PILOT_OD - C.PILOT_ID
    print("=== pilot 环 ===")
    print(f"  实测平台区速度 {u_pilot_meas:.2f} m/s；模型边界条件取体均 [DOC] {C.U_PILOT_BULK} m/s")
    print(f"  实测 u' = {math.sqrt(uu_pilot):.2f} m/s -> 相对体均的 I = {i_pilot*100:.1f} %")
    print(f"  水力直径 D_h = {dh_pilot*1e3:.1f} mm")

    # ---- 伴流
    i_cfl = 0.01                             # [DOC] 假定自由流湍流强度 1%
    print("=== 伴流 ===")
    print(f"  U = {C.U_COFLOW} m/s, I = {i_cfl*100:.1f} % [DOC], D_h = 300 mm")

    # ---- 汇总 CSV（供报告与后续脚本引用）
    with (C.DIR_RESULTS / "inlet_conditions.csv").open("w", encoding="utf-8") as fh:
        fh.write("inlet,U[m/s],I[%],D_h[mm],T[K],note\n")
        fh.write(f"inlet-jet,{C.U_JET_BULK},{i_jet*100:.2f},{C.D_JET*1e3:.1f},{C.T_JET},"
                 f"TUD 实测剖面 + I 面积加权\n")
        fh.write(f"inlet-pilot,{C.U_PILOT_BULK},{i_pilot*100:.2f},{dh_pilot*1e3:.1f},{C.T_PILOT},"
                 f"均匀(体均), 实测平台 15.2 m/s 见灵敏度对照\n")
        fh.write(f"inlet-coflow,{C.U_COFLOW},{i_cfl*100:.2f},300.0,{C.T_COFLOW},"
                 f"均匀, I 文档假定 1%\n")
    print("写出 results/inlet_conditions.csv")

    # ---- 组分质量分数（供 boundary-conditions 使用）
    with (C.DIR_RESULTS / "inlet_composition.csv").open("w", encoding="utf-8") as fh:
        fh.write("species,inlet-jet,inlet-pilot,inlet-coflow\n")
        for sp in C.SPECIES:
            fh.write(f"{sp},{C.Y_JET.get(sp,0):.6f},{C.Y_PILOT.get(sp,0):.6f},"
                     f"{C.Y_COFLOW.get(sp,0):.6f}\n")
        s_jet = sum(C.Y_JET.values())
        s_pilot = sum(C.Y_PILOT.values())
        s_cf = sum(C.Y_COFLOW.values())
        fh.write(f"SUM,{s_jet:.6f},{s_pilot:.6f},{s_cf:.6f}\n")
    print("写出 results/inlet_composition.csv")
    print(f"  质量分数合计校验: jet {sum(C.Y_JET.values()):.5f}  "
          f"pilot {sum(C.Y_PILOT.values()):.5f}  coflow {sum(C.Y_COFLOW.values()):.5f}")


if __name__ == "__main__":
    main()
