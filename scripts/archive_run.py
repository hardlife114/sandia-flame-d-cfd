"""算例归档器：为每次大规模计算生成「可复现备份」清单，并可选复制大文件。

设计标准（用户要求）：**根据备份的文件可以复现这次计算**。
因此清单必须覆盖复现的全部必要条件：

  ┌ 网格 ────────── 文件 + sha256 + 生成命令（可重建）
  ├ 算例定义 ────── case.h5（内含网格指针 + 全部模型/边界/求解设置）+ sha256
  ├ 边界条件 ────── **逐项回读记录**（从驱动日志提取，不靠记忆）
  ├ 阶段序列 ────── 冷流/反应各多少步、分段方式
  ├ 求解参数 ────── 湍流/燃烧模型、离散格式、URF、伪时间步
  ├ 代码版本 ────── git commit（脚本的行为由该 commit 唯一确定）
  ├ 环境 ────────── Fluent 版本、并行核数
  └ 结果 ────────── 对标指标（用于复核重跑结果一致）

用法：
  # 生成清单（不复制大文件）
  python scripts/archive_run.py --tag box3d_round300

  # 生成清单 + 把大文件复制到备份目录并校验 sha256
  python scripts/archive_run.py --tag box3d_round300 --backup-dir D:\\flamed_backup

  # 显式指定日志与网格（历史算例的日志命名不统一时用）
  python scripts/archive_run.py --tag box3d_round \\
         --log run/driver_round.log --mesh mesh/box3d/compact_round.msh

  # 恢复：备份目录内含 BACKUP_SHA256.txt，可校验完整性
  #   sha256sum -c BACKUP_SHA256.txt
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run"
RES = ROOT / "results"
ARCH = ROOT / "archive"


def say(*a):
    print(" ".join(str(x) for x in a), flush=True)


def sha256(p: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def find_log(tag: str) -> Path | None:
    """按优先级找该算例的驱动日志。"""
    for cand in (RUN / f"driver_{tag}.log", RUN / f"log_{tag}.txt",
                 RUN / "driver_round.log", RUN / f"trn_{tag}.txt"):
        if cand.exists():
            return cand
    return None


def read(p: Path, limit: int = 400_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:                                       # noqa: BLE001
        return ""


def parse_log(txt: str) -> dict:
    """从驱动日志提取复现要素。

    兼容三种历史日志格式：
      A) driver_round.py（3D 圆进口分段接力）—— 有「全部 N 段完成（冷流 A + 反应 B 步）」首行
      B) run_box3d_mix.py（等温惰性）—— 「一阶 N 步 OK」+「[混合 k/N]」
      C) run_np_eq.py（2D 非预混）—— 命令行头「n=3000 cores=10 urf=0.5」+「迭代 100」
    """
    d: dict = {}
    # Fluent 版本与核数（dimension 可选：2D 日志写「（10 核）」，3D 写「（3D，10 核）」）
    m = re.search(r"已启动 Fluent version\s*([\d\sRr]+?)（(?:(\w+)，)?\s*(\d+)\s*核）", txt)
    if m:
        d["fluent_version"] = m.group(1).strip()
        if m.group(2):
            d["dimension"] = m.group(2)
        d["cores"] = int(m.group(3))
    # 阶段序列：格式 A
    m = re.search(r"全部\s*(\d+)\s*段完成（冷流\s*(\d+)\s*\+\s*反应\s*(\d+)\s*步）", txt)
    if m:
        d["segments"] = int(m.group(1))
        d["steps_cold"] = int(m.group(2))
        d["steps_react"] = int(m.group(3))
    else:
        # 格式 B：等温惰性混合
        m = re.search(r"一阶\s*(\d+)\s*步 OK", txt)
        if m:
            d["steps_cold"] = int(m.group(1))
        prog = re.findall(r"\[混合\s*(\d+)/(\d+)\]", txt)
        if prog:
            d["steps_react"] = max(int(p[1]) for p in prog)
            d["segments"] = 1
        # 格式 C：2D 非预混，命令行头 n=<总步数>
        if not prog:
            m = re.search(r"\bn=(\d+)\s+cores=(\d+)", txt)
            if m:
                d["steps_react"] = int(m.group(1))
                d["cores"] = int(m.group(2))
    # 分段方式
    segs = re.findall(r"反应段 seg(\d+)\s*\((\d+)\s*步\)", txt)
    if segs:
        d["segment_size"] = int(segs[0][1])
    # 边界硬校验（逐项）—— ★ 分段驱动会让每段都打印一次，必须去重
    checks = re.findall(r"\[校验\]\s*(\S+)\s*U=([\d.]+)\(应\s*([\d.]+)\)\s*T=([\d.]+)\(应\s*([\d.]+)\)", txt)
    if checks:
        seen, uniq = set(), []
        for c in checks:
            key = (c[0], c[1], c[2], c[3], c[4])
            if key in seen:
                continue
            seen.add(key)
            uniq.append({"zone": c[0], "U": float(c[1]), "U_expect": float(c[2]),
                         "T": float(c[3]), "T_expect": float(c[4])})
        d["inlet_checks"] = uniq
    # 组分显式值（同样去重）
    comps = re.findall(r"(velocity-inlet-\d+):\s*U=([\d.]+)\s*T=([\d.]+)\s*组分显式=(\{[^}]*\})", txt)
    if comps:
        seen, uniq = set(), []
        for c in comps:
            key = (c[0], c[1], c[2], c[3])
            if key in seen:
                continue
            seen.add(key)
            uniq.append({"zone": c[0], "U": float(c[1]), "T": float(c[2]),
                         "species": c[3]})
        d["inlet_species"] = uniq
    # 进口分区生效情况
    m = re.search(r"进口分区生效=(\[[^\]]*\])\s*网格缺失=([^\n]*)", txt)
    if m:
        d["zones_active"] = m.group(1)
        d["zones_missing"] = m.group(2).strip()
    # 网格文件：多种日志写法
    m = re.search(r"--mesh\s+(\S+)", txt)
    if m:
        d["mesh_arg"] = m.group(1).replace("\\", "/")
    else:
        m = re.search(r"(mesh[\\/][\w./\\-]+\.msh)", txt)
        if m:
            d["mesh_arg"] = m.group(1).replace("\\", "/")
    # 离散格式 / URF
    m = re.search(r"二阶迎风切换 OK（(\d+)\s*个方程）", txt)
    if m:
        d["second_order_equations"] = int(m.group(1))
    # URF：分段驱动可能在不同阶段用不同值，列出全部出现过的
    urfs = re.findall(r"URF\(TUI\)\s*urf=([\d.]+)", txt)
    if urfs:
        uniq_urf = sorted({float(u) for u in urfs})
        d["urf"] = uniq_urf[0] if len(uniq_urf) == 1 else uniq_urf
    # ★ 进口原始记录：不依赖单一格式，收集全部去重后的相关行
    #   （3D EDM / 等温惰性 / 2D 非预混三种日志的写法各不相同）
    recs, seen = [], set()
    for line in txt.splitlines():
        if not re.search(r"velocity-inlet-\d+", line):
            continue
        s = line.strip()
        if not s or s in seen or len(s) > 400:
            continue
        if not any(t in s for t in ("校验", "组分", "f=", "U=")):
            continue
        seen.add(s)
        recs.append(s)
    if recs:
        d["inlet_records"] = recs
    # 单步耗时
    sp = [float(x) for x in re.findall(r"([\d.]+)\s*s/步", txt)]
    if sp:
        d["sec_per_step_median"] = round(sorted(sp)[len(sp) // 2], 2)
    # 收敛证据
    if "仅 144 字节" in txt or "逐字节一致" in txt:
        d["convergence_note"] = "场数据逐字节一致（见手册 §11.20）"
    return d


def parse_rms(tag: str) -> dict:
    """从对标汇总表取该算例的逐站 RMS。"""
    f = RES / "station_rms_so_compare.csv"
    if not f.exists():
        return {}
    import csv
    rows = list(csv.DictReader(f.open(encoding="utf-8-sig")))
    key = tag.replace("cfd_", "").replace(".csv", "")
    for r in rows:
        if key in (r.get("case") or "") or key in (r.get("file") or ""):
            return r
    # 退化：按 csv 文件名匹配
    for r in rows:
        if r.get("file", "").replace(".csv", "") == key:
            return r
    return {}


def git_info() -> dict:
    def g(*a):
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                                  text=True, timeout=15).stdout.strip()
        except Exception:                                   # noqa: BLE001
            return ""
    return {"commit": g("rev-parse", "HEAD"),
            "short": g("rev-parse", "--short", "HEAD"),
            "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
            "describe": g("describe", "--tags", "--always"),
            "dirty": bool(g("status", "--porcelain"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="算例名（run/<tag>.cas.h5）")
    ap.add_argument("--mesh", default=None, help="网格路径（默认从日志解析）")
    ap.add_argument("--log", default=None,
                    help="驱动日志路径（默认按 driver_<tag>.log / log_<tag>.txt 等顺序探测）")
    ap.add_argument("--backup-dir", default=None,
                    help="若给出，把大文件复制到该目录并校验 sha256")
    ap.add_argument("--no-copy", action="store_true",
                    help="只生成清单，不复制（默认在指定 backup-dir 时复制）")
    a = ap.parse_args()

    tag = a.tag
    case = RUN / f"{tag}.cas.h5"
    dat = RUN / f"{tag}.dat.h5"
    if not case.exists():
        say(f"❌ 找不到 {case}")
        return 1

    say("=" * 78)
    say(f"归档算例：{tag}    {time.strftime('%F %T')}")
    say("=" * 78)

    if a.log:
        logp = Path(a.log)
        if not logp.is_absolute():
            logp = ROOT / logp
        if not logp.exists():
            say(f"❌ 指定的日志不存在：{logp}")
            return 1
    else:
        logp = find_log(tag)
    logtxt = read(logp) if logp else ""
    say(f"  日志来源：{logp.relative_to(ROOT) if logp else '（未找到）'}")
    info = parse_log(logtxt)
    gi = git_info()

    # ---- 网格 ----
    mesh_rel = a.mesh or info.get("mesh_arg")
    mesh = None
    if mesh_rel:
        mp = Path(mesh_rel)
        mesh = mp if mp.is_absolute() else (ROOT / mp)
        if not mesh.exists():
            mesh = None
    mesh_rec = None
    if mesh:
        say(f"  网格 {mesh.name} ({human(mesh.stat().st_size)}) … 计算 sha256")
        mesh_rec = {"path": str(mesh.relative_to(ROOT)).replace("\\", "/"),
                    "size": mesh.stat().st_size, "sha256": sha256(mesh)}

    # ---- 算例文件 ----
    files = {}
    for label, p in (("case", case), ("data", dat)):
        if p.exists():
            say(f"  {label} {p.name} ({human(p.stat().st_size)}) … 计算 sha256")
            files[label] = {"path": f"run/{p.name}", "size": p.stat().st_size,
                            "sha256": sha256(p)}

    rms = parse_rms(tag)
    manifest = {
        "tag": tag,
        "archived_at": time.strftime("%F %T"),
        "git": gi,
        "environment": {k: info.get(k) for k in
                        ("fluent_version", "dimension", "cores") if info.get(k)},
        "mesh": mesh_rec,
        "case_files": files,
        "boundary_conditions": {
            "inlet_checks": info.get("inlet_checks", []),
            "inlet_species": info.get("inlet_species", []),
            "inlet_records": info.get("inlet_records", []),
            "zones_active": info.get("zones_active"),
            "zones_missing": info.get("zones_missing"),
        },
        "solver": {
            "steps_cold": info.get("steps_cold"),
            "steps_react": info.get("steps_react"),
            "segments": info.get("segments"),
            "segment_size": info.get("segment_size"),
            "urf": info.get("urf"),
            "second_order_equations": info.get("second_order_equations"),
            "sec_per_step_median": info.get("sec_per_step_median"),
        },
        "convergence": info.get("convergence_note"),
        "metrics": rms,
        "source_log": str(logp.relative_to(ROOT)).replace("\\", "/") if logp else None,
    }

    outdir = ARCH / tag
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 人读版清单 ----
    L = []
    L.append(f"# 算例归档：{tag}")
    L.append(f"\n> 归档时间：{manifest['archived_at']}　"
             f"代码版本：`{gi['short']}` ({gi['describe']})　"
             f"分支：`{gi['branch']}`{'　**工作区有未提交改动**' if gi['dirty'] else ''}")
    L.append("\n## 复现标准\n")
    L.append("按本清单可在本机重跑出同一结果。复现所需全部要素如下：\n")
    L.append("| 要素 | 内容 |")
    L.append("|---|---|")
    L.append(f"| 代码版本 | commit `{gi['commit'] or '—'}` |")
    env = manifest["environment"]
    L.append(f"| 环境 | Fluent {env.get('fluent_version','—')} "
             f"{env.get('dimension','')} / {env.get('cores','—')} 核 |")
    if mesh_rec:
        L.append(f"| 网格 | `{mesh_rec['path']}` （{human(mesh_rec['size'])}，"
                 f"sha256 `{mesh_rec['sha256'][:16]}…`） |")
    if files.get("case"):
        L.append(f"| 算例定义 | `{files['case']['path']}` "
                 f"（{human(files['case']['size'])}，sha256 `{files['case']['sha256'][:16]}…`）"
                 f" — 内含网格指针与全部模型/边界/求解设置 |")
    if files.get("data"):
        L.append(f"| 收敛场 | `{files['data']['path']}` "
                 f"（{human(files['data']['size'])}，sha256 `{files['data']['sha256'][:16]}…`）"
                 f" — 仅用于复核，非复现必需 |")
    L.append(f"| 驱动日志 | `{manifest['source_log'] or '—'}` |")

    L.append("\n## 网格生成命令\n")
    if mesh_rec:
        mm = mesh_rec["path"]
        if "round300" in mm:
            L.append("```bash\npython scripts/gen_mesh_box3d.py --compact --round "
                     "--half-mm 150 --dmin 0.5 --dmax 10 --out " + mm + "\n```")
        elif "compact_round" in mm:
            L.append("```bash\npython scripts/gen_mesh_box3d.py --compact --round "
                     "--out " + mm + "\n```")
        else:
            L.append(f"```bash\n# 见 scripts/gen_mesh_box3d.py / gen_mesh.py，目标：{mm}\n```")

    L.append("\n## 边界条件（逐项回读记录，非回忆）\n")
    bc = manifest["boundary_conditions"]
    if bc["inlet_checks"]:
        L.append("| zone | U 实测 | U 应为 | T 实测 | T 应为 |")
        L.append("|---|---:|---:|---:|---:|")
        for c in bc["inlet_checks"]:
            L.append(f"| {c['zone']} | {c['U']} | {c['U_expect']} | "
                     f"{c['T']} | {c['T_expect']} |")
    if bc["inlet_species"]:
        L.append("\n进口组分（质量分数，日志实测）：\n")
        for c in bc["inlet_species"]:
            L.append(f"- `{c['zone']}` U={c['U']} T={c['T']} → {c['species']}")
    if bc.get("inlet_records"):
        L.append("\n日志原始记录（去重后全文，供独立核对）：\n")
        L.append("```text")
        L.extend(bc["inlet_records"])
        L.append("```")
    if not bc["inlet_checks"] and not bc.get("inlet_records"):
        L.append("（日志中未找到进口记录）")
    if bc.get("zones_active"):
        L.append(f"\n进口分区生效：{bc['zones_active']}　"
                 f"网格缺失：{bc.get('zones_missing')}")

    s = manifest["solver"]
    L.append("\n## 求解设置与阶段序列\n")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append(f"| 冷流步数 | {s.get('steps_cold','—')} |")
    L.append(f"| 反应步数 | {s.get('steps_react','—')} |")
    L.append(f"| 分段 | {s.get('segments','—')} 段 × {s.get('segment_size','—')} 步 |")
    L.append(f"| URF | {s.get('urf','—')} |")
    L.append(f"| 二阶离散方程数 | {s.get('second_order_equations','—')} |")
    L.append(f"| 单步耗时中位 | {s.get('sec_per_step_median','—')} s |")
    if manifest.get("convergence"):
        L.append(f"\n收敛证据：{manifest['convergence']}")

    if rms:
        L.append("\n## 对标结果（复现后应一致）\n")
        L.append("| 量 | 值 |")
        L.append("|---|---|")
        for k, v in rms.items():
            if k in ("case", "file", "mean") or str(k).startswith("x"):
                L.append(f"| {k} | {v} |")

    L.append("\n## 复现步骤\n")
    L.append("```bash\n"
             "# 1) 检出该版本代码\n"
             f"git checkout {gi['short']}\n\n"
             "# 2) 重建网格（若未随备份携带 .msh）\n"
             "#    命令见上「网格生成命令」\n\n"
             "# 3) 用归档的 case 直接续算，或从头重跑：\n"
             + (f"#    推荐：直接读回算例定义\n"
                f"#    run/{tag}.cas.h5 内含网格与全部设置\n"
                if files.get("case") else "")
             + "```")
    (outdir / "MANIFEST.md").write_text("\n".join(L), encoding="utf-8")
    say(f"\n  已写 {outdir.relative_to(ROOT)}\\MANIFEST.md 与 manifest.json")

    # ---- 可选：复制大文件 ----
    if a.backup_dir and not a.no_copy:
        bd = Path(a.backup_dir) / tag
        bd.mkdir(parents=True, exist_ok=True)
        say(f"\n  备份到 {bd}")
        targets = [p for p in (mesh, case, dat) if p and p.exists()]
        if logp:
            targets.append(logp)
        ok = True
        for p in targets:
            dst = bd / p.name
            if dst.exists() and sha256(dst) == sha256(p):
                say(f"    = {p.name} 已存在且校验一致，跳过")
                continue
            say(f"    → {p.name} ({human(p.stat().st_size)}) 复制中…")
            shutil.copy2(p, dst)
            h1, h2 = sha256(p), sha256(dst)
            if h1 == h2:
                say(f"      ✓ sha256 校验通过 {h1[:16]}…")
            else:
                say(f"      ❌ 校验失败 {p.name}: {h1[:16]} != {h2[:16]}")
                ok = False
        says = "全部校验通过" if ok else "**存在校验失败**"
        say(f"  备份完成：{says}")
        (bd / "BACKUP_SHA256.txt").write_text(
            "\n".join(f"{sha256(bd / p.name)}  {p.name}" for p in targets
                      if (bd / p.name).exists()), encoding="utf-8")

    # ---- 复现充分性自检 ----
    say("\n  【复现充分性自检】")
    checks = [
        ("网格可重建或已备份", bool(mesh_rec)),
        ("算例定义 case.h5 在位", bool(files.get("case"))),
        ("边界条件有逐项回读记录",
         bool(manifest["boundary_conditions"]["inlet_checks"]
              or manifest["boundary_conditions"].get("inlet_records"))),
        ("阶段序列已记录", bool(s.get("steps_react") or s.get("steps_cold"))),
        ("代码版本已锁定", bool(gi["commit"])),
        ("工作区干净（无未提交改动）", not gi["dirty"]),
    ]
    allok = True
    for name, ok in checks:
        say(f"    {'✓' if ok else '✗'} {name}")
        allok &= ok
    say(f"  → {'✅ 满足「可复现」标准' if allok else '⚠️ 有缺项，见上'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
