"""腾讯校园招聘适配器（纯 HTTP，不需要浏览器）

与其他家最大的不同：腾讯的接口没有签名、没有反爬，直接 urllib 就能调，速度快 10 倍。

用到的三个接口（2026-11 实测）：
  1) POST /api/v1/position/searchPosition
     body: {"projectIdList":[],"projectMappingIdList":[104],"keyword":"","bgList":[],
            "workCountryType":0,"workCityList":[],"recruitCityList":[],"positionFidList":[],
            "pageIndex":1,"pageSize":100}
     → {"data":{"count":73,"positionList":[{postId, id, positionTitle, workCities, bgs,
                                            projectName, recruitLabelName, projectId}, ...]}}

  2) GET /api/v1/position/getProjectMapping
     → 应聘项目树；关键 id：
          1   = 应届毕业生（2025-2026 毕业）
          2   = 应届实习（2027 届暑期实习）
          104 = 日常实习    ← 28 届能投的就是这个
          14  = 青云计划-应届生
          20  = 青云计划-实习生

  3) GET /api/v1/jobDetails/getJobDetailsByPostId?postId=<postId>
     → {title, desc, request, introduction, graduateBonus, internBonus,
        workCityList, projectName, recruitLabelName, ...}

注意：腾讯的岗位**没有发布时间字段**，所以 publish_time 留空、published_days = -1。
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field

from .bytedance import Job  # 复用统一模型

BASE = "https://join.qq.com"
SEARCH = f"{BASE}/api/v1/position/searchPosition"
DETAIL = f"{BASE}/api/v1/jobDetails/getJobDetailsByPostId"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": f"{BASE}/post.html",
    "Origin": BASE,
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# 应聘项目 id → 中文名（用于展示与筛选）
PROJECTS = {
    1: "应届毕业生",
    2: "应届实习",
    104: "日常实习",
    14: "青云计划-应届生",
    20: "青云计划-实习生",
}
# 28 届能投的项目（不限毕业年份）
INTERN_PROJECTS = (104,)

CAMPUS_BATCHES = ("应届毕业生", "应届生", "校园招聘", "青云计划-应届生")


@dataclass
class TencentJob(Job):
    project: str = ""


def _ts() -> int:
    return int(time.time() * 1000)


def _get(url: str, params: dict) -> dict:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{url}?{qs}&timestamp={_ts()}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read())


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(f"{url}?timestamp={_ts()}",
                                 data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read())


def search(keyword: str, *, projects: tuple[int, ...] = INTERN_PROJECTS,
           page_size: int = 100, max_pages: int = 10, verbose: bool = True) -> list[dict]:
    """按关键词翻页拿岗位列表（不含 JD）。"""
    body = {
        "projectIdList": [], "projectMappingIdList": list(projects), "keyword": keyword,
        "bgList": [], "workCountryType": 0, "workCityList": [], "recruitCityList": [],
        "positionFidList": [],
    }
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        payload = _post(SEARCH, {**body, "pageIndex": page, "pageSize": page_size})
        data = payload.get("data") or {}
        items = data.get("positionList") or []
        total = int(data.get("count") or 0)
        if not items:
            break
        for item in items:
            key = str(item.get("postId") or item.get("id"))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        if verbose:
            print(f"      {keyword}: 第 {page} 页 → {len(items)} 条，累计 {len(out)}/{total}")
        if len(out) >= total:
            break
        time.sleep(0.4)
    return out


def detail(post_id: str) -> dict:
    try:
        return _get(DETAIL, {"postId": post_id}).get("data") or {}
    except Exception:
        return {}


def to_job(item: dict, extra: dict | None = None) -> Job:
    extra = extra or {}
    title = str(item.get("positionTitle") or extra.get("title") or "").strip()
    cities = str(item.get("workCities") or "").replace("深圳总部", "深圳").strip()
    city = "/".join([c for c in cities.split() if c])
    project = str(item.get("projectName") or extra.get("projectName") or "")
    batch = str(item.get("recruitLabelName") or project)

    desc = str(extra.get("desc") or extra.get("introduction") or "")
    req = str(extra.get("request") or extra.get("internBonus") or extra.get("graduateBonus") or "")
    post_id = str(item.get("postId") or extra.get("postId") or "")

    return Job(
        company="腾讯",
        title=title,
        city=city,
        batch=batch,
        work_type="实习" if "实习" in (batch + project) else "正式",
        job_id=post_id or str(item.get("id") or ""),
        publish_time="",       # 腾讯接口不返回发布时间
        published_days=-1,
        url=f"{BASE}/post_detail.html?postId={post_id}" if post_id else "",
        category=str(item.get("tidName") or extra.get("tidName") or ""),
        description=desc[:4000],
        requirement=req[:4000],
        raw={"project": project},
    )


def scan(keywords: list[str], *, projects: tuple[int, ...] = INTERN_PROJECTS,
         with_detail: bool = True, verbose: bool = True) -> list[Job]:
    """按关键词抓腾讯实习岗，可选逐条补 JD。"""
    collected: dict[str, dict] = {}
    for kw in keywords:
        if verbose:
            print(f"\n[腾讯] 关键词「{kw}」")
        for item in search(kw, projects=projects, verbose=verbose):
            collected.setdefault(str(item.get("postId") or item.get("id")), item)

    if verbose:
        print(f"\n[腾讯] 去重后 {len(collected)} 个岗位，开始补 JD…")

    jobs: list[Job] = []
    for i, (pid, item) in enumerate(collected.items(), 1):
        extra = detail(pid) if with_detail else {}
        job = to_job(item, extra)
        if job.title:
            jobs.append(job)
        if with_detail and i % 20 == 0 and verbose:
            print(f"      已补 {i}/{len(collected)}")
        if with_detail:
            time.sleep(0.15)  # 温柔一点，避免把人家接口打爆
    return jobs


def is_intern(job: Job) -> bool:
    """28 届能投：批次含"实习"且不是校招正式岗。"""
    if any(b in (job.batch or "") for b in CAMPUS_BATCHES):
        return False
    return "实习" in (job.batch or "") or "实习" in (job.title or "")
