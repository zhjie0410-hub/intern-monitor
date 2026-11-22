# 大厂实习监控 · 项目结构

目标：把各家大厂官网的**实习**岗位抓下来 → 标准化 → 存成分层数据 → 供看板（dashboard）查询。
投递仍然是人工的（官网有简历冻结期、每批限投 1-3 个，不适合全自动）。

> 状态：目录骨架已建好，代码正在从旧的 `sites/` + `scan.py` 迁到 `src/`。

---

## 一、目录职责

```
大厂实习监控/
├─ config/                  配置（不写死在代码里）
│   ├─ companies.yaml       公司清单：slug、官网入口、启用开关、适配器名
│   ├─ keywords.yaml        搜索关键词、方向词、排除词
│   └─ scoring.yaml         打分权重（方向/技能/城市/新鲜度）
│
├─ src/                     代码
│   ├─ main.py              入口：按 config 依次跑各公司适配器
│   ├─ core/                与公司无关的公共逻辑
│   │   ├─ models.py        Job 数据模型（统一字段）
│   │   ├─ scorer.py        打分与过滤（28届可投 / 方向 / 城市 / 新鲜度）
│   │   ├─ store.py         落盘：单岗位 JSON、公司汇总、类别视图、SQLite
│   │   └─ utils.py         时间戳、slug、去重键
│   ├─ scanners/            每家一个适配器（只负责“抓”）
│   │   ├─ base.py          适配器接口约定
│   │   ├─ bytedance.py     字节跳动（已跑通）
│   │   ├─ tencent.py       腾讯
│   │   ├─ dewu.py          得物
│   │   ├─ meituan.py       美团
│   │   ├─ alibaba.py       阿里
│   │   ├─ jd.py            京东
│   │   └─ baidu.py         百度
│   └─ dashboard/           看板（后续）
│       ├─ app.py           主页：多公司一览 + 筛选
│       ├─ pages/           子页：按方向 / 按公司 / 新增岗位 / 投递记录
│       └─ assets/          样式、图标
│
├─ data/                    ★ 数据分层（见第二节）
│   ├─ raw/<company>/       接口原始响应（JSON，按抓取时间存）
│   ├─ companies/<company>/ ★ 按公司划分
│   │   ├─ jobs/<job_id>.json   单个岗位一份（岗位为主键）
│   │   └─ index.csv            该公司所有岗位的一行摘要
│   ├─ categories/          ★ 按岗位方向划分的视图（从上面派生）
│   │   ├─ 数据分析.csv
│   │   ├─ 商业分析.csv
│   │   ├─ 经营分析.csv
│   │   ├─ 策略运营.csv
│   │   └─ 策略分析.csv
│   ├─ snapshots/YYYYMMDD/  每日快照（用于“新增 / 下线”对比）
│   └─ exports/             对外导出的成品表（发给别人/给 Excel 看）
│
├─ db/
│   └─ jobs.sqlite          ★ 看板的数据源（结构见 db/schema.sql）
├─ logs/                    运行日志（按天）
├─ tests/                   离线测试
└─ docs/                    设计说明
```

---

## 二、数据为什么这么分

| 层 | 位置 | 回答什么问题 | 谁写 |
|---|---|---|---|
| **原始层** | `data/raw/<company>/` | 抓的时候接口到底返回了什么（排查用） | 适配器 |
| **岗位层** | `data/companies/<company>/jobs/<job_id>.json` | 这一个岗位的完整信息（JD、要求、发布时间、状态） | core/store |
| **公司层** | `data/companies/<company>/index.csv` | 这家公司有多少岗位、最新什么时候更的 | core/store |
| **方向层** | `data/categories/<方向>.csv` | 我关心的方向有哪些岗位（跨公司） | core/store |
| **快照层** | `data/snapshots/YYYYMMDD/` | 今天比昨天多了什么、少了什么 | core/store |
| **服务层** | `db/jobs.sqlite` | 看板的查询来源（筛选/排序/统计） | core/store |
| **导出层** | `data/exports/` | 给人看的成品表 | 手动/定时 |

**为什么岗位单独存文件而不是全塞 CSV**：
一个是 JD 正文很长（4000 字），CSV 会很难读；另一个是岗位会被反复更新（涨薪、改要求、下线），
按 `job_id` 存单文件可以只覆盖变化的那份，也方便看板点击看详情。

