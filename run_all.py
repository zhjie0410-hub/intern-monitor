"""跑所有已确认接口的公司：抓取 → 合并 → 出 CSV → 重建看板。

用法：
    python run_all.py                      # 跑全部
    python run_all.py --only 得物 京东      # 只跑指定公司
    python run_all.py --pages 3            # 每家最多翻 3 页（调试用）
"""

from __future__ import annotations

import argparse
import csv
import os
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "shixiseng-auto" / ".pkgs"))
sys.path.insert(0, str(ROOT / "src"))

from scanners import generic, specs  # noqa: E402

KEYWORDS = ["数据分析", "商业分析", "经营分析", "策略运营", "数据科学", "用户增长"]

DATA = ROOT / "data" / "exports"

# 详情页 URL 模板（已用真实 ID 验证标题能对上）
DETAIL_URLS = {
    "美团": "https://zhaopin.meituan.com/web/position/detail?jobUnionId={id}",
    "网易": "https://hr.163.com/job-detail.html?id={id}",
    "小红书": "https://job.xiaohongshu.com/campus/position/{id}",
    "快手": "https://zhaopin.kuaishou.cn/recruit/e/#/official/trainee/job-info/{id}",
    # 以下未验证到可用的详情页，回退到列表页
    "京东": "https://campus.jd.com/#/jobs",
    "得物": "https://campus.dewu.com/578078/position/list",
    "拼多多": "https://careers.pddglobalhr.com/campus/intern",
    "小米": "https://hr.xiaomi.com/website/opportunities.html?project=%E5%AE%9E%E4%B9%A0",
    "阿里巴巴": "https://campus-talent.alibaba.com/campus/position?batchId=100000560002",
    "蚂蚁": "https://talent.antgroup.com/campus-full-list?type=campus_intern&batchId=25051200066269",
}
LOG_DIR = ROOT / "logs"


def load_directions():
    path = ROOT / "config" / "keywords.yaml"
    fallback = [("数据分析", ["数据分析", "数分"]), ("商业分析", ["商业分析"]),
                ("数据科学", ["数据科学"]), ("策略运营", ["策略运营"]),
                ("经营分析", ["经营分析"]), ("用户增长", ["用户增长", "增长分析"]),
                ("风控策略", ["风控策略"])]
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items = ((data.get("directions") or {}).get("enabled")) or []
        rules = [(d["name"], d.get("keywords") or [d["name"]]) for d in items if d.get("name")]
        return (rules or fallback), list(data.get("exclude") or [])
    except Exception:
        return fallback, []


def pick_direction(title: str, rules) -> str:
    for name, kws in rules:
        if any(k in title for k in kws):
            return name
    return ""


