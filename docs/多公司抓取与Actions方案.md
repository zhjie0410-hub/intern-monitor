# 多公司抓取 + GitHub Actions 每日更新 · 可行性方案

> 状态：**待确认**　｜　更新：2026-11-22
> 需求来源：第一批 / 第二批 / 第三批全部接入（22 家）+ 关键词加「风控策略」+ 记录每家的做法 + Actions 每天更新

---

## 一、结论先说

| 问题 | 结论 |
|---|---|
| 22 家能不能都抓到？ | **大部分能**，但要分三种情况：纯接口（简单）、SPA+浏览器（中等）、登录墙/境外站（困难或放弃） |
| GitHub Actions 能不能每天跑？ | **技术上能**，但有一个**必须先验证的前提**：Actions 的海外 IP 能不能访问这些国内站点 |
| 要不要一开始就全上 22 家？ | **不要**。先验证 Actions 连通性 + 本地做 3 家，再批量 |

**最大的风险不是写代码，是 IP。** 我这边的探测是在国内网络下做的：

```
可达（17 家）：字节 腾讯 美团 阿里 京东 百度 快手 小红书 拼多多 网易
              蚂蚁 小米 SHEIN 米哈游 华为
不可达（6 家）：滴滴  哔哩哔哩  携程  蔚来  货拉拉  shopee
异常（2 家）：  得物 404   顺丰 502
```

GitHub Actions 的 runner 在**美国/欧洲**，这些站点对海外 IP 的反应**完全未知**——有的可能更快（CDN），有的会超时或弹验证码。**这个必须先测。**

---

## 二、第 0 步：先做一个 Actions 连通性探针（30 分钟）

在仓库里加一个只跑一次的手动 workflow，逐个域名 curl，输出状态与耗时：

```yaml
name: probe
on: workflow_dispatch
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: 探测各家官网可达性
        run: |
          while read name url; do
            code=$(curl -o /dev/null -s -w '%{http_code} %{time_total}s' --max-time 15 "$url" || echo "TIMEOUT")
            echo "$name | $code" | tee -a probe.txt
          done <<'EOF'
          字节跳动 https://jobs.bytedance.com/campus
          腾讯 https://join.qq.com/post.html
          ...
          EOF
      - uses: actions/upload-artifact@v4
        with: { name: probe-result, path: probe.txt }
```

**这一步的产出决定后面怎么做**：
- 全部可达 → 直接按计划上
- 部分不可达 → 那些公司改用「本地跑 + 手动 commit」（或放弃 Actions 全自动）
- 腾讯接口可达但浏览器不行 → 腾讯走 HTTP（本来就不需要浏览器）

---

## 三、22 家的抓取方式预判

按实现难度分三类，直接影响工作量：

### A 类：纯 HTTP 接口（1-2 小时/家）

| 公司 | 依据 | 备注 |
|---|---|---|
| **腾讯** | ✅ 已跑通 | `searchPosition` + `getJobDetailsByPostId`，无签名无风控 |
| 竞品可参照 | 有待验证 | 大厂校招站多数是 Vue/React + REST |

### B 类：SPA + 浏览器（半天/家）

页面能访问但数据前端渲染，要用 Playwright：

| 公司 | 已知情况 |
|---|---|
| **字节跳动** | ✅ 已跑通（`?current&limit` 分页 + 拦截接口响应拿 JD/时间） |
| 美团 | 校招站跳社招站，站内筛实习生 |
| 得物 | 首页 404，需找真实入口（可能是 campus.dewu.com/xxx） |
| 百度 | 页面信息最友好，疑似半 SSR |
| 京东 / 快手 / 小红书 / 拼多多 / 网易 / 蚂蚁 / 小米 | 待逐个摸接口 |
| SHEIN / 米哈游 | 境外/游戏站，注意 IP 与语言 |
| 华为 | career.huawei.com/cn，流程特殊（勇敢星计划） |

### C 类：困难或建议放弃

| 公司 | 问题 |
|---|---|
| 滴滴 / 哔哩哔哩 / 携程 / 蔚来 / 货拉拉 / shopee | 当前网络下**直接连不上**（URLError），先解决可达性 |
| 顺丰 | 502（站点维护或反爬） |
| 得物 | 主域名 404 |

> 这 7 家建议放最后，如果 Actions 也连不上就明确不做，不浪费时间。

---

## 四、关键词统一（7 个）

```yaml
keywords:
  - 数据分析
  - 商业分析
  - 数据科学
  - 策略运营
  - 经营分析
  - 用户增长
  - 风控策略        # ← 本次新增
```

方向白名单同步加「风控策略」（注意：风控策略岗位可能叫「风控策略分析师」「风控建模」，要不要一并收，你定）。

---

## 五、「记录每家怎么做的」产出物

新增 `docs/公司接入记录.md`，一家一行，字段固定：

