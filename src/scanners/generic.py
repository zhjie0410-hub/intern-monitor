"""通用抓取引擎：抓包 → 重放 → 字段映射。

核心思路
--------
各家招聘站的列表接口都带 token（csrf / ctoken / u_query_id），外部直接拼请求很难过。
但**页面自己会发一次**，我们只要：
  1. 打开页面，等它把列表请求发出去
  2. 把这条请求（URL + 请求体 + headers）抓下来
  3. 只替换「页码」参数，用同一个浏览器上下文重放
  4. 按规格里的字段映射解析 JSON

优点：token 天然新鲜；不用逆向签名；一套代码适配多家。

规格（spec）字段
----------------
必填：
    name        公司中文名
    entry       入口 URL
    api         列表接口 URL 的关键片段（用于识别哪条请求是列表）
    list_path   响应里岗位数组的路径，如 "data.list" / "data.content"
    title       标题字段名
可选：
    clicks      进入页面后要点的选择器/文字列表
    wait        首次等待毫秒（默认 5000）
    page_in     "body" | "query"   页码所在位置
    page_field  页码字段名，支持点号路径（如 "page.pageNo"）
    page_start  起始页码（默认 1）
    size_field  每页条数字段名
    page_size   每页条数（默认 100）
    id          岗位 ID 字段
    city        城市字段（可能是数组或字符串）
    time        时间字段名
    time_kind   "ms" | "iso" | "ymd"
    desc        岗位描述字段
    req         任职要求字段
    batch       批次字段
    work_type   工作类型字段
"""

from __future__ import annotations

import json
import re
from datetime import datetime

MAX_PAGES = 30


