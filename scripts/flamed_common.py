"""flameD 基准算例共享常量。

全部工况数据引自 SandiaPilotDoc21.pdf (Release 2.1, 15-JUN-2007)，
见 refs/SandiaPilotDoc21.pdf。标注 [DOC] 的为文档直接给定值。

坐标约定（Fluent 2D 轴对称）：x = 轴向，y = 径向，对称轴为 y = 0。
"""

from pathlib import Path

# ---------------------------------------------------------------- 路径
ROOT = Path(__file__).resolve().parent.parent
DIR_MECH = ROOT / "mechanism"
DIR_DECKS = ROOT / "decks"
DIR_MESH = ROOT / "mesh"
DIR_PROF = ROOT / "profiles"
DIR_FLAMELET = ROOT / "flamelet"
DIR_RUN = ROOT / "run"
DIR_REFS = ROOT / "refs"
DIR_RESULTS = ROOT / "results"

# ---------------------------------------------------------------- 几何 [DOC]
D_JET = 7.2e-3              # 主射流内径 [m]
PILOT_ID = 7.7e-3           # pilot 环内径 (壁厚 0.25 mm)
PILOT_OD = 18.2e-3          # pilot 环外径
BURNER_OD = 18.9e-3         # 燃烧器外壁外径 (壁厚 0.35 mm)
WIND_TUNNEL = 0.30          # 风洞出口边长 [m]

R_JET = D_JET / 2                 # 3.6 mm
R_PILOT_IN = PILOT_ID / 2         # 3.85 mm
R_PILOT_OUT = PILOT_OD / 2        # 9.1 mm
R_BURNER_OUT = BURNER_OD / 2      # 9.45 mm

# 计算域
L_DOMAIN = 100 * D_JET      # 轴向 720 mm
R_DOMAIN = 30 * D_JET       # 径向 216 mm

# ---------------------------------------------------------------- 工况 [DOC]
# 主射流
T_JET = 294.0               # K
U_JET_BULK = 49.6           # m/s  (Re = 22400)  ★ Flame D
RE_D = 22400.0
Y_JET = {"CH4": 0.15637, "O2": 0.19650, "N2": 0.64713}   # 25% CH4 + 75% dry air (vol)

# 引燃环 pilot —— 文档给定的喷口出口平面质量分数 (T = 1880 K)
T_PILOT = 1880.0            # K (+/- 50)
U_PILOT_BULK = 11.4         # m/s  [DOC] Flame D
U_PILOT_MEAS = 15.2         # m/s  由 TUD 实测剖面反推的平台区速度（灵敏度对照）
RHO_PILOT = 0.180           # kg/m3 [DOC]
F_PILOT = 0.27              # pilot 混合物分数 [DOC]
Y_PILOT = {
    "N2": 0.7342,
    "O2": 0.0540,
    "H2O": 0.0942,
    "CO2": 0.1098,
    "CO": 4.07e-3,
    "OH": 2.8e-3,
    "O": 7.47e-4,
    "H2": 1.29e-4,
    "H": 2.48e-5,
    "NO": 4.8e-6,
}

# Sandia C–F 系列：几何/组分相同，仅 jet 与 pilot 速度按比例变化
# [DOC] SandiaPilotDoc21.pdf §BULK FLOW
# 文档说明：pilot 组成对 E/F 通常沿用 Flame D；F 接近全局熄火
FLAMES = {
    "C": dict(U_jet=29.7, U_pilot=6.8,  Re=13400.0, note="弱火焰"),
    "D": dict(U_jet=49.6, U_pilot=11.4, Re=22400.0, note="基准，少量局部熄火"),
    "E": dict(U_jet=74.4, U_pilot=17.1, Re=33600.0, note="较强局部熄火"),
    "F": dict(U_jet=99.2, U_pilot=22.8, Re=44800.0, note="接近全局熄火"),
}

