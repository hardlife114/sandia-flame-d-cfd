"""长方体通道 3D 六面体网格（用户指定：底面进口 / 顶面出口 / 四周壁面 / 火焰区加密）。

几何（与已验证的平面 2D 网格同源，保证可比性）：
  x ∈ [0, 720mm]   轴向（进口面 x=0 → 出口面 x=720）
  y ∈ [-216, 216]  横向 1（沿用 v5 径向分段，火焰带 |y|≤9.45mm 加密）
  z ∈ [-216, 216]  横向 2（自定义对称分段：近壁边界层加密 + 中心渐粗）

进口面分区（按 |y|，沿 z 全宽 = 平面条带语义）：
  inlet-jet    |y| ≤ 3.6mm        （燃料，7.2mm 条带）
  inlet-pilot  3.6 < |y| ≤ 9.1mm  （稳燃环带）
  inlet-coflow 其余                （伴流/氧化剂）

★ legacy ASCII 3D 格式（本日实测破解，run/probe_hex_format.log）：
  (2 3)；(10 (0 1 N 0 3))；(12 (1 1 M 1 0)) + 每单元整数 4（hex）；
  (13 (zone first last type **4**)) ← 末位 = **面的节点数**（不是维度！写 3 会
  被按三角面解析 → interior 0 个 → invalid grid）；面行 6 列 n1 n2 n3 n4 c0 c1。

用法：python scripts/gen_mesh_box3d.py --level coarse [--out ...]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import flamed_common as C           # noqa: E402
from gen_mesh import build_axis     # noqa: E402

hx = lambda v: format(v, "x")                              # noqa: E731
FT_INTERIOR, FT_WALL, FT_PRESSURE_OUTLET, FT_VELOCITY_INLET = 2, 3, 5, 10
FT_SYMMETRY = 7

# ★ 实验伴流半径（Sandia Flame D：伴流喷口直径 300 mm）
R_COFLOW = 0.150

# z 向分段（每半，mm）：近壁 4mm 起，几何渐张到中心 96mm（中心 z 梯度≈0，粗可接受）
Z_HALF_MM = [4.0, 8.0, 16.0, 32.0, 60.0, 96.0]

# ---- 紧凑规格（--compact）：目标 < 1.0M 单元，保反应区、粗化外围 ----
# 反应区（|y|≤45mm 火焰带 + x≤200mm 发展区）与 v5 coarse 完全一致；
# 粗化：coflow 外围（|y|>45mm）、下游（x>200mm）、z 向 12→8 段。
X_COMPACT = [
    {"a": 0.0,      "b": 30e-3,   "d0": 0.3000e-3, "d1": 0.3000e-3},  # 反应区（保持）
    {"a": 30e-3,    "b": 80e-3,   "d0": None,      "d1": 0.87180e-3}, # 火焰轴向（保持）
    {"a": 80e-3,    "b": 200e-3,  "d0": None,      "d1": 2.00000e-3}, # 发展区（保持）
    {"a": 200e-3,   "b": 400e-3,  "d0": None,      "d1": 12.0000e-3}, # 粗化
    {"a": 400e-3,   "b": C.L_DOMAIN, "d0": None,   "d1": 28.0000e-3}, # 粗化
]
Y_COMPACT = [
    {"a": 0.0,            "b": C.R_JET,        "d0": 0.1600e-3, "d1": 0.1600e-3},  # 保持
    {"a": C.R_JET,        "b": C.R_PILOT_IN,   "d0": 0.1250e-3, "d1": 0.1250e-3},  # 唇
    {"a": C.R_PILOT_IN,   "b": C.R_PILOT_OUT,  "d0": None,      "d1": 0.1726e-3},  # pilot
    {"a": C.R_PILOT_OUT,  "b": C.R_BURNER_OUT, "d0": 0.1750e-3, "d1": 0.1750e-3},  # 外唇
    {"a": C.R_BURNER_OUT, "b": 45e-3,          "d0": None,      "d1": 0.34870e-3},  # ★火焰带（保持）
    {"a": 45e-3,          "b": 100e-3,         "d0": None,      "d1": 7.00000e-3},  # 粗化
    {"a": 100e-3,         "b": C.R_DOMAIN,     "d0": None,      "d1": 22.0000e-3},  # 粗化
]
# z 向 6 段（每半 3）：反应区 z 梯度≈0，是最高效的压缩杠杆
Z_HALF_MM_COMPACT = [8.0, 55.0, 153.0]

# face zone 计划（顺序稳定，便于 BC 设置）
PZ = {
    3:  (FT_VELOCITY_INLET, "inlet-jet"),
    4:  (FT_VELOCITY_INLET, "inlet-pilot"),
    5:  (FT_VELOCITY_INLET, "inlet-coflow"),
    6:  (FT_PRESSURE_OUTLET, "outlet"),
    7:  (FT_WALL, "wall-y-minus"),
    8:  (FT_WALL, "wall-y-plus"),
    9:  (FT_WALL, "wall-z-minus"),
    10: (FT_WALL, "wall-z-plus"),
}

# ★ 圆形进口（严格对标实验）：按到中心半径 r=√(y²+z²) 分区
#   jet r≤3.6mm ｜ pilot 3.6<r≤9.1mm ｜ coflow 9.1<r≤150mm ｜ 空气 r>150mm
PZ_ROUND = dict(PZ)
PZ_ROUND[11] = (FT_VELOCITY_INLET, "inlet-air")

# ★ 1/4 域（y=0、z=0 为 symmetry，外侧仍是 wall）
PZ_QUARTER = {
    3:  (FT_VELOCITY_INLET, "inlet-jet"),
    4:  (FT_VELOCITY_INLET, "inlet-pilot"),
    5:  (FT_VELOCITY_INLET, "inlet-coflow"),
    11: (FT_VELOCITY_INLET, "inlet-air"),
    6:  (FT_PRESSURE_OUTLET, "outlet"),
    7:  (FT_SYMMETRY, "sym-y0"),
    8:  (FT_WALL, "wall-y-plus"),
    9:  (FT_SYMMETRY, "sym-z0"),
    10: (FT_WALL, "wall-z-plus"),
}

# z 向渐变规格（圆形进口必需：轴线附近 Δz≈0.5mm 才能分辨 7.2mm 的圆射流）
Z_HALF_SPEC_ROUND = [
    {"a": 0.0, "b": 15e-3, "d0": 0.50e-3, "d1": 1.00e-3},
    {"a": 15e-3, "b": 60e-3, "d0": None, "d1": 9.90e-3},
    {"a": 60e-3, "b": C.R_DOMAIN, "d0": None, "d1": 9.90e-3},
]

# ---------------- ★ 百万单元预算版（--tight）：目标 ≤ 1.0M ----------------
# 思路：细网格只留给"喷口 + 火焰核心"，外围一律拉到 10mm 上限
X_TIGHT = [
    {"a": 0.0, "b": 30e-3, "d0": 0.60e-3, "d1": 0.60e-3},   # 喷口/点火区
    {"a": 30e-3, "b": 100e-3, "d0": None, "d1": 2.00e-3},    # 火焰轴向
    {"a": 100e-3, "b": 300e-3, "d0": None, "d1": 6.00e-3},   # 发展区
    {"a": 300e-3, "b": C.L_DOMAIN, "d0": None, "d1": 9.90e-3},
]
# ★ 用**等间距子段**而非几何渐变：渐变段在几何反解时首层会被压到 0.5mm 以下
#   （实测 0.467/0.487mm，违反下限），等间距段可精确守住 [0.5, 10] mm。
YZ_TIGHT_ROUND = [
    {"a": 0.0, "b": 7e-3, "d0": 0.50e-3, "d1": 0.50e-3},      # 射流核心 0.5mm
    {"a": 7e-3, "b": 12e-3, "d0": 1.00e-3, "d1": 1.00e-3},    # 火焰近场
    {"a": 12e-3, "b": 20e-3, "d0": 2.00e-3, "d1": 2.00e-3},
    {"a": 20e-3, "b": 30e-3, "d0": 5.00e-3, "d1": 5.00e-3},
    {"a": 30e-3, "b": C.R_DOMAIN, "d0": 9.90e-3, "d1": 9.90e-3},  # 外围
]
# 百万预算下的全域 x 规格（尽量省：仅喷口区细，其余迅速拉到上限）
X_TIGHT_FULL = [
    {"a": 0.0, "b": 30e-3, "d0": 0.75e-3, "d1": 0.75e-3},
    {"a": 30e-3, "b": 120e-3, "d0": None, "d1": 9.90e-3},
    {"a": 120e-3, "b": C.L_DOMAIN, "d0": None, "d1": 9.90e-3},
]


def yz_spec(half: float) -> list:
    """按**半域宽度**生成横向等间距子段规格。

    ★ 域缩到实验风洞尺寸（半域 150mm）后，省下的单元还给火焰核心区：
      0.5mm 细区 7→8mm、1mm 区 12→16mm、2.5mm 区 20→30mm。
    """
    b4 = min(30e-3, half * 0.85)
    segs = [
        {"a": 0.0, "b": 8e-3, "d0": 0.50e-3, "d1": 0.50e-3},
        {"a": 8e-3, "b": 16e-3, "d0": 1.00e-3, "d1": 1.00e-3},
        {"a": 16e-3, "b": b4, "d0": 2.50e-3, "d1": 2.50e-3},
    ]
    if half > b4 + 1e-9:
        segs.append({"a": b4, "b": half, "d0": 9.90e-3, "d1": 9.90e-3})
    return segs


def clamp_specs(segs: list, dmin: float | None = None,
                dmax: float | None = None) -> list:
    """把段规格的目标间距限制到 [dmin, dmax]，并合并短于 dmin 的薄段。

    ★ 不能只做 clamp：唇口只有 0.25/0.35 mm，短于 dmin 时会被切成 1 个仍小于
      dmin 的单元 → 必须**并入相邻段**（0.5mm 分辨率下唇口本就无法分辨）。
    """
    out = []
    for s in segs:
        d = dict(s)
        for k in ("d0", "d1"):
            v = d.get(k)
            if v is None:
                continue
            if dmin:
                v = max(v, dmin)
            if dmax:
                v = min(v, dmax)
            d[k] = v
        out.append(d)
    if not dmin:
        return out
    merged, i = [], 0
    while i < len(out):
        a = out[i]["a"]
        j = i
        while (out[j]["b"] - a) < dmin and j + 1 < len(out):
            j += 1
        d = dict(out[j])
        d["a"] = a
        merged.append(d)
        i = j + 1
    return merged


def build_z_axis(half_mm=None, dmax: float | None = None,
                 spec: list | None = None) -> list[float]:
    """对称 z 坐标（m）：[-R..-d, 0, d..R]（纯 Python，零依赖）

    dmax：若给出，按 ≤ dmax 的**均匀**间距铺满半域（段表 half_mm 被忽略）。
    spec：若给出（dict 段表），用 build_axis 生成**渐变**半轴（圆形进口用）。
    """
    if spec:
        return build_axis(spec, 1.0)
    if dmax:
        R_mm = C.R_DOMAIN * 1e3
        n = max(1, int(-(-R_mm // dmax)))          # ceil
        half_mm = [R_mm / n] * n
    segs = half_mm if half_mm is not None else Z_HALF_MM
    half = [0.0]
    for d in segs:
        half.append(half[-1] + d)
    assert abs(half[-1] - C.R_DOMAIN * 1e3) < 0.5, \
        f"z 半轴和 {half[-1]} mm ≠ {C.R_DOMAIN*1e3}"
    neg = [-v for v in half[1:][::-1]]
    return [v * 1e-3 for v in (neg + half)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="coarse", choices=["coarse", "medium", "fine"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--compact", action="store_true",
                    help="紧凑规格（<1.0M 单元）：保反应区，粗化外围/下游，z 6 段")
    ap.add_argument("--refine", type=float, default=1.0,
                    help="★ GCI 用：统一缩放全部段间距（含 z），间距÷refine")
    ap.add_argument("--dmin", type=float, default=None,
                    help="最小单元尺寸下限 [mm]（小于此的目标间距被抬高，"
                         "并合并短于此的薄段）")
    ap.add_argument("--dmax", type=float, default=None,
                    help="最大单元尺寸上限 [mm]（含 z 向：按 ≤dmax 均匀铺满）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只统计单元数与尺寸，不写网格文件")
    ap.add_argument("--round", action="store_true",
                    help="★ 圆形进口分区：按到中心半径 r=√(y²+z²) 划分 "
                         "jet/pilot/coflow/空气（严格对标实验）")
    ap.add_argument("--quarter", action="store_true",
                    help="1/4 域：y=0、z=0 为 symmetry（需配合 --round）")
    ap.add_argument("--tight", action="store_true",
                    help="★ 百万单元预算版规格（细网格只留给喷口与火焰核心）")
    ap.add_argument("--half-mm", type=float, default=None,
                    help="★ 横向半域宽度 [mm]（默认 216；**150 = 实验风洞 300mm"
                         " 方截面，Dh 恰好 0.30 m**）")
    a = ap.parse_args()

    dmin = a.dmin * 1e-3 if a.dmin else None
    dmax = a.dmax * 1e-3 if a.dmax else None

    if a.compact:
        rf = a.refine
        half = (a.half_mm * 1e-3) if a.half_mm else C.R_DOMAIN
        XSP, YSP = X_COMPACT, Y_COMPACT
        if a.half_mm:                          # ★ 半域可缩 → 横向规格按新半宽生成
            XSP, YSP = X_TIGHT_FULL, yz_spec(half)
        elif a.tight:
            XSP, YSP = X_TIGHT_FULL, YZ_TIGHT_ROUND
        if dmin or dmax:                       # ★ 对**已选**规格限幅（不是 X_COMPACT）
            XSP = clamp_specs(XSP, dmin, dmax)
            YSP = clamp_specs(YSP, dmin, dmax)
        xs = build_axis(XSP, rf)
        ys_half = build_axis(YSP, rf)
        # z 向：圆形进口用渐变规格；给了 dmax 就按 ≤dmax 均匀铺满；否则 6 段
        if a.round:
            zspec = (yz_spec(half) if a.half_mm else
                     (YZ_TIGHT_ROUND if a.tight else Z_HALF_SPEC_ROUND))
            zs_half = build_z_axis(spec=zspec)
        else:
            zs_half = build_z_axis(Z_HALF_MM_COMPACT,
                                   dmax * 1e3 if dmax else None)
        zs = zs_half if a.quarter else (
            [-v for v in reversed(zs_half[1:])] + zs_half)
        tag = "compact" if rf == 1.0 else f"gci_r{rf:.3f}".replace(".", "")
    else:
        spec = C.MESH_SPECS_V5[a.level]
        refine = spec["refine"]
        xs = build_axis(spec["axial"], refine)
        ys_half = build_axis(spec["radial"], refine)
        zs = build_z_axis()
        tag = a.level
    if dmin or dmax:
        tag += ("_lim" + (f"{a.dmin}".replace(".", "p") if a.dmin else "0")
                + "-" + (f"{a.dmax}".replace(".", "p") if a.dmax else "0"))
    if a.round:
        tag += "_round"
    if a.quarter:
        tag += "_q"

    ys = ys_half if a.quarter else ([-v for v in reversed(ys_half[1:])]
                                    + ys_half)              # 镜像全域 / 1/4 域
    nx, ny, nz = len(xs) - 1, len(ys) - 1, len(zs) - 1
    ncell = nx * ny * nz

    if a.dry_run:
        import statistics
        dx = [xs[i + 1] - xs[i] for i in range(nx)]
        dy = [ys[i + 1] - ys[i] for i in range(ny)]
        dz = [zs[i + 1] - zs[i] for i in range(nz)]
        print(f"[dry-run] tag={tag}")
        print(f"  单元 {ncell:,}  ({nx} x × {ny} y × {nz} z)")
        for nm, d in (("Δx", dx), ("Δy", dy), ("Δz", dz)):
            print(f"  {nm}: min {min(d)*1e3:.4f} mm  max {max(d)*1e3:.4f} mm  "
                  f"中位 {statistics.median(d)*1e3:.4f} mm")
        print(f"  节点 {((nx+1)*(ny+1)*(nz+1)):,}")
        return 0

    nid = lambda ix, iy, iz: (ix * (ny + 1) + iy) * (nz + 1) + iz + 1   # noqa: E731
    cid = lambda ix, iy, iz: (ix * ny + iy) * nz + iz + 1               # noqa: E731

    nodes = [(xs[ix], ys[iy], zs[iz])
             for ix in range(nx + 1)
             for iy in range(ny + 1)
             for iz in range(nz + 1)]

    # ---- 单元（hex，标准序：底 4 逆时针 + 顶 4 对应）----
    cells = []
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                cells.append((nid(ix, iy, iz), nid(ix + 1, iy, iz),
                              nid(ix + 1, iy + 1, iz), nid(ix, iy + 1, iz),
                              nid(ix, iy, iz + 1), nid(ix + 1, iy, iz + 1),
                              nid(ix + 1, iy + 1, iz + 1), nid(ix, iy + 1, iz + 1)))

    # ---- 面（去重 + zone 分类）----
    faces: dict[frozenset, list] = {}

    def add(seq, c0, zone):
        key = frozenset(seq)
        if key in faces:
            faces[key][2] = c0                              # 第二单元 → c1
        else:
            faces[key] = [tuple(seq), c0, 0, zone]

    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                c = cells[cid(ix, iy, iz) - 1]
                n000, n100, n110, n010, n001, n101, n111, n011 = c
                ci = cid(ix, iy, iz)
                # 面的边界判定：用**面索引**（差一错误教训：最后单元的 +侧
                # 必须判 == n，不是 == n-1，否则出口/壁面被误标为内部）
                zx = 3 if ix == 0 else 0                    # x=0 进口（后细分）
                zx2 = 6 if ix + 1 == nx else 0              # x=L 出口
                zy = 7 if iy == 0 else 0                    # y=-R 壁
                zy2 = 8 if iy + 1 == ny else 0              # y=+R 壁
                zz = 9 if iz == 0 else 0                    # z=-R 壁
                zz2 = 10 if iz + 1 == nz else 0             # z=+R 壁
                add((n000, n010, n011, n001), ci, zx)
                add((n100, n101, n111, n110), ci, zx2)
                add((n000, n001, n101, n100), ci, zy)
                add((n010, n110, n111, n011), ci, zy2)
                add((n000, n100, n110, n010), ci, zz)
                add((n001, n011, n111, n101), ci, zz2)

    PZU = PZ_QUARTER if a.quarter else (PZ_ROUND if a.round else PZ)
    # ★ 半域 ≤ 150mm（= 实验风洞 300mm 方截面）时，伴流覆盖整个截面，不再有"空气"环
    RCOF = R_COFLOW if (ys[-1] > 0.1501) else 1e9

    # 进口面细分
    for rec in faces.values():
        if rec[3] != 3:
            continue
        ymid = sum(nodes[n - 1][1] for n in rec[0]) / 4.0
        zmid = sum(nodes[n - 1][2] for n in rec[0]) / 4.0
        if a.round:
            # ★ 严格对标实验：按**到中心半径**分区（圆形射流）
            r = math.hypot(ymid, zmid)
            rec[3] = (3 if r <= C.R_JET else
                      4 if r <= C.R_PILOT_OUT else
                      5 if r <= RCOF else 11)         # 11 = 伴流以外（同伴流的空气）
        else:
            ay = abs(ymid)
            rec[3] = 3 if ay <= C.R_JET else (4 if ay <= C.R_PILOT_OUT else 5)

    interior = [r for r in faces.values() if r[2] != 0]
    by_zone: dict[int, list] = {z: [] for z in PZU}
    for r in faces.values():
        if r[2] == 0:
            by_zone[r[3]].append(r)
    NF = len(interior) + sum(len(v) for v in by_zone.values())

    # ---- 写出 ----
    L = [f'(1 "flameD box3d {tag}: x=axial, y/z=transverse, walls all around")',
         "(3 3)", ""]
    L.append(f"(12 (0 1 {hx(ncell)} 0))")
    L.append(f"(13 (0 1 {hx(NF)} 0))")
    L.append(f"(10 (0 1 {hx(len(nodes))} 0 3))")
    L.append("")
    L.append(f"(12 (1 1 {hx(ncell)} 1 0)")
    L.append("(")
    row = []
    for _ in range(ncell):
        row.append("4")                                     # hex 类型码 = 4
        if len(row) == 16:
            L.append(" ".join(row))
            row = []
    if row:
        L.append(" ".join(row))
    L.append("))")
    L.append("")
    first = 1
    L.append(f"(13 ({hx(FT_INTERIOR)} {hx(first)} {hx(len(interior))} "
             f"{hx(FT_INTERIOR)} 4)")                       # ★ 末位 4 = 面节点数
    L.append("(")
    for s, c0, c1, _ in interior:
        L.append(" ".join(hx(v) for v in s) + f" {hx(c0)} {hx(c1)}")
    L.append("))")
    L.append("")
    first = len(interior) + 1
    for z in sorted(PZU):
        fs = by_zone[z]
        if not fs:
            continue
        last = first + len(fs) - 1
        L.append(f"(13 ({hx(z)} {hx(first)} {hx(last)} {hx(PZU[z][0])} 4)")
        L.append("(")
        for s, c0, c1, _ in fs:
            L.append(" ".join(hx(v) for v in s) + f" {hx(c0)} {hx(c1)}")
        L.append("))")
        L.append("")
        first = last + 1
    L.append(f"(10 (1 1 {hx(len(nodes))} 1 3)")
    L.append("(")
    for x, y, z in nodes:
        L.append(f" {x:.16e}  {y:.16e}  {z:.16e}")
    L.append("))")

    out = Path(a.out) if a.out else ROOT / "mesh" / "box3d" / f"{tag}.msh"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="ascii")
    print(f"[{out.name}] 节点 {len(nodes)}  单元 {ncell} "
          f"({nx} x × {ny} y × {nz} z)  面 {NF}")
    print(f"  x: {xs[0]*1e3:.1f}..{xs[-1]*1e3:.1f} mm ({nx} 段)")
    print(f"  y: {ys[0]*1e3:.1f}..{ys[-1]*1e3:.1f} mm ({ny} 段)")
    print(f"  z: {zs[0]*1e3:.1f}..{zs[-1]*1e3:.1f} mm ({nz} 段)")
    for z in sorted(PZU):
        print(f"    zone {z:>2} {PZU[z][1]:<16} 面 {len(by_zone[z]):>6}")
    print(f"    interior       面 {len(interior):>6}")

    # ---- ★ 进口分区面积 vs 实验（严格对标的核心校验）----
    if a.round:
        print("\n  [进口分区面积校验 · 对标实验]")

        def qarea(seq):
            p = [nodes[n - 1] for n in seq]
            v1 = [p[1][i] - p[0][i] for i in range(3)]
            v2 = [p[2][i] - p[0][i] for i in range(3)]
            v3 = [p[3][i] - p[0][i] for i in range(3)]
            c1 = (v1[1] * v2[2] - v1[2] * v2[1],
                  v1[2] * v2[0] - v1[0] * v2[2],
                  v1[0] * v2[1] - v1[1] * v2[0])
            c2 = (v2[1] * v3[2] - v2[2] * v3[1],
                  v2[2] * v3[0] - v2[0] * v3[2],
                  v2[0] * v3[1] - v2[1] * v3[0])
            return 0.5 * (sum(x * x for x in c1) ** 0.5
                          + sum(x * x for x in c2) ** 0.5)

        import math as _m
        side = 2 * ys[-1]
        sq = side ** 2
        tgt = {
            3: ("jet", _m.pi * C.R_JET ** 2, C.D_JET),
            4: ("pilot", _m.pi * (C.R_PILOT_OUT ** 2 - C.R_JET ** 2), None),
            5: ("coflow",
                sq - _m.pi * C.R_PILOT_OUT ** 2 if RCOF > 1e8
                else _m.pi * (RCOF ** 2 - C.R_PILOT_OUT ** 2), None),
            11: ("air", sq - _m.pi * R_COFLOW ** 2, None),
        }
        for z in (3, 4, 5, 11):
            if not by_zone.get(z):
                continue
            A = sum(qarea(r[0]) for r in by_zone.get(z, []))
            nm, th, deq = tgt[z]
            err = (A - th) / th * 100
            extra = ""
            if deq:                       # 用离散面积反算等效直径
                d_eq = 2 * _m.sqrt(A / _m.pi)
                extra = (f"　等效直径 d_eq = {d_eq*1e3:.3f} mm"
                         f"（实验 {deq*1e3:.3f} mm，"
                         f"{(d_eq/deq-1)*100:+.2f}%）")
            print(f"    {nm:<7} 离散面积 {A*1e6:10.2f} mm²   "
                  f"理论 {th*1e6:10.2f} mm²   偏差 {err:+6.2f}%{extra}")


if __name__ == "__main__":
    main()
