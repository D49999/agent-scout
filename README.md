# GitHub 每日 Agent 项目获取器

一个轻量级 Python 应用，每天自动从 GitHub 抓取与 **AI Agent** 相关的开源项目，
基于**近期 star 上涨数**筛选出真正有价值、正在升温的项目，并输出 Markdown / JSON 日报。

## ✨ 特性
- 🔍 **关键词检索**：支持 `ai-agent / llm-agent / autonomous-agent / agent-framework / multi-agent` 等，可自定义
- 📈 **Star 增长估算**：通过 `stargazers` API 的 `starred_at` 时间戳，统计近 N 天新增 star
- 🏆 **综合评分**：`stars_gained + log(total_stars) + log(forks)`，兼顾热度与体量
- 📝 **多格式输出**：自动生成 `reports/agent_daily_YYYY-MM-DD.md` 与 `.json`
- 🤖 **可定时任务化**：配合 `cron` 或 GitHub Actions 即可每日自动运行

## 🚀 快速开始
```bash
pip install requests
export GITHUB_TOKEN=ghp_xxx        # 建议配置，避免限流
python fetcher.py --days 1 --top 20
```

## ⚙️ 参数
| 参数 | 说明 | 默认 |
|---|---|---|
| `--days` | 统计 star 增长的时间窗口（天） | 1 |
| `--top` | 输出 Top N | 20 |
| `--min-stars` | 候选项目最少总 star 数 | 50 |
| `--keywords` | 逗号分隔的关键词 | ai-agent,llm-agent,... |
| `--outdir` | 报告输出目录 | ./reports |
| `--token` | GitHub Token (也可用环境变量) | None |

## 🕒 定时运行（GitHub Actions 示例）
```yaml
name: Daily Agent Report
on:
  schedule: [{cron: "0 1 * * *"}]
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install requests
      - run: python fetcher.py --days 1 --top 30
        env: {GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}}
      - uses: stefanzweifel/git-auto-commit-action@v5
        with: {commit_message: "chore: daily agent report"}
```

## 🧠 工作原理
1. **候选检索**：调用 `/search/repositories`，按关键词 + 最近推送时间 + 最小 star 数过滤
2. **增长估算**：对每个候选仓库，从 `stargazers` 最后一页向前回溯，统计 `starred_at >= now - N天` 的数量
3. **排序输出**：以"近端新增 star"为主键、综合评分为次键排序，输出 Top N

## ⚠️ 注意
- 未配置 token 时，未认证调用限流为 60 次/小时，建议必配 `GITHUB_TOKEN`
- `stargazers` 接口对超大仓库（>10万 star）的回溯会被本工具限制在最近 1000 个内，以控制 API 用量
