"""大厂官网实习监控 · 字节跳动适配器（v2：拦截接口响应）

关键发现：列表接口的 JSON 比页面 DOM 丰富得多——含
  publish_time（发布时间，毫秒时间戳）、description（JD 正文）、requirement（任职要求）、
  recruit_type（正式/实习）、job_subject（批次，如「2027届校园招聘」/「ByteIntern」）、code（职位 ID）。

接口带签名，外部直接调不通，但**浏览器自己会调**：我们只负责读它的响应。
列表页支持 ?current=<页>&limit=<每页条数>，实测 limit=100 有效。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

BASE = (
    "https://jobs.bytedance.com/campus/position?keywords={kw}"
    "&category=&location=&project=&type=&job_hot_flag="
    "&current={cur}&limit={limit}&functionCategory=&tag="
)

INTERN_BATCHES = ("日常实习", "ByteIntern", "暑期实习", "实习")
CAMPUS_BATCHES = ("校园招聘", "校招", "秋招", "春招")


@dataclass
class Job:
    company: str
    title: str
    city: str
    batch: str              # 批次：日常实习 / ByteIntern / 2027届校园招聘
    work_type: str          # 正式 / 实习
    job_id: str             # 职位 ID（如 A102507A）
    publish_time: str       # YYYY-MM-DD
    published_days: int     # 距今多少天
    url: str
    category: str = ""      # 职能分类，如「数据分析」
    direction: str = ""     # 方向（由 config/keywords.yaml 白名单判定）
    first_seen: str = ""    # 我们第一次抓到它的日期（官网不给发布时间时用它）
    first_seen_days: int = -1   # 距首次发现多少天
    fresh_days: int = -1    # 统一"新鲜度"：有官方发布时间用它，否则用 first_seen_days
    fresh_source: str = ""  # official / first_seen
    description: str = ""   # 岗位描述（JD 正文）
    requirement: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = asdict(self)
        out.pop("raw", None)
        return out


def _batch_name(rec: dict) -> str:
    subject = rec.get("job_subject") or {}
    name = subject.get("name") or {}
    if isinstance(name, dict):
        return str(name.get("zh_cn") or "")
    return str(name or "")


def _city(rec: dict) -> str:
    cities = rec.get("city_list") or []
    names = []
    for c in cities:
        if isinstance(c, dict) and c.get("name"):
            names.append(str(c["name"]))
    if not names:
        info = rec.get("city_info") or {}
        if isinstance(info, dict) and info.get("name"):
            names = [str(info["name"])]
    return "/".join(names)


def _fmt_time(ms) -> tuple[str, int]:
    try:
        ts = int(ms) / 1000
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d"), (datetime.now() - dt).days
    except Exception:
        return "", -1


def to_job(rec: dict) -> Job | None:
    title = str(rec.get("title") or "").strip()
    if not title:
        return None
    batch = _batch_name(rec)
    work_type = ""
    rtype = rec.get("recruit_type") or {}
    if isinstance(rtype, dict):
        work_type = str(rtype.get("name") or "")
    published, days = _fmt_time(rec.get("publish_time"))
    category = ""
    jc = rec.get("job_category") or {}
    if isinstance(jc, dict):
        category = str(jc.get("name") or "")
    return Job(
        company="字节跳动",
        title=title,
        city=_city(rec),
        batch=batch,
        work_type=work_type,
        job_id=str(rec.get("code") or rec.get("id") or ""),
        publish_time=published,
        published_days=days,
        url=f"https://jobs.bytedance.com/campus/position/{rec.get('id')}/detail",
        category=category,
        description=str(rec.get("description") or "")[:4000],
        requirement=str(rec.get("requirement") or "")[:4000],
        raw=rec,
    )


def is_intern(job: Job) -> bool:
    """28 届能投：工作类型=实习 或 批次是实习项目；排除校招正式岗。"""
    if any(b in (job.batch or "") for b in CAMPUS_BATCHES):
        return False
    if job.work_type == "实习":
        return True
    if any(b in (job.batch or "") for b in INTERN_BATCHES):
        return True
    return "实习" in job.title


def scan(page, keyword: str, *, limit: int = 100, max_pages: int = 40, verbose: bool = True) -> list[Job]:
    """逐页打开列表页，读浏览器自己发出的 search/job/posts 响应。"""
    bucket: list[dict] = []

    def _handler(resp):
        _collect(resp, bucket)

    page.on("response", _handler)

    jobs: list[Job] = []
    seen: set[str] = set()

    for cur in range(1, max_pages + 1):
        bucket.clear()
        page.goto(BASE.format(kw=keyword, cur=cur, limit=limit), wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2600)
        records: list[dict] = []
        for payload in bucket:
            data = payload.get("data") or {}
            records.extend(data.get("job_post_list") or [])
        if not records:
            if verbose:
                print(f"      第 {cur} 页没有拿到数据，结束")
            break
        for rec in records:
            job = to_job(rec)
            if not job:
                continue
            key = job.job_id or job.title
            if key in seen:
                continue
            seen.add(key)
            jobs.append(job)
        if verbose:
            print(f"      第 {cur} 页 → 本页 {len(records)} 条，累计 {len(jobs)}")
        if len(records) < limit:
            break
    try:
        page.remove_listener("response", _handler)
    except Exception:
        pass
    return jobs


def _collect(resp, bucket: list[dict]) -> None:
    try:
        if "search/job/posts" in resp.url and resp.request.method == "POST":
            bucket.append(resp.json())
    except Exception:
        pass
