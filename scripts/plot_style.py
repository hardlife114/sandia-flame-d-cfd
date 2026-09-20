"""matplotlib 中文显示统一配置（ANSYS 自带 matplotlib 不含 CJK 字体）。

用法：
    from plot_style import use_cjk
    use_cjk()
"""
from __future__ import annotations

from pathlib import Path

_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
    r"C:\Windows\Fonts\Deng.ttf",      # 等线
)


def use_cjk() -> str | None:
    """注册系统 CJK 字体并把 matplotlib 默认字体切过去；返回字体名或 None。"""
    import matplotlib
    from matplotlib import font_manager
    import matplotlib.pyplot as plt

    for c in _CANDIDATES:
        p = Path(c)
        if not p.exists():
            continue
        try:
            font_manager.fontManager.addfont(str(p))
            name = font_manager.FontProperties(fname=str(p)).get_name()
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            matplotlib.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            return name
        except Exception:                                    # noqa: BLE001
            continue
    plt.rcParams["axes.unicode_minus"] = False
    return None