# 伴流 —— 文档含环境湿度的元素质量分数反解
T_COFLOW = 291.0            # K
U_COFLOW = 0.9              # m/s (+/- 0.05)
Y_COFLOW = {"O2": 0.23574, "N2": 0.75800, "H2O": 0.006256}
Y_COFLOW_DRY = {"O2": 0.2322, "N2": 0.7678}    # 干空气对照

# ---------------------------------------------------------------- 标量基准 [DOC]
F_STOIC = 0.351             # 化学计量混合物分数
L_STOIC_D = 47.0            # 化学计量火焰长度 / d (flame D)
L_VIS_D = 67.0              # 可见火焰长度 / d
ELEM_JET = {"H": 0.0393, "C": 0.1170, "O": 0.1965, "N": 0.6472}
ELEM_COFLOW = {"H": 0.0007, "C": 0.0000, "O": 0.2413, "N": 0.7580}
W_H, W_C, W_O, W_N = 1.008, 12.011, 15.999, 14.007

P_OP = 0.993 * 101325.0     # 操作压力 100 633 Pa [DOC] 0.993 atm

# 测点位置 [DOC] §MEASUREMENT LOCATIONS
X_D_AXIAL = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75]
X_D_RADIAL = [1, 2, 3, 7.5, 15, 30, 45, 60, 75]

# ---------------------------------------------------------------- 组分
SPECIES = ["N2", "O2", "H2O", "CH4", "CO", "CO2", "OH", "H2", "NO"]

# ---------------------------------------------------------------- Fluent 环境
ANSYS_ROOT = Path(r"D:\Program Files\ANSYS\2025R2\v252")
FLUENT_EXE = ANSYS_ROOT / "fluent" / "ntbin" / "win64" / "fluent.exe"
ANSYS_PY = ANSYS_ROOT / "commonfiles" / "CPython" / "3_10" / "winx64" / "Release" / "python" / "python.exe"
PYFLUENT_PATH = ANSYS_ROOT / "commonfiles" / "CPython" / "3_10" / "winx64" / "Release" / "Ansys" / "PyFluentCore"
CK_GRI = ANSYS_ROOT / "fluent" / "fluent25.2.0" / "KINetics" / "data"

SERVER_INFO = DIR_RUN / "serverinfo.txt"

