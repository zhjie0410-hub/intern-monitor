"""通用探针：走查一家公司的「实习入口 → 岗位列表 → 字段口径」。

用法：
    python tools/probe_company.py --name 京东 --url https://campus.jd.com/ --click 日常实习
    python tools/probe_company.py --name 美团 --url https://zhaopin.meituan.com/web/position

它做五件事：
    1. 打开入口页，记录最终 URL / 正文长度
    2. 扫描页面上和「实习」相关的可点文字
    3. 命中 --click 就点进去，记录 URL 变化
    4. 拦截所有 XHR，找出像「岗位列表」的接口（含路径 + 请求体）
    5. 检查接口 JSON 有没有时间字段 → 决定发布时间口径

结果同时打印并写入 data/probe/<公司>.json。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "shixiseng-auto" / ".pkgs"))

PROBE_DIR = ROOT / "data" / "probe"

# 判断「像岗位列表接口」的关键词
LIST_HINTS = ("job", "position", "search", "list", "recruit", "zhiwei", "vacanc")
# 时间字段线索
TIME_HINTS = ("publish", "updatetime", "update_time", "createtime", "create_time",
              "refresh", "date", "time")

INTERN_TEXT = re.compile(r"日常实习|实习生|实习")


def walk_time_fields(obj, path="", depth=0) -> list[str]:
    """在 JSON 里找所有可能是时间的字段名。"""
    found = []
    if depth > 4:
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            low = str(k).lower()
            if any(h in low for h in TIME_HINTS) and not isinstance(v, (dict, list)):
                found.append(f"{path}.{k} = {str(v)[:30]}")
            found += walk_time_fields(v, f"{path}.{k}", depth + 1)
    elif isinstance(obj, list) and obj:
        found += walk_time_fields(obj[0], f"{path}[0]", depth + 1)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--click", default="", help="要点击的文字，如 日常实习")
    ap.add_argument("--wait", type=int, default=6000)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    report: dict = {"company": args.name, "entry": args.url, "probed_at": datetime.now().isoformat(timespec="seconds")}
    calls: list[dict] = []
    payloads: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True, args=["--no-proxy-server"])
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        page = ctx.new_page()

        def on_resp(r):
            try:
                if r.request.resource_type not in ("xhr", "fetch"):
                    return
                if not any(h in r.url.lower() for h in LIST_HINTS):
                    return
                entry = {"method": r.request.method, "url": r.url.split("?")[0],
                         "body": (r.request.post_data or "")[:300]}
                calls.append(entry)
                if "json" in r.headers.get("content-type", ""):
                    data = r.json()
                    payloads.append({"url": entry["url"], "sample": json.dumps(data, ensure_ascii=False)[:400],
                                     "time_fields": walk_time_fields(data)[:8]})
            except Exception:
                pass

        page.on("response", on_resp)
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(args.wait)
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            report["ok"] = False
            print(f"[{args.name}] 打不开：{report['error']}")
            _save(report)
            browser.close()
            return 1

        info = page.evaluate("""() => {
          const t = (document.body.innerText || '').replace(/\\s+/g, ' ');
          const clicks = Array.from(document.querySelectorAll('a,button,span,div,li'))
            .filter(e => e.children.length === 0)
            .map(e => (e.innerText || '').trim())
            .filter(s => s && s.length <= 12);
          return {url: location.href, len: t.length, head: t.slice(0, 300),
                  intern_texts: [...new Set(clicks.filter(s => /实习/.test(s)))].slice(0, 10)};
        }""")
        report.update({
            "ok": True,
            "final_url": info["url"],
            "text_len": info["len"],
            "page_head": info["head"][:300],
            "intern_clickables": info["intern_texts"],
        })
        print(f"[{args.name}] 打开成功：{info['url'][:70]}")
        print(f"   正文 {info['len']} 字｜含实习文字：{info['intern_texts'][:6]}")

        if args.click:
            clicked = False
            try:
                page.get_by_text(args.click, exact=True).first.click(timeout=6000)
                clicked = True
            except Exception:
                for kw in ("日常实习", "实习生", "实习"):
                    try:
                        page.get_by_text(kw, exact=False).first.click(timeout=4000)
                        clicked, args.click = True, kw
                        break
                    except Exception:
                        continue
            page.wait_for_timeout(4000)
            report["clicked"] = {"target": args.click, "ok": clicked, "url_after": page.url}
            print(f"   点击「{args.click}」→ {'成功' if clicked else '失败'}，URL：{page.url[:70]}")

        browser.close()

    # 汇总接口
    uniq = []
    seen = set()
    for c in calls:
        key = (c["method"], c["url"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    report["apis"] = uniq[:12]
    report["payloads"] = payloads[:6]
    has_time = any(p.get("time_fields") for p in payloads)
    report["has_time_field"] = has_time

    print(f"\n   疑似列表接口 {len(uniq)} 个：")
    for a in uniq[:6]:
        print(f"     {a['method']:<5} {a['url'].replace('https://', '')[:66]}")
        if a["body"]:
            print(f"           body: {a['body'][:100]}")
    print(f"\n   接口里有时间字段：{'✅ 有' if has_time else '❌ 没有'}")
    for p in payloads[:3]:
        if p.get("time_fields"):
            print(f"     {p['url'][:50]} → {p['time_fields'][:4]}")

    _save(report)
    return 0


def _save(report: dict) -> None:
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    out = PROBE_DIR / f"{report['company']}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"   → 已保存 {out.relative_to(ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
