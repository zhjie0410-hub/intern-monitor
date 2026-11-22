"""把抓取结果生成自包含 HTML 看板（双击就能用，不需要服务器 / 数据库）。

设计取舍：
  - 数据直接内嵌进 HTML（window.__JOB_DATA__），所以 file:// 打开也能用，
    不会踩到 fetch 本地 JSON 的 CORS 限制。
  - 界面用原生 JS + CSS，不引任何 CDN，断网也能看。
  - 筛选项：关键词、公司、方向、城市、发布时间、分数下限；支持排序、标已投。

用法：
    python tools/build_dashboard.py                       # 自动找最新的 data/exports/*.csv
    python tools/build_dashboard.py --csv 某个文件.csv
    python tools/build_dashboard.py --out data/dashboard/看板.html
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORTS = ROOT / "data" / "exports"
OUT_DEFAULT = ROOT / "data" / "dashboard" / "看板.html"

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>实习岗位看板 · __GENERATED__</title>
<style>
  :root{
    --bg:#f5f6f8; --card:#fff; --line:#e4e7ed; --text:#1f2329; --muted:#6b7280;
    --blue:#2563eb; --green:#059669; --orange:#ea580c; --red:#dc2626;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
       font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  header{background:#fff;border-bottom:1px solid var(--line);padding:16px 24px}
  h1{margin:0 0 4px;font-size:19px}
  .sub{color:var(--muted);font-size:12px}
  .wrap{padding:16px 24px 60px}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
  .stat b{display:block;font-size:22px;line-height:1.3}
  .stat span{color:var(--muted);font-size:12px}
  .filters{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;
           display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}
  .filters label{color:var(--muted);font-size:12px;margin-right:4px}
  .filters input,.filters select{padding:6px 8px;border:1px solid var(--line);border-radius:6px;
      font-size:13px;background:#fff;color:var(--text)}
  .filters input[type=search]{min-width:200px}
  .filters .spacer{flex:1}
  button{cursor:pointer;padding:6px 12px;border:1px solid var(--line);border-radius:6px;
         background:#fff;font-size:13px}
  button.primary{background:var(--blue);color:#fff;border-color:var(--blue)}
  table{width:100%;border-collapse:collapse;background:var(--card);
        border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
  th{background:#fafbfc;font-size:12px;color:var(--muted);white-space:nowrap;cursor:pointer;
     position:sticky;top:0;z-index:2}
  th:hover{color:var(--blue)}
  tr:last-child td{border-bottom:none}
  tr:hover td{background:#f9fbff}
  td.title{max-width:340px}
  td.title a{color:var(--text);text-decoration:none;font-weight:600}
  td.title a:hover{color:var(--blue);text-decoration:underline}
  td.title .jk{font-weight:600}
    .lk a{color:#2f6fed;text-decoration:none}
    .lk a:hover{text-decoration:underline}
    .lk .na{color:#c3c8cf}
    .copy{margin-left:6px;padding:1px 6px;font-size:11px;border:1px solid #d7dbe0;border-radius:4px;background:#fff;color:#666;cursor:pointer}
    .copy:hover{border-color:#2f6fed;color:#2f6fed}
    .jd{color:var(--muted);font-size:12px;margin-top:2px;
      display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .chip{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;
        border:1px solid var(--line);color:var(--muted);background:#fafbfc;white-space:nowrap}
  .chip.intern{color:var(--green);border-color:#bbf7d0;background:#f0fdf4}
  .chip.campus{color:var(--orange);border-color:#fed7aa;background:#fff7ed}
  .score{font-weight:700}
  .score.hi{color:var(--green)} .score.mid{color:var(--blue)} .score.lo{color:var(--muted)}
  .fresh{color:var(--green);font-weight:600}
  .old{color:var(--muted)}
  .applied td{opacity:.45}
  .btn-applied{font-size:12px;padding:2px 8px}
  .empty{padding:40px;text-align:center;color:var(--muted);background:var(--card);
         border:1px solid var(--line);border-radius:10px}
  .pager{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:center;
         margin:16px 0 8px}
  .pager button{min-width:34px;padding:5px 9px;font-size:13px}
  .pager button.active{background:var(--blue);color:#fff;border-color:var(--blue);font-weight:600}
  .pager button:disabled{opacity:.4;cursor:default}
  .pager .info{color:var(--muted);font-size:12px;margin-left:8px}
  footer{color:var(--muted);font-size:12px;padding:0 24px 30px}
</style>
</head>
<body>
<header>
  <h1>实习岗位看板</h1>
  <div class="sub">生成时间 __GENERATED__ ｜ 数据来源：公司官网 ｜ 共 __TOTAL__ 个岗位（点标题直达官网）</div>
</header>

<div class="wrap">
  <div class="stats" id="stats"></div>

  <div class="filters">
    <input type="search" id="q" placeholder="搜索岗位 / 公司 / JD 关键词，如 SQL、策略、TikTok">
    <span><label>公司</label><select id="f-company"></select></span>
    <span><label>方向</label><select id="f-category"></select></span>
    <span><label>城市</label><select id="f-city"></select></span>
    <span><label>发布</label>
      <select id="f-days">
        <option value="0">不限</option>
        <option value="7">近 7 天</option>
        <option value="30" selected>近 30 天</option>
        <option value="90">近 90 天</option>
        <option value="180">近半年</option>
      </select>
    </span>
    <span><label>分数≥</label>
      <select id="f-score">
        <option value="0">不限</option>
        <option value="100">100</option>
        <option value="110">110</option>
        <option value="115">115</option>
        <option value="120">120</option>
      </select>
    </span>
    <span><label>每页</label>
      <select id="f-pagesize">
        <option value="20" selected>20</option>
        <option value="30">30</option>
        <option value="50">50</option>
        <option value="100">100</option>
        <option value="9999">全部</option>
      </select>
    </span>
    <span class="spacer"></span>
    <button id="btn-reset">重置</button>
    <button class="primary" id="btn-csv">导出当前结果 CSV</button>
  </div>

  <div id="list"></div>
</div>
<footer>本页为静态文件：数据已内嵌，可离线打开、可随手发给别人。投递请点岗位标题到官网完成。</footer>

<script>
const DATA = __DATA__;
const APPLIED_KEY = "ss_dashboard_applied";

let applied = new Set(JSON.parse(localStorage.getItem(APPLIED_KEY) || "[]"));
let sortKey = "score", sortDir = -1;
let page = 1;
let pageSize = 20;

const $ = id => document.getElementById(id);

function uniq(list){ return [...new Set(list.filter(Boolean))].sort(); }

function initFilters(){
  const setOpts = (id, values, label) => {
    const el = $(id);
    el.innerHTML = '<option value="">全部</option>' +
      values.map(v => `<option value="${v}">${v}</option>`).join("");
  };
  setOpts("f-company", uniq(DATA.map(d => d.company)));
  setOpts("f-category", uniq(DATA.map(d => d.direction)));
  setOpts("f-city", uniq(DATA.map(d => (d.city||"").split("/")[0])));
}

function currentRows(){
  const q = $("q").value.trim().toLowerCase();
  const company = $("f-company").value;
  const category = $("f-category").value;
  const city = $("f-city").value;
  const days = Number($("f-days").value) || 0;
  const minScore = Number($("f-score").value) || 0;

  let rows = DATA.filter(d => {
    if (company && d.company !== company) return false;
    if (category && d.direction !== category) return false;
    if (city && !(d.city||"").includes(city)) return false;
    const fd = (d.fresh_days !== undefined && d.fresh_days !== null) ? d.fresh_days : d.published_days;
    if (days && !(fd >= 0 && fd <= days)) return false;
    if (minScore && (d.score||0) < minScore) return false;
    if (q) {
      const blob = (d.title + " " + d.company + " " + (d.city||"") + " " +
                    (d.description||"") + " " + (d.requirement||"") + " " + (d.reasons||"")).toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });

  rows.sort((a,b) => {
    let va = a[sortKey], vb = b[sortKey];
    if (sortKey === "published_days" || sortKey === "score") { va = Number(va)||0; vb = Number(vb)||0; }
    else { va = String(va||""); vb = String(vb||""); }
    if (va < vb) return -1 * sortDir;
    if (va > vb) return 1 * sortDir;
    return 0;
  });
  return rows;
}

function renderStats(rows){
  const total = rows.length;
  const fdays = d => (d.fresh_days !== undefined && d.fresh_days !== null) ? d.fresh_days : d.published_days;
  const fresh7 = rows.filter(d => fdays(d) >= 0 && fdays(d) <= 7).length;
  const fresh30 = rows.filter(d => fdays(d) >= 0 && fdays(d) <= 30).length;
  const noOfficial = rows.filter(d => d.fresh_source === "first_seen").length;
  const bj = rows.filter(d => (d.city||"").includes("北京") || (d.city||"").includes("上海")).length;
  const hiScore = rows.filter(d => (d.score||0) >= 115).length;
  const done = rows.filter(d => applied.has(d.key)).length;
  $("stats").innerHTML = [
    ["当前筛选", total, "个岗位"],
    ["近 7 天发布", fresh7, "优先投"],
    ["近 30 天发布", fresh30, "较新"],
    ["北京/上海", bj, "地理集中"],
    ["分数 ≥115", hiScore, "高匹配"],
    ["已标记投递", done, "本地记录"],
    ["官网无发布时间", noOfficial, "按首次发现算"],
  ].map(([k,v,s]) => `<div class="stat"><b>${v}</b><span>${k} · ${s}</span></div>`).join("");
}

function cell(d){
  const isIntern = (d.batch||"").includes("日常实习") || (d.batch||"").includes("ByteIntern") || (d.work_type||"") === "实习";
  const cls = isIntern ? "chip intern" : "chip campus";
  const days = (d.fresh_days !== undefined && d.fresh_days !== null) ? d.fresh_days : d.published_days;
  const daysTxt = days === 0 ? "今天" : (days > 0 ? days + " 天前" : "");
  const daysCls = (days >= 0 && days <= 7) ? "fresh" : "old";
  return `<tr class="${applied.has(d.key) ? "applied" : ""}" data-key="${d.key}">
    <td class="score ${d.score>=115?'hi':(d.score>=105?'mid':'lo')}">${d.score || ""}</td>
    <td class="title">
      ${/^https?:\/\//.test(d.url || "")
        ? `<a class="jk" href="${d.url}" target="_blank" rel="noopener">${d.title || ""}</a>`
        : `<span class="jk">${d.title || ""}</span>`}
      <button class="copy" data-t="${(d.title||"").replace(/"/g,'&quot;')}" title="复制岗位名">复制</button>
      <div class="jd">${(d.description||"").slice(0,120)}</div>
    </td>
    <td>${d.company || ""}</td>
    <td>${(d.city||"").replace(/\\//g," / ")}</td>
    <td><span class="${cls}">${d.batch || d.work_type || ""}</span></td>
    <td>${d.direction || d.category || ""}</td>
    <td>${d.publish_time || (d.first_seen ? "首次发现 " + d.first_seen : "—")}
        <div class="${daysCls}">${daysTxt}</div>
        <div style="font-size:11px;color:var(--muted)">${d.fresh_source === "first_seen" ? "（官网无发布时间）" : ""}</div></td>
    <td class="lk">${/^https?:\/\//.test(d.url || "")
      ? `<a href="${d.url}" target="_blank" rel="noopener">${/detail|\/position\/|positionId/.test(d.url) ? "详情" : "列表"}</a>`
      : `<span class="na">—</span>`}</td>
    <td><button class="btn-applied" data-toggle="${d.key}">${applied.has(d.key) ? "已投" : "标记投递"}</button></td>
  </tr>`;
}

function pageButtons(totalPages){
  if (totalPages <= 1) return "";
  const nums = [];
  const push = n => nums.push(`<button data-page="${n}" class="${n === page ? 'active' : ''}">${n}</button>`);
  const window_ = 2;
  for (let n = 1; n <= totalPages; n++) {
    if (n === 1 || n === totalPages || Math.abs(n - page) <= window_) push(n);
    else if (nums[nums.length - 1] !== "...") nums.push("...");
  }
  const html = nums.map(x => x === "..." ? '<button disabled>…</button>' : x).join("");
  return `<div class="pager">
    <button data-page="prev" ${page === 1 ? "disabled" : ""}>‹ 上一页</button>
    ${html}
    <button data-page="next" ${page === totalPages ? "disabled" : ""}>下一页 ›</button>
  </div>`;
}

function render(){
  const rows = currentRows();
  renderStats(rows);
  if (!rows.length) {
    $("list").innerHTML = '<div class="empty">没有符合条件的岗位，放宽筛选试试</div>';
    return;
  }
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (page > totalPages) page = totalPages;
  if (page < 1) page = 1;
  const start = (page - 1) * pageSize;
  const slice = rows.slice(start, start + pageSize);

  $("list").innerHTML = `<table>
    <thead><tr>
      <th data-sort="score">分数</th>
      <th data-sort="title">岗位</th>
      <th data-sort="company">公司</th>
      <th data-sort="city">城市</th>
      <th data-sort="batch">批次</th>
      <th data-sort="direction">方向</th>
      <th data-sort="fresh_days">发布 / 首次发现</th>
      <th>链接</th>
      <th>操作</th>
    </tr></thead>
    <tbody>${slice.map(cell).join("")}</tbody>
  </table>
  ${pageButtons(totalPages)}
  <div class="pager"><span class="info">第 ${page}/${totalPages} 页，共 ${rows.length} 个岗位（${pageSize >= 9999 ? "全部显示" : "每页 " + pageSize + " 个"}）</span></div>`;
}

function bind(){
  $("f-pagesize").addEventListener("change", () => {
    pageSize = Number($("f-pagesize").value) || 20;
    page = 1;
    render();
  });
  ["q","f-company","f-category","f-city","f-days","f-score"].forEach(id => {
    const handler = () => { page = 1; render(); };
    $(id).addEventListener("input", handler);
    $(id).addEventListener("change", handler);
  });
  $("btn-reset").onclick = () => {
    $("q").value = ""; $("f-company").value = ""; $("f-category").value = "";
    $("f-city").value = ""; $("f-days").value = "30"; $("f-score").value = "0";
    $("f-pagesize").value = "20";
    pageSize = 20;
    page = 1;
    render();
  };
  $("btn-csv").onclick = () => {
    const rows = currentRows();
    document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".copy");
    if (!btn) return;
    try {
      await navigator.clipboard.writeText(btn.dataset.t || "");
      const old = btn.textContent; btn.textContent = "已复制";
      setTimeout(() => btn.textContent = old, 1200);
    } catch (err) { btn.textContent = "失败"; }
  });

  const cols = ["score","company","title","city","batch","category","publish_time","published_days","job_id","url"];
    const csv = "\\ufeff" + [cols.join(",")].concat(rows.map(r =>
      cols.map(c => '"' + String(r[c] ?? "").replace(/"/g,'""') + '"').join(","))).join("\\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"}));
    a.download = "看板筛选结果.csv";
    a.click();
  };
  document.addEventListener("click", e => {
    const pg = e.target.closest("button[data-page]");
    if (pg) {
      const v = pg.dataset.page;
      const totalPages = Math.max(1, Math.ceil(currentRows().length / pageSize));
      if (v === "prev") page = Math.max(1, page - 1);
      else if (v === "next") page = Math.min(totalPages, page + 1);
      else page = Number(v) || 1;
      render();
      window.scrollTo({top: 0, behavior: "smooth"});
      return;
    }
    const th = e.target.closest("th[data-sort]");
    if (th) {
      const key = th.dataset.sort;
      if (sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = key === "published_days" ? 1 : -1; }
      page = 1;
      render();
      return;
    }
    const btn = e.target.closest("button[data-toggle]");
    if (btn) {
      const key = btn.dataset.toggle;
      if (applied.has(key)) applied.delete(key); else applied.add(key);
      localStorage.setItem(APPLIED_KEY, JSON.stringify([...applied]));
      render();
    }
  });
}

initFilters();
bind();
render();
</script>
</body>
</html>
"""


