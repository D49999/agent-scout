"""
GitHub 每日 Agent 项目获取器
============================
功能：
  - 通过 GitHub Search API 抓取近期与 AI Agent 相关的开源项目
  - 计算每个项目近 N 天的 star 上涨数（基于 stargazers 时间序列）
  - 按 star 增长量排序，筛选有价值的项目
  - 输出 Markdown / JSON 日报

使用：
  export GITHUB_TOKEN=ghp_xxx        # 强烈建议配置，否则会触发限流
  python fetcher.py --days 1 --top 20 --keywords "agent,llm-agent,autonomous-agent"
"""

from __future__ import annotations
import os
import json
import time
import argparse
import datetime as dt
from dataclasses import dataclass, asdict
from typing import List, Optional

import requests

GITHUB_API = "https://api.github.com"


# ----------------------------- 数据结构 -----------------------------
@dataclass
class RepoInfo:
    full_name: str
    html_url: str
    description: str
    language: str
    stars_total: int
    stars_gained: int          # 近 N 天新增 star 数
    forks: int
    topics: List[str]
    created_at: str
    pushed_at: str
    score: float               # 综合评分


# ----------------------------- 抓取器 -----------------------------
class GitHubAgentFetcher:
    def __init__(self, token: Optional[str] = None, days: int = 1):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.days = days
        self.session = requests.Session()
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers.update(headers)

    # -------- 1. 搜索候选仓库 --------
    def search_candidates(
        self,
        keywords: List[str],
        min_stars: int = 50,
        max_pages: int = 3,
    ) -> List[dict]:
        """
        通过 GitHub Search API 检索 agent 相关项目。
        采用 topic 检索（更精准）+ 关键词回退检索（更广覆盖），合并去重。
        """
        # 用近 90 天的活跃度过滤，避免日期窗口太窄导致零结果
        since = (dt.date.today() - dt.timedelta(days=90)).isoformat()

        seen, items = set(), []

        # 构造多组查询：topic 精准 + in:name,description 兜底
        queries = []
        for k in keywords:
            queries.append(f'topic:{k} stars:>={min_stars} pushed:>={since}')
        # 兜底：在仓库名/描述里搜 "agent"，再叠加 llm/ai 限定
        queries.append(f'agent llm in:name,description stars:>={min_stars} pushed:>={since}')
        queries.append(f'ai-agent in:name,description stars:>={min_stars} pushed:>={since}')

        for q in queries:
            for page in range(1, max_pages + 1):
                r = self.session.get(
                    f"{GITHUB_API}/search/repositories",
                    params={"q": q, "sort": "stars", "order": "desc",
                            "per_page": 100, "page": page},
                    timeout=30,
                )
                if r.status_code != 200:
                    print(f"[WARN] search failed q={q!r} code={r.status_code} msg={r.text[:120]}")
                    break
                batch = r.json().get("items", [])
                if not batch:
                    break
                for repo in batch:
                    if repo["full_name"] not in seen:
                        seen.add(repo["full_name"])
                        items.append(repo)
                time.sleep(1)
        print(f"[INFO] 合并去重后候选数: {len(items)}")
        return items


    # -------- 2. 估算近 N 天的 star 增长 --------
    def estimate_recent_stars(self, full_name: str, total_stars: int) -> int:
        """
        通过 stargazers API（带时间戳）取最后一页的近端时间，
        二分式估算近 days 天内的新增 star 数。

        为节约 API 调用，这里采用"分页探针"策略：
          - 每页 100 条，从最后一页向前扫描
          - 一旦发现 starred_at < cutoff，则停止
        """
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=self.days)
        headers = {"Accept": "application/vnd.github.v3.star+json"}
        per_page = 100
        last_page = max(1, (total_stars + per_page - 1) // per_page)

        gained = 0
        # 从最后一页往前回溯，最多扫 10 页（即近 1000 个 star）
        for p in range(last_page, max(last_page - 10, 0), -1):
            r = self.session.get(
                f"{GITHUB_API}/repos/{full_name}/stargazers",
                params={"per_page": per_page, "page": p},
                headers={**self.session.headers, **headers},
                timeout=30,
            )
            if r.status_code != 200:
                break
            page_items = r.json()
            if not page_items:
                continue
            stop = False
            for item in reversed(page_items):  # 新→旧
                ts = item.get("starred_at")
                if not ts:
                    continue
                t = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
                if t >= cutoff:
                    gained += 1
                else:
                    stop = True
                    break
            if stop:
                break
            time.sleep(0.3)
        return gained

    # -------- 3. 综合评分 --------
    @staticmethod
    def score(stars_gained: int, stars_total: int, forks: int) -> float:
        # 强调"近端增长"，同时奖励一定的项目体量与社区参与
        import math
        return round(
            stars_gained * 1.0
            + math.log1p(stars_total) * 2.0
            + math.log1p(forks) * 1.5,
            2,
        )

    # -------- 4. 主流程 --------
    def run(
        self,
        keywords: List[str],
        top: int = 20,
        min_stars: int = 50,
    ) -> List[RepoInfo]:
        print(f"[INFO] 检索关键词: {keywords}, 时间窗口: 近 {self.days} 天")
        candidates = self.search_candidates(keywords, min_stars=min_stars)
        print(f"[INFO] 候选项目数: {len(candidates)}")

        results: List[RepoInfo] = []
        for i, repo in enumerate(candidates, 1):
            name = repo["full_name"]
            total = repo["stargazers_count"]
            try:
                gained = self.estimate_recent_stars(name, total)
            except Exception as e:
                print(f"[WARN] {name} 估算失败: {e}")
                gained = 0
            info = RepoInfo(
                full_name=name,
                html_url=repo["html_url"],
                description=(repo.get("description") or "").strip(),
                language=repo.get("language") or "",
                stars_total=total,
                stars_gained=gained,
                forks=repo.get("forks_count", 0),
                topics=repo.get("topics", []) or [],
                created_at=repo.get("created_at", ""),
                pushed_at=repo.get("pushed_at", ""),
                score=self.score(gained, total, repo.get("forks_count", 0)),
            )
            results.append(info)
            print(f"  [{i}/{len(candidates)}] {name:<45s} +{gained} stars (total {total})")

        # 按近端增长优先，得分次之
        results.sort(key=lambda x: (x.stars_gained, x.score), reverse=True)
        return results[:top]


# ----------------------------- 输出 -----------------------------
def to_markdown(repos: List[RepoInfo], days: int) -> str:
    today = dt.date.today().isoformat()
    md = [
        f"# 🤖 GitHub Agent 项目日报 ({today})",
        f"> 统计窗口：近 **{days}** 天的 star 增长；按新增 star 数排序\n",
        "| # | 项目 | 新增⭐ | 总⭐ | Fork | 语言 | 描述 |",
        "|---|------|-------|------|------|------|------|",
    ]
    for i, r in enumerate(repos, 1):
        desc = (r.description or "").replace("|", "\\|")[:80]
        md.append(
            f"| {i} | [{r.full_name}]({r.html_url}) | **+{r.stars_gained}** "
            f"| {r.stars_total} | {r.forks} | {r.language} | {desc} |"
        )
    return "\n".join(md)


def save_outputs(repos: List[RepoInfo], outdir: str, days: int):
    os.makedirs(outdir, exist_ok=True)
    today = dt.date.today().isoformat()
    json_path = os.path.join(outdir, f"agent_daily_{today}.json")
    md_path = os.path.join(outdir, f"agent_daily_{today}.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in repos], f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(repos, days))
    print(f"[OK] JSON -> {json_path}")
    print(f"[OK] MD   -> {md_path}")


# ----------------------------- CLI -----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="GitHub 每日 Agent 项目获取器")
    p.add_argument("--days", type=int, default=1, help="统计 star 增长的天数窗口")
    p.add_argument("--top", type=int, default=20, help="输出前 N 个项目")
    p.add_argument("--min-stars", type=int, default=50, help="候选项目最小总 star 数")
    p.add_argument(
        "--keywords",
        type=str,
        default="ai-agent,llm-agent,autonomous-agent,agent-framework,multi-agent",
        help="逗号分隔的关键词列表",
    )
    p.add_argument("--outdir", type=str, default="./reports", help="输出目录")
    p.add_argument("--token", type=str, default=None, help="GitHub Token (可选)")
    return p.parse_args()


def main():
    args = parse_args()
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    fetcher = GitHubAgentFetcher(token=args.token, days=args.days)
    repos = fetcher.run(keywords=keywords, top=args.top, min_stars=args.min_stars)
    save_outputs(repos, args.outdir, args.days)
    print("\n" + to_markdown(repos, args.days))


if __name__ == "__main__":
    main()