**为什么还要 SQLite**：
看板要做多条件筛选 + 排序 + 按公司/方向聚合，文件读写太慢。SQLite 是单文件、零部署，直接给看板用。

---

## 三、公司 slug 约定

目录和文件名一律用英文 slug，CSV 里保留中文公司名。

| 公司 | slug | 官网入口 |
|---|---|---|
| 字节跳动 | `bytedance` | https://jobs.bytedance.com/campus |
| 腾讯 | `tencent` | https://join.qq.com |
| 得物 | `dewu` | https://campus.dewu.com |
| 美团 | `meituan` | https://zhaopin.meituan.com |
| 阿里巴巴 | `alibaba` | https://talent.alibaba.com |
| 京东 | `jd` | https://campus.jd.com |
| 百度 | `baidu` | https://talent.baidu.com/jobs/campus |

新增公司 = 加一个 `config/companies.yaml` 条目 + 一个 `src/scanners/<slug>.py`。

---

## 四、统一字段（Job 模型）

所有适配器最后都产出这个结构，避免下游为每家写分支：

| 字段 | 说明 |
|---|---|
| `company` / `company_slug` | 公司中文名 / slug |
| `job_id` | 平台内岗位 ID（去重主键） |
| `title` | 岗位标题 |
| `city` | 城市（多城市用 `/` 连） |
| `category` | 职能分类（如「数据分析」） |
| `batch` | 批次（日常实习 / ByteIntern / 2027届校园招聘） |
| `work_type` | 正式 / 实习 |
| `publish_time` | 发布时间（YYYY-MM-DD） |
| `published_days` | 距今天数 |
| `url` | 详情页直链 |
| `description` | 岗位描述（JD 正文） |
| `requirement` | 任职要求 |
| `score` / `reasons` | 打分与理由（下游算，不入原始层） |
| `first_seen` / `last_seen` | 首次/最近一次抓到（用于新增与下线判断） |
| `status` | active / offline / applied / ignored |

---

## 五、看板取数方式（后续）

```python
# 典型查询：北京/上海、近 30 天、数据分析方向、分数降序
SELECT company, title, city, publish_time, published_days, score, url
FROM jobs
WHERE status = 'active'
  AND (city LIKE '%北京%' OR city LIKE '%上海%')
  AND published_days <= 30
  AND category LIKE '%数据分析%'
ORDER BY score DESC, published_days ASC;
```

---

## 六、当前架构与完成度

早期是「一公司一适配器」，现在是 **引擎 + 规格**：

```
run_all.py                    总调度（抓取 → 过滤 → 打分 → 导出 → 重建看板）
├─ src/scanners/generic.py    引擎：抓包 / URL翻页 / 点击翻页 + 字段映射
├─ src/scanners/specs.py      10 家公司的规格（入口、接口片段、分页字段、字段名）
└─ sites/                     老适配器，仍在使用
   ├─ bytedance.py            字节（URL 翻页 current/limit）
   └─ tencent.py              腾讯（纯 HTTP，无发布时间）
```

### 完成度

| 项 | 状态 |
|---|---|
| 引擎（三种翻页策略） | ✅ 抓包重放 / URL翻页 / 点击翻页，重放被签名拦住时自动降级 |
| 规格化接入 | ✅ 10 家（得物、京东、拼多多、网易、快手、小红书、小米、阿里、蚂蚁、美团） |
| 老适配器接入 | ✅ 字节跳动、腾讯 |
| 实际抓到数据 | ✅ 7 家（快手 1102、美团 557、网易 553、小红书 306、京东 88、字节 1802、腾讯 17） |
| 阿里 / 蚂蚁 | ⚠️ 请求不稳定，今天多次尝试均为 0 响应（疑似风控限流） |
| 拼多多 | ✅ 已确认实习专区只有 2 个岗位，非 bug |
| 看板 | ✅ `tools/build_dashboard.py` → `docs/index.html`，GitHub Pages 在线 |
| 每日定时 | ✅ GitHub Actions（北京 05:30），首次运行已验证成功 |
| 详情链接 | ✅ 4 家能直链详情页（美团/网易/小红书/快手），京东只能到列表页 |
| SQLite | ❌ 已放弃，改为纯 CSV + 静态 HTML |

旧的 `scan.py` 和 `sites/` 保留：`sites/` 里的字节、腾讯仍被 `run_all.py` 调用；
`scan.py` 是单公司调试入口，不参与每日流程。
