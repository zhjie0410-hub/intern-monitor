# 部署到 GitHub（定时更新 + 手机看板）

> 目标：每天自动抓一次，结果推到仓库，手机/任何电脑打开网址就能看、就能点「详情」去投。
> 现状：代码已 commit 到本地仓库，**还差你把它推上 GitHub**（推送需要你的账号，我这边没有凭证）。

---

## 一、建仓库并推送（3 步）

### 1. 在 GitHub 建一个空仓库

- 打开 https://github.com/new
- Repository name：`intern-monitor`（随便，记住就行）
- 选 **Public**（Pages 免费版必须是 public）
- **不要**勾 Add README / .gitignore / license（保持空仓库）

### 2. 本地推上去

在 `D:\ds开题报告\大厂实习监控` 里执行（把 `<你的用户名>` 换成你的）：

```bash
git remote add origin https://github.com/<你的用户名>/intern-monitor.git
git branch -M main
git push -u origin main
```

> 第一次 push 会弹窗要账号密码。GitHub 现在不接受密码，要 **Personal Access Token**：
> Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token → 勾 `repo` → 复制那串 token 当密码用。

### 3. 开两个开关（很重要，否则 Actions 跑不起来）

| 开关 | 位置 | 设成 |
|---|---|---|
| **Actions 写权限** | Settings → Actions → General → Workflow permissions | 选 **Read and write permissions** → Save |
| **Pages** | Settings → Pages → Build and deployment | Source: **Deploy from a branch** → Branch: **main** / folder: **/docs** → Save |

---

## 二、验证

1. 打开仓库的 **Actions** 标签
2. 左边选「每日抓取实习岗位」→ 右边 **Run workflow** → Run
3. 等 20-40 分钟（要跑 111 页快手），看是否变绿
4. 绿了之后，`docs/index.html` 会被自动提交，手机打开：

```
https://<你的用户名>.github.io/intern-monitor/
```

---

## 三、定时规则

```yaml
schedule:
  - cron: "30 21 * * *"   # UTC 21:30 = 北京 05:30
```

GitHub 的 cron 通常延迟 **10-40 分钟**，凌晨跑完，早上起来就能看。

---

## 四、⚠️ 一个必须先验证的风险

GitHub Actions 跑在**海外机房**（美国/欧洲），而我们要抓的是国内招聘站。

| 可能的情况 | 表现 |
|---|---|
| 站点拦海外 IP / 需要国内 CDN | 抓到 0 条，或请求超时 |
| 正常 | 抓到和本地差不多的条数 |

**所以第 2 步「Run workflow」一定要先手动跑一次看结果。** 如果真的被拦，有两个后路：

### 后路 A：用你自己的电脑定时跑（推荐，最稳）

Windows 任务计划，每天 6 点跑 `tools/run_daily.ps1`：

```powershell
schtasks /create /tn "实习岗位每日抓取" /tr "powershell -ExecutionPolicy Bypass -File D:\ds开题报告\大厂实习监控\tools\run_daily.ps1" /sc daily /st 06:00 /rl highest
```

它会生成 `docs/index.html`，再 `git push` 一下，手机照样能看。
缺点是电脑得开着。

### 后路 B：GitHub 上换自托管 runner

在你自己电脑上装一个 GitHub Actions self-hosted runner（走你的家庭网络），
workflow 里把 `runs-on: ubuntu-latest` 改成 `runs-on: self-hosted`。
这样 Actions 用的是你的 IP，站点不会拦。

---

## 五、手机上看板的限制（提前说清）

| 功能 | 手机能用吗 |
|---|---|
| 看岗位、筛选、排序 | ✅ |
| 点「详情」跳官网 | ✅ |
| 导出 CSV | ✅（手机浏览器支持下载） |
| **「标记投递」** | ⚠️ 存在**浏览器本地**（localStorage），手机上标的，电脑上不同步 |

标记不同步是因为这是纯静态页，没有后端。如果要跨设备同步，得加一个存储服务（比如 Supabase 免费版），那是另一个工程量。

**折中方案**：用「导出 CSV」记录已投的，或者在手机上也标一遍。

---

## 六、每天会变的东西

Actions 每次只提交这两个文件，仓库不会膨胀：

```
data/latest/jobs.csv     ← 最新一份岗位表
docs/index.html          ← 看板（内含数据）
```

`data/exports/`、`logs/`、`data/snapshots/`（已投标记）都在 `.gitignore` 里，**不会上传**。
