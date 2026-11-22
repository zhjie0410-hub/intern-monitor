"""针对已知入口的站点，抓「岗位列表接口」。

和 probe_company.py 的区别：这个脚本只关心一件事——
在页面加载过程中，哪一个 XHR 响应里**装有岗位数组**，字段结构是什么，有没有时间字段。

用法：
    python tools/probe_api.py            # 跑内置清单
    python tools/probe_api.py --only 京东
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "shixiseng-auto" / ".pkgs"))

OUT = ROOT / "data" / "probe"

# 用户截图提供的真实「实习」入口
SITES = [
    ("京东", "https://campus.jd.com/#/jobs"),
    ("美团", "https://zhaopin.meituan.com/web/campus"),
    ("小红书", "https://job.xiaohongshu.com/campus/intern"),
    ("阿里巴巴", "https://campus-talent.alibaba.com/campus/position?batchId=100000560002"),
    ("蚂蚁", "https://talent.antgroup.com/campus-full-list?type=campus_intern&batchId=25051200066269"),
    ("小米", "https://hr.xiaomi.com/website/opportunities.html?project=%E5%AE%9E%E4%B9%A0&q=%E6%95%B0%E6%8D%AE%E5%88%86%E6%9E%90"),
    ("米哈游", "https://jobs.mihoyo.com/#/campus/position?jobName=&projectIds%5B0%5D=4"),
]

TITLE_KEYS = ("title", "name", "jobname", "positionname", "postname", "jobtitle", "position")
TIME_KEYS = ("publish", "update", "create", "refresh", "time", "date")


def looks_like_jobs(data) -> tuple[bool, list | None]:
    """在 JSON 里找长度>=3、且字段像岗位的数组。"""
    best = None

    def walk(obj, depth=0):
        nonlocal best
        if depth > 5:
            return
        if isinstance(obj, dict):
            for _, v in obj.items():
                walk(v, depth + 1)
        elif isinstance(obj, list) and len(obj) >= 3 and isinstance(obj[0], dict):
            keys = [str(k).lower() for k in obj[0].keys()]
            if any(any(t in k for t in TITLE_KEYS) for k in keys):
                if best is None or len(obj) > len(best):
                    best = obj
            for item in obj[:3]:
                walk(item, depth + 1)

    walk(data)
    return (best is not None), best


def field_report(items: list) -> dict:
    first = items[0]
    keys = list(first.keys())
    time_fields = [k for k in keys if any(t in k.lower() for t in TIME_KEYS)]
    sample = {k: str(first[k])[:60] for k in keys[:8]}
    return {"count": len(items), "keys": keys[:16], "time_fields": time_fields, "sample": sample}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只跑某一家")
    ap.add_argument("--wait", type=int, default=8000)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True, args=["--no-proxy-server"])
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

        for name, url in SITES:
            if args.only and args.only not in name:
                continue
            page = ctx.new_page()
            hits: list[dict] = []

            def on_resp(r, bucket=hits):
                try:
                    if r.request.resource_type not in ("xhr", "fetch"):
                        return
                    ct = r.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    data = r.json()
                    ok, items = looks_like_jobs(data)
                    if not ok:
                        return
                    bucket.append({
                        "method": r.request.method,
                        "url": r.url.split("?")[0],
                        "query": r.url.split("?")[1][:200] if "?" in r.url else "",
                        "body": (r.request.post_data or "")[:300],
                        **field_report(items),
                    })
                except Exception:
                    pass

            page.on("response", on_resp)
            entry = {"company": name, "entry": url, "probed_at": datetime.now().isoformat(timespec="seconds")}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(args.wait)
                txt = page.evaluate("() => (document.body.innerText||'').replace(/\\s+/g,' ')")
                entry["text_len"] = len(txt)
                entry["head"] = txt[:200]
                entry["apis"] = sorted(hits, key=lambda x: -x["count"])[:4]
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            page.close()

            results.append(entry)
            print(f"\n{'=' * 70}\n[{name}] {entry.get('text_len', 0)} 字")
            if entry.get("error"):
                print("   失败:", entry["error"][:90])
                continue
            if not entry["apis"]:
                print("   ❌ 没有找到岗位数组接口（可能需要再点一层筛选）")
                continue
            for a in entry["apis"][:2]:
                print(f"   ✅ {a['method']} {a['url'].replace('https://', '')[:60]}")
                print(f"      {a['count']} 条 | 时间字段: {a['time_fields'] or '❌ 无'}")
                print(f"      字段: {a['keys'][:10]}")
                if a["body"]:
                    print(f"      body: {a['body'][:110]}")

        browser.close()

    (OUT / "api-probe.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已保存 {OUT / 'api-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
