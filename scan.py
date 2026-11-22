"""大厂官网实习岗位监控 · 主程序

用法：
    python scan.py                                  # 默认 4 个关键词
    python scan.py --keyword 数据分析 --pages 5      # 指定关键词与翻页数
    python scan.py --days 14                        # 只要最近 14 天发布的

输出 data/jobs-YYYYMMDD.csv，字段含发布时间、职位 ID、直链、JD 摘要。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sites import bytedance, tencent  # noqa: E402

DATA = ROOT / "data" / "exports"
SEEN_PATH = ROOT / "data" / "snapshots" / "seen.json"   # 成品表统一放 exports，看板从这里取最新

DIRECTION_WORDS = ["数据分析", "商业分析", "经营分析", "数据科学", "数据挖掘", "策略分析",
                   "策略运营", "数据运营", "用户增长", "战略分析", "数分", "商业智能"]
SKILL_WORDS = {"sql": 8, "python": 6, "ab实验": 8, "ab test": 8, "实验": 5, "指标体系": 8,
               "归因": 6, "看板": 5, "tableau": 5, "power bi": 6, "hive": 4, "数据仓库": 3}
OFFTOPIC = ["安全模型", "隐私安全", "销售运营", "客服", "审核", "标注"]




def load_seen() -> dict:
    """已见过的岗位 → 首次发现日期。腾讯等不公开发布时间的公司靠它算新鲜度。"""
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_seen(seen: dict) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")


def stamp_freshness(jobs, seen: dict) -> None:
    """给每个岗位补 first_seen / fresh_days：官方有发布时间就用官方的，没有就用首次发现。"""
    today = date.today()
    for job in jobs:
        key = f"{job.company}::{job.job_id}"
        first = seen.get(key) or today.isoformat()
        seen[key] = first
        job.first_seen = first
        try:
            job.first_seen_days = (today - date.fromisoformat(first)).days
        except Exception:
            job.first_seen_days = -1
        if job.published_days >= 0:
            job.fresh_days = job.published_days
            job.fresh_source = "official"
        else:
            job.fresh_days = job.first_seen_days
            job.fresh_source = "first_seen"


def load_directions():
    """读 config/keywords.yaml 的方向白名单与排除词；读不到就用兜底四条。"""
    fallback = [("数据分析", ["数据分析", "数分"]), ("商业分析", ["商业分析"]),
                ("数据科学", ["数据科学"]), ("策略运营", ["策略运营"])]
    path = ROOT / "config" / "keywords.yaml"
    if not path.exists():
        return fallback, []
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return fallback, []
    items = ((data.get("directions") or {}).get("enabled")) or []
    rules = [(d["name"], d.get("keywords") or [d["name"]]) for d in items if d.get("name")]
    return (rules or fallback), list(data.get("exclude") or [])


def pick_direction(title, rules):
    for name, kws in rules:
        if any(k in title for k in kws):
            return name
    return ""


def score(job) -> tuple[float, list[str]]:
    reasons: list[str] = []
    total = 60.0

    hit = [w for w in DIRECTION_WORDS if w in job.title]
    if hit:
        total += 20
        reasons.append(f"方向「{hit[0]}」")
    else:
        total -= 30
        reasons.append("标题非目标方向")

    blob = (job.title + " " + job.description + " " + job.requirement).lower()
    for word, pts in SKILL_WORDS.items():
        if word in blob:
            total += pts
            reasons.append(f"{word}+{pts}")

    if job.city.startswith(("北京", "上海")):
        total += 6
        reasons.append("北京/上海+6")
    elif job.city in ("杭州", "深圳"):
        total += 3
        reasons.append(f"{job.city}+3")

    off = [w for w in OFFTOPIC if w in job.title]
    if off:
        total -= 12
        reasons.append(f"跑偏「{off[0]}」-12")

    days = job.fresh_days if job.fresh_days is not None else job.published_days
    if days is not None and days >= 0:
        if days <= 7:
            total += 8
            reasons.append("近7天+8")
        elif days <= 30:
            total += 4
            reasons.append("近30天+4")

    return round(total, 1), reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", action="append")
    parser.add_argument("--pages", type=int, default=40, help="每个关键词最多翻几页（每页 100 条）")
    parser.add_argument("--days", type=int, default=0, help="只要最近 N 天发布的，0=不限")
    parser.add_argument("--all", action="store_true", help="连非实习岗一起导出")
    parser.add_argument("--company", action="append",
                        help="只抓指定公司：bytedance / tencent，可重复；默认两家都抓")
    args = parser.parse_args()

    keywords = args.keyword or ["数据分析", "商业分析", "经营分析", "策略运营",
                                  "数据科学", "用户增长", "风控策略"]
    DATA.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    companies = [c.lower() for c in (args.company or ["bytedance", "tencent"])]
    collected = []

    if "bytedance" in companies:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True, args=["--no-proxy-server"])
            ctx = browser.new_context(locale="zh-CN",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
            page = ctx.new_page()
            for kw in keywords:
                print(f"\n[字节跳动] 关键词「{kw}」")
                collected.extend(bytedance.scan(page, kw, max_pages=args.pages))
            browser.close()

    if "tencent" in companies:
        print("\n[腾讯] 日常实习（纯 HTTP，无需浏览器）")
        collected.extend(tencent.scan(keywords, verbose=True))

    uniq: dict[str, object] = {}
    for job in collected:
        uniq.setdefault(f"{job.company}::{job.job_id or job.title}", job)
    jobs = list(uniq.values())
    def keep_intern(job):
        if job.company == "腾讯":
            return tencent.is_intern(job)
        return bytedance.is_intern(job)

    interns = jobs if args.all else [j for j in jobs if keep_intern(j)]
    if args.days:
        interns = [j for j in interns if 0 <= (j.fresh_days if j.fresh_days is not None else -1) <= args.days]

    # 先统一补首次发现时间，再算新鲜度（腾讯等没有官方发布时间）
    seen = load_seen()
    stamp_freshness(interns, seen)
    save_seen(seen)

    # 方向白名单：不在名单里的岗位直接丢掉（不再写进 CSV）
    rules, excludes = load_directions()
    before = len(interns)
    matched = []
    for job in interns:
        direction = pick_direction(job.title, rules)
        if not direction:
            continue
        if any(w in job.title for w in excludes):
            continue
        job.direction = direction
        matched.append(job)
    interns = matched
    print(f"\n方向过滤：{before} → {len(interns)}（保留 {'、'.join(n for n, _ in rules)}）")

    rows = []
    for job in interns:
        s, reasons = score(job)
        rows.append({**job.to_dict(), "score": s, "reasons": "；".join(reasons)})
    rows.sort(key=lambda r: (-r["score"], r["published_days"]))

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = DATA / f"jobs-{stamp}.csv"
    fields = ["score", "company", "title", "city", "batch", "work_type", "direction", "category",
              "publish_time", "published_days", "first_seen", "first_seen_days",
              "fresh_days", "fresh_source", "job_id", "url", "reasons",
              "description", "requirement"]
    for attempt in range(3):
        try:
            with out.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for r in rows:
                    writer.writerow({k: r.get(k, "") for k in fields})
            break
        except PermissionError:
            out = out.with_name(out.stem + f"-{attempt + 2}.csv")
    else:
        raise SystemExit("CSV 写不进去（文件被占用），请关掉 Excel 再跑")

    print(f"\n{'=' * 78}")
    print(f"抓到 {len(jobs)} 个岗位 → 实习类 {len(interns)} 个（筛选后 {len(rows)} 个）")
    print(f"导出：{out}\n")
    print(f"{'分数':<6}{'发布':<12}{'岗位':<34}{'城市':<10}{'批次':<12}ID")
    print("-" * 88)
    for r in rows[:30]:
        print(f"{r['score']:<6}{r['publish_time']:<12}{r['title'][:32]:<34}{r['city'][:8]:<10}"
              f"{r['batch'][:10]:<12}{r['job_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
