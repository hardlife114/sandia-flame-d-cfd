"""生成 Sandia flameD 的 2D 轴对称结构化四边形网格。

输出格式：FLUENT 遗留 ASCII 网格（已按 Fluent 2025 R2 实测书写体例实现，
样本来自 mesh/_oracle.cas —— 由 Fluent 自身读入 2D 算例后以遗留 ASCII 写出的
网格段）。要点：

  * 段结构      (12 单元头) (13 面头) (10 节点头)，随后逐段写数据
  * **所有整数（计数、节点号、单元号）均为十六进制**
  * 面按**区域分块**书写，没有全局面表；区域 2 为内部面
  * 单元段只写每个单元的**节点数**（三角形 3，四边形 4）
  * 节点坐标每行一个，'%.16e'
  * 面类型码：2=interior 3=wall 4=pressure-inlet 5=pressure-outlet 7=symmetry
    （velocity-inlet / axis 的码值由 probe_codes.py 实测确定）

坐标：x = 轴向(0..720 mm)，y = 径向(0..216 mm)，对称轴 y = 0。
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import flamed_common as C

# ---------------------------------------------------------------- 面类型码
FT_INTERIOR = 2
FT_WALL = 3
FT_PRESSURE_INLET = 4
FT_PRESSURE_OUTLET = 5
FT_SYMMETRY = 7

# 待定码值（由 probe_codes.py 实测后回填）
FT_VELOCITY_INLET = 10
FT_AXIS = 37

# 单元段取值：Fluent 2025 R2 实测，**必须为 3**。
# 试过 4 -> 计算进程 SIGSEGV；2 -> Failed in Fill_Domain；3 -> 正常建网格
# （官方 2D 样例的单元段同样是 3，个别 7 节点多边形单元为 7）。
# 单元的实际形状由面连接关系推导，网格检查报告为 mixed cell，几何/体积正确。
CELL_SECTION_VALUE = 3


def n_from_ends(L: float, d0: float, d1: float) -> tuple[int, float]:
    """给定段长 L、首层间距 d0、末层间距 d1，求单元数 n 与增长比 q。

    段内按几何级数 d_i = d0_eff * q^i 分布，且 sum(d_i) = L。
    先按 (d1/d0)^(1/(n-1)) 的关系扫描整数 n 使总长最接近 L，
    再用 d0_eff = L(q-1)/(q^n-1) 微调首层间距，使总长**精确**等于 L。
    返回 (n, q)。|d1-d0| 足够小时退化为均匀分布（q=1）。
    """
    if L <= 0:
        raise ValueError("段长必须为正")
    if d0 <= 0 or d1 <= 0:
        raise ValueError("间距必须为正")
    if abs(d1 - d0) <= 1e-12 * max(d0, d1):
        return max(1, int(round(L / d0))), 1.0
    ratio = d1 / d0
    best = None                                   # (err, n, q)
    n = 2
    while n <= 2_000_000:
        q = ratio ** (1.0 / (n - 1))
        s = d0 * (q ** n - 1.0) / (q - 1.0)
        err = abs(s - L)
        if best is None or err < best[0]:
            best = (err, n, q)
        if s > L and err > best[0]:
            break
        n += 1
    _, n, q = best
    return n, q


def build_axis(segs: list, refine: float = 1.0) -> list[float]:
    """按段生成一维坐标，段端点严格对齐，且**段与段之间尺寸自动延续**。

    段三种写法：
      (起点, 终点, 目标间距)                  —— 均匀段（v1 规格）
      (起点, 终点, 增长比 q, 首层间距 d0 | None) —— 几何渐变段（v2/v3 规格）
          q >= 1：d_i = d0 * q^i；q = 1 即均匀段
          d0 = None：**延续上一段的末层间距**（保证相邻段无突变）
          d0 = 数值：显式指定（仅用于唇口这类薄几何，需局部更细）
      {"a":…, "b":…, "d0":…, "d1":…}          —— **双端锁定段**（v4 规格）
          首末间距同时给定，段内几何分布由 n_from_ends 反解；
          d0 = None 时延续上一段末层间距。

    `refine`：把所有显式给定的间距除以该因子。
      * 元组写法只缩"首层"，几何段的尾层间距不受控（级间比会失真）；
      * **dict 写法同时缩 d0 与 d1**，因此整段间距严格按 1/refine 缩放，
        单元数也严格按 refine 增长 —— 这是做严格 GCI 的前提。
    """
    if refine <= 0:
        raise ValueError("refine 必须为正")
    pts: list[float] = []
    carry: float | None = None          # 上一段末层间距
    for seg in segs:
        if isinstance(seg, dict):
            a, b = seg["a"], seg["b"]
            if b <= a:
                raise ValueError(f"非法段 {a} -> {b}")
            d0, d1 = seg["d0"], seg["d1"]
            if d0 is None:
                if carry is None:
                    raise ValueError("首段必须显式给出 d0")
                d0 = carry
            d0, d1 = d0 / refine, d1 / refine
            L = b - a
            n, q = n_from_ends(L, d0, d1)
            if abs(q - 1.0) < 1e-12:
                de = L / n
                coords = [a + de * i for i in range(n + 1)]
                carry = de
            else:
                de = L * (q - 1.0) / (q ** n - 1.0)
                coords = [a + de * (q ** i - 1.0) / (q - 1.0)
                          for i in range(n + 1)]
                coords[-1] = b
                carry = coords[-1] - coords[-2]
        elif len(seg) == 3:
            a, b, target = seg
            if b <= a:
                raise ValueError(f"非法段 {a} -> {b}")
            d = target / refine
            n = max(1, int(math.ceil((b - a) / d - 1e-9)))
            de = (b - a) / n
            coords = [a + de * i for i in range(n + 1)]
        elif len(seg) == 4:
            a, b, q, d0 = seg
            if b <= a:
                raise ValueError(f"非法段 {a} -> {b}")
            if q < 1.0:
                raise ValueError(f"增长比必须 >= 1（段 {a}->{b}: q={q}）")
            d0 = (d0 / refine) if d0 is not None else carry
            if d0 is None:
                raise ValueError("第一段必须给出首层间距")
            L = b - a
            if abs(q - 1.0) < 1e-12:
                n = max(1, int(math.ceil(L / d0 - 1e-9)))
                de = L / n
                coords = [a + de * i for i in range(n + 1)]
                carry = de
            else:
                n = 1
                while d0 * (q ** n - 1.0) / (q - 1.0) < L - 1e-15:
                    n += 1
                de = L * (q - 1.0) / (q ** n - 1.0)
                coords = [a + de * (q ** i - 1.0) / (q - 1.0) for i in range(n + 1)]
                carry = de * q ** (n - 1)
            coords[-1] = b
        else:
            raise ValueError(f"非法段写法：{seg}")
        if pts:
            pts.pop()
        pts.extend(coords)
    out = [pts[0]]
    for v in pts[1:]:
        if abs(v - out[-1]) > 1e-14:
            out.append(v)
    return out


class QuadMesh:
    """2D 轴对称映射四边形网格。

    节点号 nid(iy, ix) = ix*(ny+1) + iy + 1，单元号 cid(iy, ix) = ix*ny + iy + 1。
    面法向约定：节点序方向 (dx,dy) 旋转 -90° 得 (dy,-dx)，法向由 c0 指向 c1；
    边界面 c1 = 0，法向指向区域外部。
    """

    def __init__(self, xs: list[float], ys: list[float],
                 ftype: dict[int, int] | None = None,
                 cell_nodes: int = CELL_SECTION_VALUE):
        self.xs, self.ys = xs, ys
        self.nx, self.ny = len(xs) - 1, len(ys) - 1
        self.ftype = ftype or {
            C.ZONE_FLUID: FT_INTERIOR,
            C.ZONE_LIP: FT_WALL,
            C.ZONE_RIM: FT_WALL,
            C.ZONE_IN_JET: FT_VELOCITY_INLET,
            C.ZONE_IN_PILOT: FT_VELOCITY_INLET,
            C.ZONE_IN_COFLOW: FT_VELOCITY_INLET,
            C.ZONE_AXIS: FT_AXIS,
            C.ZONE_OUTLET: FT_PRESSURE_OUTLET,
            C.ZONE_FARFIELD: FT_WALL,
        }
        self.cell_nodes = cell_nodes

    # -- 索引
    def nid(self, iy: int, ix: int) -> int:
        return ix * (self.ny + 1) + iy + 1

    def cid(self, iy: int, ix: int) -> int:
        return ix * self.ny + iy + 1

    # -- 组装
    def assemble(self):
        nodes = [(self.xs[ix], self.ys[iy])
                 for ix in range(self.nx + 1) for iy in range(self.ny + 1)]

        interior = []
        for ix in range(1, self.nx):
            for iy in range(self.ny):
                interior.append((self.nid(iy, ix), self.nid(iy + 1, ix),
                                 self.cid(iy, ix - 1), self.cid(iy, ix)))
        for ix in range(self.nx):
            for iy in range(1, self.ny):
                interior.append((self.nid(iy, ix + 1), self.nid(iy, ix),
                                 self.cid(iy - 1, ix), self.cid(iy, ix)))

        def classify(iy):
            rc = 0.5 * (self.ys[iy] + self.ys[iy + 1])
            if rc <= C.R_JET + 1e-12:
                return C.ZONE_IN_JET
            if rc <= C.R_PILOT_IN + 1e-12:
                return C.ZONE_LIP
            if rc <= C.R_PILOT_OUT + 1e-12:
                return C.ZONE_IN_PILOT
            if rc <= C.R_BURNER_OUT + 1e-12:
                return C.ZONE_RIM
            return C.ZONE_IN_COFLOW

        g: dict[int, list] = {z: [] for z in
                              (C.ZONE_LIP, C.ZONE_RIM, C.ZONE_IN_JET, C.ZONE_IN_PILOT,
                               C.ZONE_IN_COFLOW, C.ZONE_AXIS, C.ZONE_OUTLET, C.ZONE_FARFIELD)}
        # 对称轴 y=0：沿**轴向**逐单元生成，法向 -y
        # 注意：此处必须按轴向索引 ix 循环（轴跨越 nx 个轴向单元），
        # 曾经误用径向索引导致边界不闭合、Fill_Domain 失败。
        for ix in range(self.nx):
            g[C.ZONE_AXIS].append((self.nid(0, ix), self.nid(0, ix + 1),
                                   self.cid(0, ix), 0))
        for iy in range(self.ny):                      # 入口 x=0, 法向 -x
            g[classify(iy)].append((self.nid(iy + 1, 0), self.nid(iy, 0),
                                    self.cid(iy, 0), 0))
        for iy in range(self.ny):                      # 出口 x=L, 法向 +x
            g[C.ZONE_OUTLET].append((self.nid(iy, self.nx), self.nid(iy + 1, self.nx),
                                     self.cid(iy, self.nx - 1), 0))
        for ix in range(self.nx):                      # 远场 y=R, 法向 +y
            g[C.ZONE_FARFIELD].append((self.nid(self.ny, ix + 1), self.nid(self.ny, ix),
                                       self.cid(self.ny - 1, ix), 0))

        ncell = self.nx * self.ny
        return nodes, ncell, interior, g

    # -- 写出
    def write(self, path: Path):
        nodes, ncell, interior, g = self.assemble()
        NN, NF = len(nodes), len(interior) + sum(len(v) for v in g.values())
        hx = lambda v: format(v, "x")                            # noqa: E731

        L = ['(1 "flameD 2D axisymmetric structured quad mesh")', "(2 2)", ""]
        L.append(f"(12 (0 1 {hx(ncell)} 0))")
        L.append(f"(13 (0 1 {hx(NF)} 0))")
        L.append(f"(10 (0 1 {hx(NN)} 0 2))")
        L.append("")

        # 单元段：每单元只写节点数
        L.append(f"(12 (1 1 {hx(ncell)} 1 0)")
        L.append("(")
        row = []
        for _ in range(ncell):
            row.append(str(self.cell_nodes))
            if len(row) == 16:
                L.append(" ".join(row))
                row = []
        if row:
            L.append(" ".join(row))
        L.append("))")
        L.append("")

        # 内部面区（区号 2）
        L.append(f"(13 ({hx(C.ZONE_FLUID)} 1 {hx(len(interior))} "
                 f"{hx(self.ftype[C.ZONE_FLUID])} 2)")
        L.append("(")
        for (a, b, c0, c1) in interior:
            L.append(f"{hx(a)} {hx(b)} {hx(c0)} {hx(c1)}")
        L.append("))")
        L.append("")

        # 边界面区
        first = len(interior) + 1
        ranges = {}
        for z in (C.ZONE_LIP, C.ZONE_RIM, C.ZONE_IN_JET, C.ZONE_IN_PILOT,
                  C.ZONE_IN_COFLOW, C.ZONE_AXIS, C.ZONE_OUTLET, C.ZONE_FARFIELD):
            fs = g[z]
            last = first + len(fs) - 1
            ranges[z] = (first, last)
            L.append(f"(13 ({hx(z)} {hx(first)} {hx(last)} {hx(self.ftype[z])} 2)")
            L.append("(")
            for (a, b, c0, c1) in fs:
                L.append(f"{hx(a)} {hx(b)} {hx(c0)} {hx(c1)}")
            L.append("))")
            L.append("")
            first = last + 1

        # 节点段
        L.append(f"(10 (1 1 {hx(NN)} 1 2)")
        L.append("(")
        for (x, y) in nodes:
            L.append(f" {x:.16e}  {y:.16e}")
        L.append("))")
        L.append("")

        path.write_text("\n".join(L), encoding="ascii")
        print(f"[{path.name}] 节点 {NN}  单元 {ncell} ({self.ny} 径向 x {self.nx} 轴向)  "
              f"面 {NF}（内部 {len(interior)}）")
        for z in (C.ZONE_LIP, C.ZONE_RIM, C.ZONE_IN_JET, C.ZONE_IN_PILOT,
                  C.ZONE_IN_COFLOW, C.ZONE_AXIS, C.ZONE_OUTLET, C.ZONE_FARFIELD):
            a, b = ranges[z]
            print(f"    zone {z:>2} {C.ZONE_NAMES[z][1]:<14} 面 {len(g[z]):>5}  "
                  f"范围 {a}..{b}  类型码 {self.ftype[z]}")
        return NN, ncell, NF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", action="append")
    ap.add_argument("--specs", choices=["v1", "v2", "v3", "v4", "v5"], default="v1",
                    help="v1=原分段均匀；v2=几何渐变 + 级间 1:1/sqrt2:1/2；"
                         "v3=v2 基础上对火焰区径向局部加密；"
                         "v4=v3 + 双端锁定段（级间加密严格生效，可做 GCI）")
    ap.add_argument("--outdir", default=None,
                    help="输出目录（默认：v1 -> mesh/，v2..v5 -> mesh/<specs>/）")
    ap.add_argument("--cell-nodes", type=int, default=CELL_SECTION_VALUE)
    a = ap.parse_args()

    graded = {"v2": C.MESH_SPECS_V2, "v3": C.MESH_SPECS_V3,
              "v4": C.MESH_SPECS_V4, "v5": C.MESH_SPECS_V5}
    if a.specs in graded:
        levels = a.level or ["coarse", "medium", "fine"]
        outdir = Path(a.outdir) if a.outdir else (C.DIR_MESH / a.specs)
    else:
        levels = a.level or ["test", "medium"]
        outdir = Path(a.outdir) if a.outdir else C.DIR_MESH
    outdir.mkdir(parents=True, exist_ok=True)

    for lv in levels:
        if a.specs in graded:
            spec = graded[a.specs][lv]
            refine = spec["refine"]
        else:
            spec = C.MESH_SPECS[lv]
            refine = 1.0
        xs = build_axis(spec["axial"], refine)
        ys = build_axis(spec["radial"], refine)
        assert abs(ys[-1] - C.R_DOMAIN) < 1e-12 and abs(xs[-1] - C.L_DOMAIN) < 1e-12
        for feat in (C.R_JET, C.R_PILOT_IN, C.R_PILOT_OUT, C.R_BURNER_OUT):
            assert any(abs(v - feat) < 1e-14 for v in ys), f"特征点 {feat} 未落在网格线上"
        print(f"=== {a.specs} level {lv} (refine={refine:.6g}) ===")
        QuadMesh(xs, ys, cell_nodes=a.cell_nodes).write(outdir / f"{lv}.msh")


if __name__ == "__main__":
    main()