def score(job: dict) -> tuple[float, list[str]]:
    reasons: list[str] = []
    total = 60.0
    if job.get("direction"):
        total += 20
        reasons.append(f"方向「{job['direction']}」")
    blob = (job.get("title", "") + " " + job.get("description", "") + " " + job.get("requirement", "")).lower()
    for word, pts in {"sql": 8, "python": 6, "ab实验": 8, "ab测试": 8, "指标体系": 8,
                      "归因": 6, "可视化": 5, "tableau": 5, "hive": 4}.items():
        if word in blob:
            total += pts
            reasons.append(f"{word}+{pts}")
    city = job.get("city", "")
    if "北京" in city or "上海" in city:
        total += 6
        reasons.append("北京/上海+6")
    days = job.get("published_days", -1)
    if 0 <= days <= 7:
        total += 8
        reasons.append("近7天+8")
    elif 0 <= days <= 30:
        total += 4
        reasons.append("近30天+4")
    return round(total, 1), reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="只跑这些公司")
    ap.add_argument("--pages", type=int, default=30, help="每家最多翻几页")
    args = ap.parse_args()

    import os

    from playwright.sync_api import sync_playwright

    DATA.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    log_path = LOG_DIR / f"run-all-{stamp}.log"
    logs: list[str] = []

    def say(msg: str) -> None:
        print(msg)
        logs.append(msg)

    all_jobs: list[dict] = []
    def want(name: str) -> bool:
        if not args.only:
            return True
        return any(o in name or name in o for o in args.only)

    selected = [s for s in specs.SPECS if want(s["name"])]

    with sync_playwright() as p:
        # 本机用 msedge（能过部分站点的 TLS/WAF）；CI 上没有 msedge，回退到自带 chromium
        channel = os.environ.get("DSH_BROWSER_CHANNEL", "msedge").strip()
        launch_kwargs = {"headless": True, "args": ["--no-proxy-server"]}
        if channel:
            launch_kwargs["channel"] = channel
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as exc:
            print(f"启动 {channel or 'chromium'} 失败（{type(exc).__name__}），改用自带 chromium")
            browser = p.chromium.launch(headless=True, args=["--no-proxy-server"])
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        for spec in selected:
            say(f"\n{'=' * 70}\n[{spec['name']}] {spec['entry']}")
            jobs = []
            for attempt in range(1, 4):      # 最多 3 次（有些 SPA 请求时好时坏）
                page = ctx.new_page()
                try:
                    strategy = spec.get("strategy", "click" if spec.get("signed") else "replay")
                    if strategy == "click":
                        jobs = generic.scan_by_click(ctx, page, spec, max_pages=min(args.pages, 10))
                    elif strategy == "nav":
                        jobs = generic.scan_by_nav(ctx, page, spec, max_pages=args.pages)
                    else:
                        jobs = generic.scan(ctx, page, spec)
                except Exception as exc:
                    say(f"      ⚠️ 第 {attempt} 次异常 {type(exc).__name__}: {str(exc)[:60]}")
                finally:
                    page.close()
                if jobs:
                    if attempt > 1:
                        say(f"      （第 {attempt} 次尝试成功）")
                    break
                if attempt < 3:
                    say(f"      第 {attempt} 次没拿到，3 秒后重试")
                    import time as _t
                    _t.sleep(3)
            say(f"      → {len(jobs)} 条")
            for j in jobs[:3]:
                say(f"        {j['title'][:34]:<36} {j['city'][:12]:<14} {j['publish_time'] or '-'}")
            all_jobs.extend(jobs)

        # ---- 老适配器（实现方式与引擎不同，但结果格式一致）----
        def want_legacy(name: str) -> bool:
            return (not args.only) or any(o in name or name in o for o in args.only)

        if want_legacy("字节跳动"):
            try:
                from sites import bytedance as bd
                say(f"\n{'=' * 70}\n[字节跳动] 老适配器（URL 翻页 current/limit）")
                page = ctx.new_page()
                total = 0
                for kw in KEYWORDS:
                    jobs = bd.scan(page, kw, limit=100, max_pages=min(args.pages, 10), verbose=False)
                    total += len(jobs)
                    all_jobs.extend(dict(vars(j)) if not isinstance(j, dict) else j for j in jobs)
                page.close()
                say(f"      → {total} 条")
            except Exception as exc:
                say(f"      ⚠️ 字节失败 {type(exc).__name__}: {str(exc)[:70]}")

        if want_legacy("腾讯"):
            try:
                from sites import tencent as tc
                say(f"\n{'=' * 70}\n[腾讯] 老适配器（纯 HTTP）")
                total = 0
                for kw in KEYWORDS:
                    jobs = tc.scan([kw], verbose=False)
                    total += len(jobs)
                    all_jobs.extend(dict(vars(j)) if not isinstance(j, dict) else j for j in jobs)
                say(f"      → {total} 条")
            except Exception as exc:
                say(f"      ⚠️ 腾讯失败 {type(exc).__name__}: {str(exc)[:70]}")

        browser.close()

    # 方向过滤 + 打分
    rules, excludes = load_directions()
    say(f"\n方向白名单：{'、'.join(n for n, _ in rules)}")
    kept: list[dict] = []
    import re as _re

    # 全局去重：同一岗位会被多个关键词命中，各关键词内部去重管不到
    deduped: list[dict] = []
    index: dict[str, dict] = {}
    dup = 0
    for job in all_jobs:
        # 同一岗位在不同城市会各有编号，这里按「公司+标题+发布时间」合并城市
        key = f"{job['company']}::{job['title']}::{job.get('publish_time', '')}"
        if key in index:
            dup += 1
            prev = index[key]
            cities = [c for c in (prev.get("city") or "").split("/") if c]
            for c in (job.get("city") or "").split("/"):
                if c and c not in cities:
                    cities.append(c)
            prev["city"] = "/".join(cities)
            continue
        index[key] = job
        deduped.append(job)
    if dup:
        say(f"去重：{len(all_jobs)} → {len(deduped)}（重复 {dup} 条）")
    all_jobs = deduped

    before = len(all_jobs)
    grade_skip = 0
    for job in all_jobs:
        title = job["title"]
        blob = title + " " + (job.get("batch") or "")
        # 28 届可用性：纯 27 届校招的岗位投不了，直接剔除
        if _re.search(r"27届|2027届", blob) and "28届" not in blob and "实习" not in blob:
            grade_skip += 1
            continue
        if _re.search(r"校招|应届生", blob) and "实习" not in blob:
            grade_skip += 1
            continue
        direction = pick_direction(job["title"], rules)
        if not direction:
            continue
        if any(w in job["title"] for w in excludes):
            continue
        job["direction"] = direction
        s, why = score(job)
        job["score"] = s
        job["reasons"] = "；".join(why)
        tpl = DETAIL_URLS.get(job["company"])
        if tpl:
            job["url"] = tpl.format(id=job.get("job_id") or "")
        kept.append(job)
    kept.sort(key=lambda x: -x["score"])
    say(f"方向过滤：{before} → {len(kept)}（剔除非28届可用 {grade_skip} 条）")

    if not kept:
        say("没有任何岗位，退出")
        log_path.write_text("\n".join(logs), encoding="utf-8")
        return 1

    out = DATA / f"jobs-{stamp}.csv"
    fields = ["score", "company", "title", "city", "batch", "work_type", "direction",
              "publish_time", "published_days", "job_id", "url", "reasons", "description", "requirement"]
    for attempt in range(3):
        try:
            with out.open("w", encoding="utf-8-sig", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for job in kept:
                    w.writerow({k: job.get(k, "") for k in fields})
            break
        except PermissionError:
            out = out.with_name(f"{out.stem}-{attempt + 2}.csv")
    say(f"导出：{out}（{len(kept)} 条）")

    log_path.write_text("\n".join(logs), encoding="utf-8")
    say(f"日志：{log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