# ---------------------------------------------------------------- 网格分级
# (起点, 终点, 目标间距) 单位 m；段内均匀分布，端点严格对齐
MESH_SPECS = {
    "test": {
        "axial": [(0.0, 30e-3, 3.0e-3), (30e-3, 80e-3, 6.0e-3),
                  (80e-3, 250e-3, 18e-3), (250e-3, L_DOMAIN, 50e-3)],
        "radial": [(0.0, R_JET, 3.0e-3), (R_JET, R_PILOT_IN, 2.5e-3),
                   (R_PILOT_IN, R_PILOT_OUT, 2.0e-3), (R_PILOT_OUT, R_BURNER_OUT, 3.5e-3),
                   (R_BURNER_OUT, 12e-3, 2.0e-3), (12e-3, 20e-3, 4.0e-3),
                   (20e-3, 40e-3, 8.0e-3), (40e-3, R_DOMAIN, 30e-3)],
    },
    "coarse": {
        "axial": [(0.0, 30e-3, 0.45e-3), (30e-3, 80e-3, 0.90e-3),
                  (80e-3, 250e-3, 2.70e-3), (250e-3, L_DOMAIN, 7.50e-3)],
        "radial": [(0.0, R_JET, 0.45e-3), (R_JET, R_PILOT_IN, 0.375e-3),
                   (R_PILOT_IN, R_PILOT_OUT, 0.30e-3), (R_PILOT_OUT, R_BURNER_OUT, 0.525e-3),
                   (R_BURNER_OUT, 12e-3, 0.30e-3), (12e-3, 20e-3, 0.60e-3),
                   (20e-3, 40e-3, 1.20e-3), (40e-3, R_DOMAIN, 4.50e-3)],
    },
    "medium": {
        "axial": [(0.0, 30e-3, 0.30e-3), (30e-3, 80e-3, 0.60e-3),
                  (80e-3, 250e-3, 1.80e-3), (250e-3, L_DOMAIN, 5.00e-3)],
        "radial": [(0.0, R_JET, 0.30e-3), (R_JET, R_PILOT_IN, 0.25e-3),
                   (R_PILOT_IN, R_PILOT_OUT, 0.20e-3), (R_PILOT_OUT, R_BURNER_OUT, 0.35e-3),
                   (R_BURNER_OUT, 12e-3, 0.20e-3), (12e-3, 20e-3, 0.40e-3),
                   (20e-3, 40e-3, 0.80e-3), (40e-3, R_DOMAIN, 3.00e-3)],
    },
    "fine": {
        "axial": [(0.0, 30e-3, 0.214e-3), (30e-3, 80e-3, 0.429e-3),
                  (80e-3, 250e-3, 1.286e-3), (250e-3, L_DOMAIN, 3.571e-3)],
        "radial": [(0.0, R_JET, 0.214e-3), (R_JET, R_PILOT_IN, 0.179e-3),
                   (R_PILOT_IN, R_PILOT_OUT, 0.143e-3), (R_PILOT_OUT, R_BURNER_OUT, 0.25e-3),
                   (R_BURNER_OUT, 12e-3, 0.143e-3), (12e-3, 20e-3, 0.286e-3),
                   (20e-3, 40e-3, 0.571e-3), (40e-3, R_DOMAIN, 2.143e-3)],
    },
}

# 边界区命名（zone id 固定，便于 journal/脚本引用）
ZONE_FLUID = 2
ZONE_LIP = 3
ZONE_RIM = 4
ZONE_IN_JET = 5
ZONE_IN_PILOT = 6
ZONE_IN_COFLOW = 7
ZONE_AXIS = 8
ZONE_OUTLET = 9
ZONE_FARFIELD = 10

ZONE_NAMES = {
    ZONE_FLUID: ("fluid", "fluid"),
    ZONE_LIP: ("wall", "wall-lip"),
    ZONE_RIM: ("wall", "wall-rim"),
    ZONE_IN_JET: ("velocity-inlet", "inlet-jet"),
    ZONE_IN_PILOT: ("velocity-inlet", "inlet-pilot"),
    ZONE_IN_COFLOW: ("velocity-inlet", "inlet-coflow"),
    ZONE_AXIS: ("axis", "axis"),
    ZONE_OUTLET: ("pressure-outlet", "outlet"),
    # 用户要求：外缘（r=R_DOMAIN 的圆柱面）改为**固壁**，只保留流向出口一个出口。
    # 此前该面是 pressure-outlet，实测出现过 100% 面积回流（2107 次 Reversed flow），
    # 是稳态解振荡的疑似外因之一；改为壁面后域被封闭，伴流只能从下游出口流出。
    ZONE_FARFIELD: ("wall", "wall-farfield"),
}