| 公司 | 入口 URL | 抓取方式 | 接口 / 选择器 | 分页参数 | 是否有发布时间 | 28届过滤依据 | 难度 | 坑 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| 字节跳动 | jobs.bytedance.com/campus | 浏览器 + 拦截响应 | `POST /api/v1/search/job/posts` | `current` / `limit=100` | ✅ `publish_time` | `work_type=实习` + 排除「2027届校园招聘」 | ★ | SPA；接口有签名需走浏览器；标题/城市在 DOM 里 | ✅ |
| 腾讯 | join.qq.com/post.html | 纯 HTTP | `POST /api/v1/position/searchPosition`；`GET /api/v1/jobDetails/getJobDetailsByPostId` | `pageIndex` / `pageSize=100` | ❌ 不提供 | `projectMappingIdList=[104]`（日常实习） | ★ | 项目 id 104=日常实习；无发布时间，用 first_seen 补 | ✅ |
| 美团 | … | … | … | … | … | … | ★★ | … | ⏳ |

这张表就是「怎么做的」的最终记录，也是别人接手时的说明书。

同时每家适配器文件头部写 docstring（像 `sites/tencent.py` 那样），把接口、参数、坑都记在代码里。

---

## 六、GitHub Actions 方案

### 6.1 workflow 结构

```yaml
name: daily-scan          # 每天更新岗位数据
on:
  schedule:
    - cron: '0 22 * * *'   # UTC 22:00 = 北京时间 06:00（趁早上看数据）
  workflow_dispatch:        # 支持手动触发
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: 装依赖
        run: |
          pip install -r requirements.txt
          python -m playwright install --with-deps chromium   # 注意：runner 没有 msedge
      - name: 抓取
        run: python scan.py --pages 15
      - name: 生成看板
        run: python tools/build_dashboard.py
      - name: 提交数据
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/ && git commit -m "chore: 每日岗位数据 $(date +%F)" || echo "无变化"
          git push
```

### 6.2 必须处理的 6 个现实问题

| 问题 | 处理 |
|---|---|
| **runner 没有 msedge** | 代码里 channel 改成「优先 msedge → 回落 chromium」，Actions 里用 chromium |
| **海外 IP 访问国内站** | 第 0 步探针验证；不可达的公司走「本地跑 + 手动 commit」 |
| **cron 延迟** | GitHub 定时任务高峰期可能延后 10-40 分钟，可接受；不要求精确 |
| **数据提交权限** | `GITHUB_TOKEN` 默认有写权限，需在仓库 Settings → Actions → Workflow permissions 选 "Read and write" |
| **仓库公开性** | 岗位数据是公开信息，可公开；但**不要**把 `已投标记`、个人简历放进去 |
| **免费额度** | public 仓库无限；private 每月 2000 分钟，每天 15 分钟 ≈ 450 分钟/月，够用 |

### 6.3 可选加分项

- **GitHub Pages**：把 `data/dashboard/看板.html` 发布成网页，手机也能看（不用下载）
- **Artifact**：每次跑把 CSV 存成 artifact，保留 90 天历史
- **失败通知**：抓取失败时发 issue 或邮件

---

## 七、合规与频率

- 22 家 × 每天 1 次，每家请求量：列表 5-40 次 + 详情 N 次 → **单站点每天几十次请求**，属于正常翻阅量级
- 全部串行 + 随机间隔（0.3-1 秒），不并发打一家
- 遇到验证码/风控立即停该站点，不重试
- 只抓公开展示的岗位信息

---

## 八、建议执行顺序（分四步，每步可验收）

| 步骤 | 内容 | 产出 | 耗时 |
|---|---|---|---|
| **S0** | Actions 连通性探针 | 一张「Actions 能否访问各家」的表 | 30 分钟 |
| **S1** | 本地做 3 家：百度、美团、快手（选可达且岗位量大的） | 3 个适配器 + 接入记录 | 1-2 天 |
| **S2** | 批量补完可达的 12-15 家 | 20 家左右的数据 | 3-5 天 |
| **S3** | 上 Actions：每日抓取 + 自动 commit + Pages | 每天自动更新的看板 | 半天 |

**不建议一上来做 22 家**：如果 S0 发现 Actions 只能访问一半，S2 的优先级要重排，先做 Actions 能访问的那些。

---

## 九、要你拍板的三件事

1. **「风控策略」是否连带收这些近义词**：风控策略分析师 / 风控建模 / 风控算法 / 反作弊？
2. **仓库公开还是私有**：公开可以用 Pages 免费看，但别人也能看到你的数据；私有则看板只能本地开。
3. **先做 S0（探针）还是先做 S1（本地 3 家）**？
   - 我建议 **S0 先做**：30 分钟就能知道 22 家里有几家能自动跑，直接决定后面要不要做那么多家。