def _dig(obj, path: str):
    """按 "a.b.c" 取值。"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def _set_dig(obj: dict, path: str, value) -> None:
    """按 "a.b.c" 写值（会就地修改）。"""
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _norm_time(value, kind: str) -> tuple[str, int]:
    """统一成 (YYYY-MM-DD, 距今天数)。"""
    if value in (None, "", 0):
        return "", -1
    try:
        text_value = str(value).strip()
        if isinstance(value, (int, float)) or text_value.isdigit():
            num = int(text_value)
            # 10 位是秒，13 位是毫秒
            ts = num / 1000 if num > 10_000_000_000 else num
            dt = datetime.fromtimestamp(ts)
        elif kind == "iso" or "T" in str(value):
            text = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text).replace(tzinfo=None)
            if "+" in text:  # ISO 带时区，粗略扣掉
                dt = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
        else:
            dt = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        days = (datetime.now() - dt).days
        return dt.strftime("%Y-%m-%d"), max(days, 0)
    except Exception:
        return "", -1


def _city(value) -> str:
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(str(item.get("name") or item.get("cityName") or ""))
            else:
                out.append(str(item))
        return "/".join(x for x in out if x)
    return str(value or "")


def _capture(page, spec: dict, timeout_ms: int = 20000) -> dict | None:
    """打开页面并抓取列表请求。"""
    hit: dict = {}

    def on_request(req):
        if hit:
            return
        if req.resource_type not in ("xhr", "fetch"):
            return
        if spec["api"] not in req.url:
            return
        hit["url"] = req.url
        hit["method"] = req.method
        hit["headers"] = dict(req.headers)
        hit["body"] = req.post_data
        hit["page"] = page

    def on_response(resp):
        if hit.get("json") is not None:
            return
        if spec["api"] not in resp.url:
            return
        try:
            hit["json"] = resp.json()
        except Exception:
            pass

    page.on("request", on_request)
    page.on("response", on_response)
    page.goto(spec["entry"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(spec.get("wait", 5000))

    for sel in spec.get("clicks", []):
        try:
            loc = page.locator(sel).first if sel.startswith((".", "#", "[", "text=")) else page.get_by_text(sel, exact=False).first
            loc.click(timeout=5000)
            page.wait_for_timeout(spec.get("click_wait", 4000))
        except Exception:
            continue

    # 有些站点要滚动才加载列表（阿里、蚂蚁）
    for _ in range(spec.get("scrolls", 2)):
        if hit.get("json") is not None:
            break
        try:
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(1800)
        except Exception:
            break

    waited = 0
    while (not hit or hit.get("json") is None) and waited < timeout_ms:
        page.wait_for_timeout(1000)
        waited += 1000
    for _ in range(3):
        try:
            page.remove_listener("request", on_request)
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return hit or None


def _replay(ctx, hit: dict, spec: dict, page_no: int) -> dict | None:
    """改页码后重放请求，返回 JSON。"""
    page_in = spec.get("page_in", "body")
    field = spec.get("page_field", "pageIndex")
    url = hit["url"]
    body = hit.get("body")
    headers = {k: v for k, v in (hit.get("headers") or {}).items()
               if k.lower() in ("content-type", "accept", "referer", "origin", "x-requested-with",
                                "authorization", "cookie", "x-csrf-token", "portal-channel",
                                "portal-platform", "website-path", "portal_entrance")}

    if page_in == "query":
        if re.search(rf"[?&]{re.escape(field)}=\d+", url):
            url = re.sub(rf"([?&]{re.escape(field)}=)\d+", rf"\g<1>{page_no}", url)
        else:
            url += ("&" if "?" in url else "?") + f"{field}={page_no}"
        data = body
    else:
        data = body
        if body:
            try:
                payload = json.loads(body)
            except Exception:
                payload = None
            if payload is not None:
                for path, val in (spec.get("body_patch") or {}).items():
                    try:
                        _set_dig(payload, path, val)
                    except Exception:
                        pass
                if spec.get("size_field"):
                    _set_dig(payload, spec["size_field"], spec.get("page_size", 100))
                if spec.get("size_field") and spec.get("page_field") is None:
                    pass
                try:
                    _set_dig(payload, field, page_no)
                except Exception:
                    pass
                data = json.dumps(payload, ensure_ascii=False)
        if not data:
            url += ("&" if "?" in url else "?") + f"{field}={page_no}"

    try:
        if hit["method"].upper() == "POST":
            resp = ctx.request.post(url, data=data, headers=headers, timeout=30000)
        else:
            resp = ctx.request.get(url, headers=headers, timeout=30000)
        return resp.json()
    except Exception:
        return None


def _to_job(spec: dict, item: dict) -> dict | None:
    title = str(_dig(item, spec["title"]) or "").strip()
    if not title:
        return None
    published, days = _norm_time(_dig(item, spec["time"]) if spec.get("time") else None,
                                 spec.get("time_kind", "ms"))
    return {
        "company": spec["name"],
        "title": title,
        "city": _city(_dig(item, spec["city"])) if spec.get("city") else "",
        "batch": str(_dig(item, spec["batch"]) or spec.get("batch_fixed", "")) if spec.get("batch") else spec.get("batch_fixed", ""),
        "work_type": str(_dig(item, spec["work_type"]) or "") if spec.get("work_type") else spec.get("work_type_fixed", ""),
        "job_id": str(_dig(item, spec["id"]) or "") if spec.get("id") else "",
        "publish_time": published,
        "published_days": days,
        "url": spec.get("detail_url_tpl", "").format(id=_dig(item, spec["id"]) or "") if spec.get("detail_url_tpl") else "",
        "description": str(_dig(item, spec["desc"]) or "")[:4000] if spec.get("desc") else "",
        "requirement": str(_dig(item, spec["req"]) or "")[:4000] if spec.get("req") else "",
        "raw": "",
    }


def scan(ctx, page, spec: dict, verbose: bool = True) -> list[dict]:
    """跑一家公司，返回岗位列表。"""
    hit = _capture(page, spec)
    if not hit:
        if verbose:
            print(f"      ❌ 没抓到接口（匹配片段：{spec['api']}）")
        return []

    jobs: list[dict] = []
    seen: set[str] = set()
    start = spec.get("page_start", 1)

    def absorb(items: list) -> int:
        added = 0
        for item in items:
            job = _to_job(spec, item)
            if not job:
                continue
            key = job["job_id"] or job["title"]
            if key in seen:
                continue
            seen.add(key)
            jobs.append(job)
            added += 1
        return added

    # 先用抓到的第一页（重放可能被签名拦住，但这一页一定是真的）
    first_items = _read_list(hit.get("json") or {}, spec)
    if first_items:
        added = absorb(first_items)
        if verbose:
            print(f"      首屏 {len(first_items)} 条（新增 {added}），累计 {len(jobs)}")

    for offset in range(MAX_PAGES):
        page_no = start + offset
        payload = _replay(ctx, hit, spec, page_no)
        if not payload:
            if verbose:
                print(f"      第 {page_no} 页重放失败 → 改为点击翻页继续")
            more = scan_by_click(ctx, page, spec, max_pages=min(MAX_PAGES, 8), verbose=verbose)
            for job in more:
                key = job["job_id"] or job["title"]
                if key not in seen:
                    seen.add(key)
                    jobs.append(job)
            break
        items = _dig(payload, spec["list_path"]) or []
        if not isinstance(items, list) or not items:
            break
        added = absorb(items)
        if verbose:
            print(f"      第 {page_no} 页 → {len(items)} 条（新增 {added}），累计 {len(jobs)}")
        if added == 0 or len(items) < spec.get("page_size", 100) * 0.5:
            break
    return jobs


# ---------------------------------------------------------------- 点击翻页模式
NEXT_SELECTORS = [
    "button:has-text('下一页')", "[class*='pagination'] [class*='next']",
    ".ant-pagination-next", "[aria-label='Next']", "[title='下一页']",
    "[class*='next']", "text=下一页",
]


def _read_list(payload: dict, spec: dict) -> list:
    items = _dig(payload, spec["list_path"])
    return items if isinstance(items, list) else []


def scan_by_click(ctx, page, spec: dict, max_pages: int = 10, verbose: bool = True) -> list[dict]:
    """打开页面 → 抓首屏响应 → 点「下一页」→ 抓新响应 → 直到没有新数据。

    适用于接口带签名（改参数重放会被 405）的站点：字节系 SaaS、得物等。
    """
    jobs: list[dict] = []
    seen: set[str] = set()
    bucket: list[dict] = []

    def on_resp(r):
        try:
            if spec["api"] in r.url:
                bucket.append(r.json())
        except Exception:
            pass

    page.on("response", on_resp)
    page.goto(spec["entry"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(spec.get("wait", 6000))

    for _ in range(spec.get("clicks_wait_pages", max_pages)):
        payload = bucket[-1] if bucket else None
        bucket.clear()
        if payload:
            items = _read_list(payload, spec)
            added = 0
            for item in items:
                job = _to_job(spec, item)
                if not job:
                    continue
                key = job["job_id"] or job["title"]
                if key in seen:
                    continue
                seen.add(key)
                jobs.append(job)
                added += 1
            if verbose:
                print(f"      抓到 {len(items)} 条（新增 {added}），累计 {len(jobs)}")
            if added == 0 and jobs:
                break
        # 点下一页
        clicked = False
        for sel in NEXT_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_enabled():
                    loc.click(timeout=4000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            if verbose:
                print("      没找到可点的『下一页』，结束")
            break
        page.wait_for_timeout(spec.get("click_wait", 3500))

    try:
        page.remove_listener("response", on_resp)
    except Exception:
        pass
    return jobs


def scan_by_nav(ctx, page, spec: dict, max_pages: int = 20, verbose: bool = True) -> list[dict]:
    """靠 URL 参数翻页：pageNum / pageIndex 等。

    每次重新导航到「入口 + &参数=N」，让页面自己发请求，我们只读响应。
    适用于接口带签名、但前端路由支持分页参数的站点（快手等）。
    """
    param = spec.get("nav_param", "pageNum")
    start = spec.get("nav_start", 1)
    jobs: list[dict] = []
    seen: set[str] = set()
    empty_streak = 0

    for i in range(max_pages):
        pageno = start + i
        got: dict = {}

        def on_resp(r, got=got):
            try:
                if spec["api"] in r.url and not got:
                    got["json"] = r.json()
            except Exception:
                pass

        page.on("response", on_resp)
        url = spec["entry"]
        if pageno != start:
            url += ("&" if "?" in url else "?") + f"{param}={pageno}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(spec.get("wait", 6000))
            if not got:
                page.mouse.wheel(0, spec.get("scroll_px", 1600))
                page.wait_for_timeout(2500)
        except Exception as exc:
            if verbose:
                print(f"      第 {pageno} 页打开失败 {type(exc).__name__}")
            break
        finally:
            try:
                page.remove_listener("response", on_resp)
            except Exception:
                pass

        items = _read_list(got.get("json") or {}, spec)
        added = 0
        for item in items:
            job = _to_job(spec, item)
            if not job:
                continue
            key = job["job_id"] or job["title"]
            if key in seen:
                continue
            seen.add(key)
            jobs.append(job)
            added += 1
        if verbose:
            print(f"      第 {pageno} 页 → {len(items)} 条（新增 {added}），累计 {len(jobs)}")
        if not items and not added:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
    return jobs