# ================================================================ 网格分级 v2
# 相对 v1 的三点改动（针对"火焰提前贴轴/数值扩散过强、网格无关性不达标"）：
#
#  1) **段内几何渐变**代替分段均匀：d_i = d0 * q^i。
#     v1 的段间尺寸比可达 x2~x3.75（如 coarse 径向 0.80 -> 3.00 mm），
#     突变会在该处产生大的截断误差 -> 假扩散。v2 令相邻单元尺寸比恒定，
#     火焰区 q<=1.035、外场 q<=1.05，全程无突变。
#
#  2) **级间比为严格的 1 : 1/sqrt(2) : 1/2**（coarse : medium : fine）。
#     v1 的两级比是 1 : 1.48 : 2.10，不是常数，严格 GCI 做不了。
#     v2 用同一套基准段 + `refine` 因子缩放首层间距，间距比精确为 sqrt(2)。
#
#  3) **单元预算向火焰区倾斜**：r/d<=5.5、x/d<=40 内加密，
#     远场（r>40mm / x>250mm 的纯伴流与出口段）主动放粗。
#
# 段的写法：(起点, 终点, 增长比 q, 首层间距 d0 | None)
#   q = 1 即均匀段；q > 1 为几何渐扩；
#   d0 = None 表示**延续上一段的末层间距**（段间自动无突变）。
# 单元数由 (b-a, d0, q) 反解，段端点严格对齐，特征半径仍强制落在网格线上。
#
# 设计取舍：唇口厚 0.25 mm，需 >=2 层才可解析，故该处间距必须 ~0.125 mm；
# 为避免在火焰根部出现尺寸突变，把射流段也一并降到 0.16 mm（均匀），
# 使 射流(0.16) -> 唇口(0.125) -> pilot(0.125 起，缓增) 全程比 <=1.3。
MESH_SPECS_V2_BASE_AXIAL = [
    (0.0,       30e-3,   1.000, 0.3000e-3),   # 近场 x/d<=4.2：火焰稳定区，均匀
    (30e-3,     80e-3,   1.040, None),        # 过渡 x/d=4.2~11
    (80e-3,    250e-3,   1.020, None),        # 中场 x/d=11~35（缓增，末层 ~5.4 mm）
    (250e-3,  L_DOMAIN,  1.000, None),        # 远场：均匀 ~5.4 mm（限幅）
]
MESH_SPECS_V2_BASE_RADIAL = [
    (0.0,          R_JET,        1.000, 0.16000e-3),  # 主射流
    (R_JET,        R_PILOT_IN,   1.000, 0.12500e-3),  # 喷唇（壁，0.25mm -> 2 层）
    (R_PILOT_IN,   R_PILOT_OUT,  1.020, 0.12500e-3),  # pilot 环（缓增到 ~0.23）
    (R_PILOT_OUT,  R_BURNER_OUT, 1.000, 0.17500e-3),  # 外唇（壁）
    (R_BURNER_OUT, 40e-3,        1.035, None),        # 火焰区 r/d<=5.6
    (40e-3,        R_DOMAIN,     1.025, None),        # 外场：末层 ~5.4 mm（限幅）
]
MESH_SPECS_V2 = {
    "coarse": {"axial": MESH_SPECS_V2_BASE_AXIAL,
               "radial": MESH_SPECS_V2_BASE_RADIAL, "refine": 1.0},
    "medium": {"axial": MESH_SPECS_V2_BASE_AXIAL,
               "radial": MESH_SPECS_V2_BASE_RADIAL, "refine": 2.0 ** 0.5},
    "fine":   {"axial": MESH_SPECS_V2_BASE_AXIAL,
               "radial": MESH_SPECS_V2_BASE_RADIAL, "refine": 2.0},
}

