"""针对京东/美团/蚂蚁的深挖探针。

难点：这三家的岗位列表接口没在前端首屏触发——
  - 京东：要先进「JD YOUNG-实习生计划」这个招聘项目
  - 美团：点「日常实习」后路由会变，接口在新路由里
  - 蚂蚁：岗位列表可能在 hrcareersweb 主机上，首屏只拉了埋点配置

所以这个脚本不预设"接口长什么样"，而是把**所有体积较大的 XHR** 都列出来，
让人一眼看出哪个是岗位列表（按响应大小 + 是否含 title/name 字段判断）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "shixiseng-auto" / ".pkgs"))

CASES = [
    ("京东", "https://campus.jd.com/#/jobs", ["JD YOUNG-实习生计划", "实习生", "JD YOUNG"]),
    ("美团", "https://zhaopin.meituan.com/web/campus", ["日常实习"]),
    ("蚂蚁", "https://talent.antgroup.com/campus-full-list?type=campus_intern&batchId=25051200066269", []),
]


def summarize(data) -> tuple[int, list[str], bool]:
    """返回(最大数组长度, 该数组首条的字段名, 是否含时间字段)。"""
    best_len, best_keys, has_time = 0, [], False

    def walk(obj, depth=0):
        nonlocal best_len, best_keys, has_time
        if depth > 6:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if any(t in str(k).lower() for t in ("publish", "update", "create", "time", "date")):
                    if not isinstance(v, (dict, list)):
                        has_time = True
                walk(v, depth + 1)
        elif isinstance(obj, list):
            if obj and isinstance(obj[0], dict) and len(obj) > best_len:
                best_len, best_keys = len(obj), list(obj[0].keys())[:10]
            for item in obj[:2]:
                walk(item, depth + 1)

    walk(data)
    return best_len, best_keys, has_time


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True, args=["--no-proxy-server"])
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 950},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

        for name, url, clicks in CASES:
            page = ctx.new_page()
            rows: list[tuple] = []

            def on_resp(r, bucket=rows):
                try:
                    if r.request.resource_type not in ("xhr", "fetch"):
                        return
                    body = r.body()
                    if len(body) < 800:
                        return
                    info = {"m": r.request.method, "u": r.url.split("?")[0],
                            "q": (r.url.split("?")[1][:150] if "?" in r.url else ""),
                            "size": len(body), "n": 0, "keys": [], "time": False, "ct": r.headers.get("content-type", "")[:20]}
                    if "json" in info["ct"]:
                        n, keys, t = summarize(r.json())
                        info.update(n=n, keys=keys, time=t)
                    bucket.append(info)
                except Exception:
                    pass

            page.on("response", on_resp)
            print(f"\n{'=' * 72}\n[{name}] {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
                for c in clicks:
                    try:
                        page.get_by_text(c, exact=False).first.click(timeout=5000)
                        page.wait_for_timeout(4500)
                        print(f"   点击「{c}」成功 → {page.url[:70]}")
                        break
                    except Exception:
                        continue
                for _ in range(2):
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(1200)
                print(f"   当前 URL: {page.url[:80]}")
            except Exception as exc:
                print(f"   失败 {type(exc).__name__}: {str(exc)[:70]}")

            # 只看体积大 + 数组长的
            cand = [x for x in rows if x["n"] >= 3 or x["size"] > 8000]
            cand.sort(key=lambda x: (-x["n"], -x["size"]))
            if not cand:
                print("   ❌ 没有可疑接口")
            for c in cand[:5]:
                print(f"   {c['m']:<5} {c['u'].replace('https://', '')[:62]}")
                print(f"        数组 {c['n']} 条 | {c['size'] / 1024:.0f}KB | 时间:{'✅' if c['time'] else '❌'} | {c['keys'][:7]}")
                if c["q"]:
                    print(f"        query: {c['q'][:110]}")
            page.close()

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
