"""3D 全域圆射流算例（V3）分段驱动器。

序列：冷流 60 步（species off）→ 反应段 18 段 × 25 步 = 450 步（含自持/统计）。
每段结束 autosave（脚本内每 25 步存一次），段间完全独立续算，可随时中断。

用法：
  python scripts/driver_round.py                # 跑完整序列
  python scripts/driver_round.py --start 5      # 从第 5 段续跑
  python scripts/driver_round.py --segs 4       # 只跑 4 段（快速诊断）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
ANSYS = r"D:\Program Files\ANSYS\2025R2\v252"
PY = ANSYS + r"\commonfiles\CPython\3_10\winx64\Release\python\python.exe"
RUN = ROOT / "run"
LOG = RUN / "driver_round.log"
TAG = "box3d_round"
CHUNK = 25


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with _LOG["p"].open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


_LOG = {"p": LOG}                     # 可由 --tag 改写到独立日志文件


def run_seg(args, label):
    env = dict(os.environ)
    env["PYTHONPATH"] = (ANSYS + r"\commonfiles\CPython\3_10\winx64\Release"
                         r"\Ansys\PyFluentCore")
    env["AWP_ROOT252"] = ANSYS
    cmd = [PY, "-u", str(ROOT / "scripts" / "run_box3d_edm.py")] + args
    say(f"[{time.strftime('%F %T')}] 启动 {label}: {' '.join(args)}")
    t0 = time.time()
    with _LOG["p"].open("a", encoding="utf-8") as fh:
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=fh,
                           stderr=subprocess.STDOUT, env=env)
    dt = time.time() - t0
    say(f"[{time.strftime('%F %T')}] {label} 结束 rc={p.returncode} "
        f"用时 {dt/60:.1f} min")
    return p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0,
                    help="0 = 从冷流段开始；>0 = 从第 N 个反应段续跑")
    ap.add_argument("--segs", type=int, default=18, help="反应段数（每段 25 步）")
    ap.add_argument("--cores", type=int, default=10)
    ap.add_argument("--tag", default=TAG,
                    help="case 名（默认 box3d_round；新域用 box3d_round300）")
    ap.add_argument("--mesh", default=None,
                    help="网格相对路径（默认由 run_box3d_edm.py 决定）")
    a = ap.parse_args()
    tag = a.tag
    extra = ["--mesh", a.mesh] if a.mesh else []
    if tag != TAG:                       # 不同算例写独立日志，避免互相混淆
        _LOG["p"] = RUN / f"driver_{tag}.log"

    say("=" * 76)
    say(f"3D 圆射流全域 V3 驱动器  start={a.start} segs={a.segs} "
        f"cores={a.cores} tag={tag} {time.strftime('%F %T')}")
    say("=" * 76)

    if a.start == 0:
        rc = run_seg(["--phase", "cold", "--n-cold", "60", "--n-iter", "0",
                      "--cores", str(a.cores), "--tag", tag, "--seg", "cold"]
                     + extra, "冷流 60 步")
        if rc != 0:
            say("冷流段失败，终止")
            return 1

    for i in range(a.start if a.start > 0 else 1, a.segs + 1):
        rc = run_seg(["--phase", "edm", "--resume", "--n-iter", str(CHUNK),
                      "--chunk", str(CHUNK), "--cores", str(a.cores),
                      "--tag", tag, "--seg", f"seg{i:02d}"] + extra,
                     f"反应段 seg{i:02d} ({CHUNK} 步)")
        if rc != 0:
            say(f"seg{i:02d} 失败（rc={rc}），终止；可用 --start {i} 续跑")
            return 1
    say(f"全部 {a.segs} 段完成（冷流 60 + 反应 {a.segs*CHUNK} 步）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