# ================================================================ 网格分级 v3
# 目标：**火焰区局部加密，不大量增加单元数**。
#
# 物理依据（flameD）：火焰（高温带）位于 r/d ≈ 1.3 ~ 5.6，即 r ≈ 9.5 ~ 40 mm；
# 轴向 r/d=15 处 T 峰值在 r/d≈1.5~3、中心线峰值在 x/d≈45。
# v2 的径向在该带里增长过快（r=30mm 处 Δr=0.877mm、r=40mm 处 1.196mm），
# 相当于把"火焰所在环带"的分辨率让给了外侧无梯度的伴流区。
#
# v3 的做法（把单元从"无梯度区"搬到"有梯度区"）：
#   * 火焰带 r ∈ [9.45, 45] mm：q = 1.012（极缓），Δr 只从 0.175 增到 ~0.60 mm；
#   * 过渡带 r ∈ [45, 70] mm：q = 1.12（连续但快速放大，此处已出火焰）；
#   * 伴流外场 r ∈ [70, 216] mm：q = 1.04（Δr 到 ~9 mm，反正没有梯度）；
#   * 轴向同理：30→80 mm 用 q=1.03 过渡，80→300 mm（x/d=11~42）用 q=1.012 覆盖火焰，
#     300→720 mm 放粗。
#
# 注意（贴体网格的固有限制）：tensor-product 四边形网格里径向分布全局一套，
# 因此"局部"只能实现为**径向局部加密 + 轴向按火焰轴向范围加密**；
# 若要做到"仅在 r<45mm 内加密轴向"，必须脱离贴体结构（非协调界面 / 三角过渡），
# 见 MESH_OPT_V3.md §5。
MESH_SPECS_V3_BASE_AXIAL = [
    (0.0,       30e-3,   1.000, 0.3000e-3),   # 火焰稳定区（x/d<=4.2），均匀
    (30e-3,     80e-3,   1.030, None),        # 过渡
    (80e-3,    300e-3,   1.012, None),        # ★ 火焰轴向 x/d=11~42，极缓
    (300e-3,   600e-3,   1.020, None),        # 火焰尾段
    (600e-3,  L_DOMAIN,  1.000, None),        # 远场出口（均匀延续）
]
MESH_SPECS_V3_BASE_RADIAL = [
    (0.0,          R_JET,        1.000, 0.16000e-3),  # 主射流
    (R_JET,        R_PILOT_IN,   1.000, 0.12500e-3),  # 喷唇（壁）
    (R_PILOT_IN,   R_PILOT_OUT,  1.010, 0.12500e-3),  # pilot 环
    (R_PILOT_OUT,  R_BURNER_OUT, 1.000, 0.17500e-3),  # 外唇（壁）
    (R_BURNER_OUT, 45e-3,        1.015, None),        # ★ 火焰带 r/d=1.3~6.3，极缓
    (45e-3,        70e-3,        1.150, None),        # 出火焰后快速过渡
    (70e-3,       130e-3,        1.045, None),        # 伴流内圈
    (130e-3,      R_DOMAIN,      1.000, None),        # 伴流外圈（均匀延续）
]
MESH_SPECS_V3 = {
    "coarse": {"axial": MESH_SPECS_V3_BASE_AXIAL,
               "radial": MESH_SPECS_V3_BASE_RADIAL, "refine": 1.0},
    "medium": {"axial": MESH_SPECS_V3_BASE_AXIAL,
               "radial": MESH_SPECS_V3_BASE_RADIAL, "refine": 2.0 ** 0.5},
    "fine":   {"axial": MESH_SPECS_V3_BASE_AXIAL,
               "radial": MESH_SPECS_V3_BASE_RADIAL, "refine": 2.0},
}

