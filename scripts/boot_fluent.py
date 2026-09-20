"""启动一个常驻的 Fluent 求解器服务（2D 双精度），供后续脚本反复连接。

必须以管理员身份运行——Fluent 启动器 fluent.exe 带 RUNASADMIN 兼容性标志，
非提权进程调用会直接返回 WinError 740。见 decks/run_flamed.bat。

启动成功后：
  - Fluent 以无 GUI 模式常驻，监听本地 remoting 端口
  - 服务器信息写入 run/ 目录下的 serverinfo-*.txt
  - 就绪标志写入 run/fluent_ready.txt（含版本与 serverinfo 路径）
  - watchdog 关闭，客户端脚本退出后 Fluent 仍存活，便于反复迭代

清理：运行 scripts/close_fluent.py，或在 Fluent 控制台执行 exit。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run"
ANSYS_ROOT = Path(r"D:\Program Files\ANSYS\2025R2\v252")

# AWP_ROOT<ver> 是 PyFluent 查找安装的唯一依据，本机未设置该环境变量
os.environ["AWP_ROOT252"] = str(ANSYS_ROOT)
# 让 Fluent 把 serverinfo 写到算例 run 目录，便于客户端定位
os.environ["SERVER_INFO_DIR"] = str(RUN)
os.environ["FLUENT_AUTOMATIC_TRANSCRIPT"] = "0"
os.environ.pop("PYFLUENT_SHOW_SERVER_GUI", None)

RUN.mkdir(parents=True, exist_ok=True)
log = RUN / "boot_fluent.log"


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


say("=" * 70)
say(time.strftime("%Y-%m-%d %H:%M:%S"), "启动 Fluent 常驻服务")
say("AWP_ROOT252 =", os.environ["AWP_ROOT252"])
say("SERVER_INFO_DIR =", os.environ["SERVER_INFO_DIR"])

try:
    import ansys.fluent.core as pyfluent
except Exception as exc:                                    # noqa: BLE001
    say("FATAL: 无法导入 PyFluent:", type(exc).__name__, exc)
    sys.exit(1)

say("PyFluent", pyfluent.__version__)

try:
    solver = pyfluent.launch_fluent(
        mode="solver",
        dimension=2,
        precision="double",
        processor_count=4,           # 许可证实测支持 4 路并行
        ui_mode="no_gui",
        start_transcript=False,
        start_watchdog=False,        # 客户端退出后不杀 Fluent
        cleanup_on_exit=False,
    )
except Exception as exc:                                    # noqa: BLE001
    say("FATAL: 启动失败:", type(exc).__name__)
    say(str(exc)[:3000])
    sys.exit(2)

version = solver.get_fluent_version()
say("启动成功，Fluent 版本:", version)
say("scheme 自检 (+ 1 2) =", solver.scheme_eval.scheme_eval("(+ 1 2)"))

# 找出 serverinfo 文件
infos = sorted(RUN.glob("serverinfo*.txt"), key=lambda p: p.stat().st_mtime)
info = infos[-1] if infos else None
say("serverinfo 文件:", info)

marker = RUN / "fluent_ready.txt"
marker.write_text(
    json.dumps(
        {
            "version": str(version),
            "server_info": str(info) if info else None,
            "ready_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
say("就绪标志写入:", marker)
say("Fluent 保持常驻。客户端脚本可用 connect_to_fluent 连接。")
say("=" * 70)