def load_directions() -> tuple[list[tuple[str, list[str]]], list[str]]:
    """读方向白名单与排除词；没有配置文件时给一套兜底规则。"""
    fallback = [
        ("数据分析", ["数据分析", "数分"]),
        ("商业分析", ["商业分析"]),
        ("数据科学", ["数据科学"]),
        ("策略运营", ["策略运营"]),
    ]
    cfg_path = ROOT / "config" / "keywords.yaml"
    if not cfg_path.exists():
        return fallback, []
    try:
        import yaml
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return fallback, []
    dirs = ((data.get("directions") or {}).get("enabled")) or []
    rules = [(d["name"], d.get("keywords") or [d["name"]]) for d in dirs if d.get("name")]
    excludes = list(data.get("exclude") or [])
    return (rules or fallback), excludes


def pick_direction(title: str, rules: list[tuple[str, list[str]]]) -> str:
    for name, kws in rules:
        if any(k in title for k in kws):
            return name
    return ""


def load_rows(csv_path: Path) -> list[dict]:
    rows = []
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                days = int(r.get("published_days") or -1)
            except ValueError:
                days = -1
            try:
                score = float(r.get("score") or 0)
            except ValueError:
                score = 0.0
            key = f"{r.get('company','')}::{r.get('job_id') or r.get('title','')}"
            rows.append({
                "key": key,
                "score": score,
                "company": r.get("company", ""),
                "title": r.get("title", ""),
                "city": r.get("city", ""),
                "batch": r.get("batch", ""),
                "work_type": r.get("work_type", ""),
                "category": r.get("category", ""),
                "direction": r.get("direction", ""),
                "publish_time": r.get("publish_time", ""),
                "published_days": days,
                "first_seen": r.get("first_seen", ""),
                "fresh_days": int(r.get("fresh_days") or days if (r.get("fresh_days") or "").strip() not in ("", "-1") else days),
                "fresh_source": r.get("fresh_source", ""),
                "job_id": r.get("job_id", ""),
                "url": r.get("url", ""),
                "reasons": r.get("reasons", ""),
                "description": (r.get("description") or "")[:600],
                "requirement": (r.get("requirement") or "")[:600],
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", help="数据来源 CSV；不传则用 data/exports 里最新的")
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    args = parser.parse_args()

    if args.csv:
        csv_path = Path(args.csv)
    else:
        candidates = sorted(EXPORTS.glob("jobs-*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print(f"没找到数据：{EXPORTS} 下没有 jobs-*.csv，先跑一次抓取")
            return 1
        csv_path = candidates[0]

    rows = load_rows(csv_path)
    rules, excludes = load_directions()
    before = len(rows)
    kept = []
    for r in rows:
        direction = pick_direction(r["title"], rules)
        if not direction:
            continue
        if any(w in r["title"] for w in excludes):
            continue
        r["direction"] = direction
        kept.append(r)
    rows = kept
    print(f"方向过滤：{before} → {len(rows)}（只保留 {'、'.join(n for n, _ in rules)}）")
    html = (TEMPLATE
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False))
            .replace("__GENERATED__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__TOTAL__", str(len(rows))))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"数据来源：{csv_path.name}（{len(rows)} 行）")
    print(f"已生成看板：{out}  ({out.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