# ================================================================ 网格分级 v4
# v3 的**结构性缺陷**：级间加密失效。
#
# 成因：v2/v3 的段写法是 (a, b, q, d0)，`refine` 只除**首层**间距，
# 而增长比 q 固定、段又要覆盖同样的长度 L，于是尾层间距几乎不变，
# 整段平均间距也就不缩。实测（scripts/mesh_refine_ratio.py）：
#     r=40 mm 处  dr: 0.628 -> 0.567 -> 0.542 mm（比 0.903 / 0.956）
#     r=50 mm 处  dr: 1.241 -> 1.241 -> 1.215 mm（比 1.000，完全不缩）
#     x=300 mm 处 dx: 4.308 -> 4.242 -> 4.181 mm（比 0.985 / 0.986）
#   → 全局 h 级间比只有 1.198 / 1.201（理想 1.414），单元数比 1 : 1.443 : 2.071
#     （理想 1 : 2 : 4）。**这种网格做出来的 GCI 不可信**。
#
# v4 的修法：段改成**双端锁定**写法 {"a","b","d0","d1"}，
# `refine` 同时缩 d0 与 d1 → 整段间距严格按 1/refine 缩放、单元数严格按
# refine 增长 → 级间比精确为 1 : 1/√2 : 1/2，单元数精确为 1 : 2 : 4。
#
# 段的 d0/d1 取自 v3-coarse 实测的段首/段末间距，因此 **v4-coarse ≡ v3-coarse
# 的分布**（单元数 ~5.9 万），差异只体现在中/细两级真正变细了。
MESH_SPECS_V4_BASE_AXIAL = [
    {"a": 0.0,     "b": 30e-3,  "d0": 0.3000e-3, "d1": 0.3000e-3},  # 火焰稳定区，均匀
    {"a": 30e-3,   "b": 80e-3,  "d0": None,      "d1": 1.7436e-3},  # 过渡
    {"a": 80e-3,   "b": 300e-3, "d0": None,      "d1": 4.3075e-3},  # ★ 火焰轴向 x/d=11~42
    {"a": 300e-3,  "b": 600e-3, "d0": None,      "d1": 9.9734e-3},  # 火焰尾段
    {"a": 600e-3,  "b": L_DOMAIN, "d0": None,    "d1": 9.9734e-3},  # 远场出口
]
MESH_SPECS_V4_BASE_RADIAL = [
    {"a": 0.0,          "b": R_JET,        "d0": 0.1600e-3, "d1": 0.1600e-3},  # 主射流
    {"a": R_JET,        "b": R_PILOT_IN,   "d0": 0.1250e-3, "d1": 0.1250e-3},  # 喷唇（壁）
    {"a": R_PILOT_IN,   "b": R_PILOT_OUT,  "d0": None,      "d1": 0.1726e-3},  # pilot 环
    {"a": R_PILOT_OUT,  "b": R_BURNER_OUT, "d0": 0.1750e-3, "d1": 0.1750e-3},  # 外唇（壁）
    {"a": R_BURNER_OUT, "b": 45e-3,        "d0": None,      "d1": 0.6974e-3},  # ★ 火焰带
    {"a": 45e-3,        "b": 70e-3,        "d0": None,      "d1": 3.7976e-3},  # 出火焰过渡
    {"a": 70e-3,        "b": 130e-3,       "d0": None,      "d1": 5.9297e-3},  # 伴流内圈
    {"a": 130e-3,       "b": R_DOMAIN,     "d0": None,      "d1": 5.9297e-3},  # 伴流外圈
]
MESH_SPECS_V4 = {
    # refine 因子不是名义的 1 : 1/√2 : 1/2，而是**反解**出来的：
    # 双端锁定缩放后，单元数 ≈ refine^2.71（几何段 + 整数取整），
    # 名义 √2 / 2 会落到 1 : 2.56 : 6.15（fine 35 万，太贵）。
    # 数值求解「使单元数严格成 1 : 2 : 4」得到 1.2750 / 1.7150：
    #   57 525 → 114 800 → 228 928 单元
    #   h_eff = 1.3544 / 0.9589 / 0.6789 mm
    #   r21 = h_med/h_fine = 1.4123，r32 = h_coarse/h_med = 1.4125（近似常数）
    "coarse": {"axial": MESH_SPECS_V4_BASE_AXIAL,
               "radial": MESH_SPECS_V4_BASE_RADIAL, "refine": 1.0},
    "medium": {"axial": MESH_SPECS_V4_BASE_AXIAL,
               "radial": MESH_SPECS_V4_BASE_RADIAL, "refine": 1.2750},
    "fine":   {"axial": MESH_SPECS_V4_BASE_AXIAL,
               "radial": MESH_SPECS_V4_BASE_RADIAL, "refine": 1.7150},
}

