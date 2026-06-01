"""
工具1: 热榜搜索 & 筛选
爬取微博、百度、今日头条、抖音热榜，筛选出热点话题并保存到本地。

用法:
    python -m tools.1_hot_topics.hot_topics
    python -m tools.1_hot_topics.hot_topics --top 15
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from loguru import logger
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.utils import (
    DATA_DIR, get_session, load_config, new_id, now_str, random_delay, save_json, today_str
)

console = Console()


# ─────────────────────────────────────────────
# 各平台爬虫
# ─────────────────────────────────────────────

def fetch_weibo_hot(session, top_n: int = 10) -> list[dict]:
    """微博热搜榜"""
    url = "https://weibo.com/ajax/side/hotSearch"
    headers = {
        "Referer": "https://weibo.com/",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("realtime", [])
        results = []
        for i, item in enumerate(items[:top_n]):
            title = item.get("note") or item.get("word", "")
            if not title:
                continue
            results.append({
                "id": new_id(),
                "platform": "weibo",
                "rank": i + 1,
                "title": title,
                "heat": item.get("num", 0),
                "url": f"https://s.weibo.com/weibo?q={title}",
                "collected_at": now_str(),
            })
        logger.info(f"微博热搜: 获取 {len(results)} 条")
        return results
    except Exception as e:
        logger.error(f"微博热搜爬取失败: {e}")
        return []


def fetch_baidu_hot(session, top_n: int = 10) -> list[dict]:
    """百度热搜榜"""
    url = "https://top.baidu.com/board?tab=realtime"
    headers = {
        "Referer": "https://www.baidu.com/",
    }
    try:
        resp = session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".c-single-text-ellipsis")
        results = []
        for i, item in enumerate(items[:top_n]):
            title = item.get_text(strip=True)
            if not title:
                continue
            results.append({
                "id": new_id(),
                "platform": "baidu",
                "rank": i + 1,
                "title": title,
                "heat": 0,
                "url": f"https://www.baidu.com/s?wd={title}",
                "collected_at": now_str(),
            })
        logger.info(f"百度热搜: 获取 {len(results)} 条")
        return results
    except Exception as e:
        logger.error(f"百度热搜爬取失败: {e}")
        return []


def fetch_toutiao_hot(session, top_n: int = 10) -> list[dict]:
    """今日头条热榜"""
    url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
    headers = {
        "Referer": "https://www.toutiao.com/",
    }
    try:
        resp = session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        results = []
        for i, item in enumerate(items[:top_n]):
            title = item.get("Title", "")
            if not title:
                continue
            results.append({
                "id": new_id(),
                "platform": "toutiao",
                "rank": i + 1,
                "title": title,
                "heat": item.get("HotValue", 0),
                "url": item.get("Url", ""),
                "collected_at": now_str(),
            })
        logger.info(f"今日头条热榜: 获取 {len(results)} 条")
        return results
    except Exception as e:
        logger.error(f"今日头条热榜爬取失败: {e}")
        return []


def fetch_douyin_hot(session, top_n: int = 10) -> list[dict]:
    """抖音热点榜"""
    url = "https://www.douyin.com/aweme/v1/hot/search/list/"
    params = {
        "device_platform": "webapp",
        "aid": "6383",
        "count": 50,
    }
    headers = {
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("word_list", [])
        results = []
        for i, item in enumerate(items[:top_n]):
            title = item.get("word", "")
            if not title:
                continue
            results.append({
                "id": new_id(),
                "platform": "douyin",
                "rank": i + 1,
                "title": title,
                "heat": item.get("hot_value", 0),
                "url": f"https://www.douyin.com/search/{title}",
                "collected_at": now_str(),
            })
        logger.info(f"抖音热点: 获取 {len(results)} 条")
        return results
    except Exception as e:
        logger.error(f"抖音热点爬取失败: {e}")
        return []


# ─────────────────────────────────────────────
# 筛选逻辑
# ─────────────────────────────────────────────

def filter_topics(all_topics: list[dict], config: dict) -> list[dict]:
    """
    筛选策略:
    1. 只保留榜单前 min_heat_rank 名内的热点
    2. 去重（不同平台可能有相同热点）
    3. 按出现平台数量排序（多平台同时上榜的优先）
    """
    min_rank = config["hot_topics"].get("min_heat_rank", 20)

    # 过滤排名
    filtered = [t for t in all_topics if t["rank"] <= min_rank]

    # 按标题去重并统计跨平台次数
    title_map: dict[str, dict] = {}
    for topic in filtered:
        title = topic["title"]
        if title not in title_map:
            title_map[title] = {**topic, "platforms": [topic["platform"]], "cross_platform": 1}
        else:
            title_map[title]["platforms"].append(topic["platform"])
            title_map[title]["cross_platform"] += 1

    # 排序：跨平台数量 > 平均排名
    unique = list(title_map.values())
    unique.sort(key=lambda x: (-x["cross_platform"], x["rank"]))

    return unique


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def run(top_n: Optional[int] = None) -> list[dict]:
    config = load_config()
    top_n = top_n or config["hot_topics"]["top_n"]
    session = get_session()

    console.print("[bold cyan]═══ 工具1: 热榜搜索 ═══[/bold cyan]")

    all_topics = []
    platforms = config["hot_topics"]["platforms"]

    fetchers = {
        "weibo": fetch_weibo_hot,
        "baidu": fetch_baidu_hot,
        "toutiao": fetch_toutiao_hot,
        "douyin": fetch_douyin_hot,
    }

    for platform in platforms:
        if platform in fetchers:
            console.print(f"  抓取 [yellow]{platform}[/yellow] 热榜...")
            topics = fetchers[platform](session, top_n)
            all_topics.extend(topics)
            random_delay(1.0, 2.5)

    console.print(f"\n  共抓取 [green]{len(all_topics)}[/green] 条热点，开始筛选...")
    selected = filter_topics(all_topics, config)

    # 展示结果
    table = Table(title=f"筛选结果 (共{len(selected)}条)", show_lines=True)
    table.add_column("排名", style="dim", width=4)
    table.add_column("标题", style="bold")
    table.add_column("平台", style="cyan")
    table.add_column("跨平台", style="green")

    for i, t in enumerate(selected[:20]):
        table.add_row(
            str(i + 1),
            t["title"][:40],
            ", ".join(t.get("platforms", [t["platform"]])),
            str(t.get("cross_platform", 1)),
        )
    console.print(table)

    # 保存
    out_path = DATA_DIR / "hot_topics" / f"{today_str()}.json"
    save_json({"date": today_str(), "total": len(selected), "topics": selected}, out_path)
    console.print(f"\n[green]✓ 已保存到 {out_path}[/green]")

    return selected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="热榜搜索工具")
    parser.add_argument("--top", type=int, help="每个平台取前N条")
    args = parser.parse_args()
    run(top_n=args.top)