# ================================================================ 网格分级 v5
# 用户要求：**加密只给火焰带，非火焰带不要加密** —— 增加的单元全部花在火焰区。
#
# 做法：在 v4 基础上，只改三个火焰段的末层间距（首层间距继承不变，保证与相邻段
# 平滑衔接、无突变），其余段与 v4 完全相同：
#   * 轴向火焰带 30→80 mm   ：d1 1.7436 → 0.8718 mm（÷2.0）
#   * 轴向火焰带 80→300 mm  ：d1 4.3075 → 2.1538 mm（÷2.0）
#   * 径向火焰带 9.45→45 mm ：d1 0.6974 → 0.3487 mm（÷2.0）
# 效果（flame-band-only 加密，非火焰带逐字不变）：
#   单元数 57 525 → 103 912（+81%），全部增量在火焰带；
#   Δr @ r=20/30/40 mm：0.331/0.481/0.628 → 0.226/0.275/0.326 mm（细 32/43/48%）；
#   Δx @ x=120/200/300 mm：2.19/3.12/4.29 → 1.10/1.57/2.15 mm（细 ~50%）；
#   远场（x>300 mm、r>70 mm）几乎不变（仅因继承性略增几列）。
MESH_SPECS_V5_BASE_AXIAL = [
    {"a": 0.0,     "b": 30e-3,  "d0": 0.3000e-3, "d1": 0.3000e-3},   # 火焰稳定区（=v4）
    {"a": 30e-3,   "b": 80e-3,  "d0": None,      "d1": 0.87180e-3},  # ★ 火焰轴向 /2.0
    {"a": 80e-3,   "b": 300e-3, "d0": None,      "d1": 2.15375e-3},  # ★ 火焰轴向 /2.0
    {"a": 300e-3,  "b": 600e-3, "d0": None,      "d1": 9.97340e-3},  # 火焰尾段（=v4）
    {"a": 600e-3,  "b": L_DOMAIN, "d0": None,    "d1": 9.97340e-3},  # 远场出口（=v4）
]
MESH_SPECS_V5_BASE_RADIAL = [
    {"a": 0.0,          "b": R_JET,        "d0": 0.1600e-3, "d1": 0.1600e-3},  # 主射流（=v4）
    {"a": R_JET,        "b": R_PILOT_IN,   "d0": 0.1250e-3, "d1": 0.1250e-3},  # 喷唇（壁，=v4）
    {"a": R_PILOT_IN,   "b": R_PILOT_OUT,  "d0": None,      "d1": 0.1726e-3},  # pilot 环（=v4）
    {"a": R_PILOT_OUT,  "b": R_BURNER_OUT, "d0": 0.1750e-3, "d1": 0.1750e-3},  # 外唇（壁，=v4）
    {"a": R_BURNER_OUT, "b": 45e-3,        "d0": None,      "d1": 0.34870e-3},  # ★ 火焰带 /2.0
    {"a": 45e-3,        "b": 70e-3,        "d0": None,      "d1": 3.79760e-3},  # 出火焰过渡（=v4）
    {"a": 70e-3,        "b": 130e-3,       "d0": None,      "d1": 5.92970e-3},  # 伴流内圈（=v4）
    {"a": 130e-3,       "b": R_DOMAIN,     "d0": None,      "d1": 5.92970e-3},  # 伴流外圈（=v4）
]
MESH_SPECS_V5 = {
    # refine 因子由 scripts/_solve_v5.py 反解（目标：单元数 1 : 2 : 4）
    #   103 912 → 207 636 → 415 305 单元（1 : 1.998 : 3.997）
    "coarse": {"axial": MESH_SPECS_V5_BASE_AXIAL,
               "radial": MESH_SPECS_V5_BASE_RADIAL, "refine": 1.0},
    "medium": {"axial": MESH_SPECS_V5_BASE_AXIAL,
               "radial": MESH_SPECS_V5_BASE_RADIAL, "refine": 1.2670},
    "fine":   {"axial": MESH_SPECS_V5_BASE_AXIAL,
               "radial": MESH_SPECS_V5_BASE_RADIAL, "refine": 1.7000},
}
