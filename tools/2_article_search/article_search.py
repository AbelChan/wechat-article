"""
工具2: 相关文章搜索 & 存储
针对筛选出的热点，从微信、网页、头条、知乎搜索相关文章，提取正文并保存到本地。

用法:
    python -m tools.2_article_search.article_search
    python -m tools.2_article_search.article_search --date 2026-05-12
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
from loguru import logger
from rich.console import Console
from rich.progress import track

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.utils import (
    DATA_DIR, get_session, load_config, load_json, new_id,
    now_str, random_delay, save_json, today_str
)

console = Console()


# ─────────────────────────────────────────────
# 文章抓取工具
# ─────────────────────────────────────────────

def extract_text_from_html(html: str, min_length: int = 300) -> str:
    """从 HTML 中提取正文"""
    soup = BeautifulSoup(html, "lxml")
    # 移除脚本/样式/导航
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # 清理多余空行
    lines = [l for l in text.splitlines() if len(l.strip()) > 10]
    return "\n".join(lines)


def search_weixin(session, keyword: str, max_results: int = 5) -> list[dict]:
    """搜狗微信搜索"""
    url = "https://weixin.sogou.com/weixin"
    params = {"type": "2", "query": keyword, "page": 1}
    headers = {
        "Referer": "https://weixin.sogou.com/",
        "Cookie": "SUV=1234; SUID=1234;",
    }
    articles = []
    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".news-list li")[:max_results]
        for item in items:
            title_el = item.select_one("h3 a")
            summary_el = item.select_one("p.txt-info")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = title_el.get("href", "")
            summary = summary_el.get_text(strip=True) if summary_el else ""
            articles.append({
                "id": new_id(),
                "platform": "weixin",
                "title": title,
                "url": link,
                "content": summary,
                "collected_at": now_str(),
            })
        logger.info(f"微信搜索 [{keyword}]: {len(articles)} 篇")
    except Exception as e:
        logger.error(f"微信搜索失败: {e}")
    return articles


def search_web_baidu(session, keyword: str, max_results: int = 5) -> list[dict]:
    """百度网页搜索"""
    url = "https://www.baidu.com/s"
    params = {"wd": keyword, "rn": max_results}
    headers = {"Referer": "https://www.baidu.com/"}
    articles = []
    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".result.c-container")[:max_results]
        for item in items:
            title_el = item.select_one("h3 a")
            abstract_el = item.select_one(".c-abstract")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = title_el.get("href", "")
            abstract = abstract_el.get_text(strip=True) if abstract_el else ""
            articles.append({
                "id": new_id(),
                "platform": "web",
                "title": title,
                "url": link,
                "content": abstract,
                "collected_at": now_str(),
            })
        logger.info(f"百度搜索 [{keyword}]: {len(articles)} 篇")
    except Exception as e:
        logger.error(f"百度搜索失败: {e}")
    return articles


def search_toutiao(session, keyword: str, max_results: int = 5) -> list[dict]:
    """今日头条搜索"""
    url = "https://www.toutiao.com/search/"
    params = {"keyword": keyword}
    headers = {"Referer": "https://www.toutiao.com/"}
    articles = []
    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # 头条搜索结果通常由JS渲染，尝试从script标签提取数据
        scripts = soup.find_all("script")
        import json
        for script in scripts:
            text = script.string or ""
            if "articleList" in text or "article_list" in text:
                match = re.search(r'"articles"\s*:\s*(\[.*?\])', text, re.DOTALL)
                if match:
                    try:
                        items = json.loads(match.group(1))
                        for item in items[:max_results]:
                            articles.append({
                                "id": new_id(),
                                "platform": "toutiao",
                                "title": item.get("title", ""),
                                "url": item.get("article_url", ""),
                                "content": item.get("abstract", ""),
                                "collected_at": now_str(),
                            })
                    except Exception:
                        pass
                break
        # 回退：解析HTML结构
        if not articles:
            items = soup.select(".article-info")[:max_results]
            for item in items:
                title_el = item.select_one("a.title")
                if title_el:
                    articles.append({
                        "id": new_id(),
                        "platform": "toutiao",
                        "title": title_el.get_text(strip=True),
                        "url": title_el.get("href", ""),
                        "content": "",
                        "collected_at": now_str(),
                    })
        logger.info(f"头条搜索 [{keyword}]: {len(articles)} 篇")
    except Exception as e:
        logger.error(f"头条搜索失败: {e}")
    return articles


def search_zhihu(session, keyword: str, max_results: int = 5) -> list[dict]:
    """知乎搜索"""
    url = "https://www.zhihu.com/api/v4/search_v3"
    params = {
        "t": "general",
        "q": keyword,
        "correction": 1,
        "offset": 0,
        "limit": max_results,
        "search_source": "Normal",
    }
    headers = {
        "Referer": f"https://www.zhihu.com/search?q={quote(keyword)}&type=content",
        "x-requested-with": "fetch",
    }
    articles = []
    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        for item in items[:max_results]:
            obj = item.get("object", {})
            obj_type = obj.get("type", "")
            if obj_type == "answer":
                title = obj.get("question", {}).get("title", "")
                content = BeautifulSoup(obj.get("content", ""), "lxml").get_text()[:500]
                url_path = f"https://www.zhihu.com/question/{obj.get('question', {}).get('id')}"
            elif obj_type == "article":
                title = obj.get("title", "")
                content = BeautifulSoup(obj.get("excerpt", ""), "lxml").get_text()[:500]
                url_path = obj.get("url", "")
            else:
                continue
            if title:
                articles.append({
                    "id": new_id(),
                    "platform": "zhihu",
                    "title": title,
                    "url": url_path,
                    "content": content,
                    "collected_at": now_str(),
                })
        logger.info(f"知乎搜索 [{keyword}]: {len(articles)} 篇")
    except Exception as e:
        logger.error(f"知乎搜索失败: {e}")
    return articles


def fetch_article_content(session, url: str, min_length: int = 300) -> str:
    """抓取文章正文"""
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        content = extract_text_from_html(resp.text)
        if len(content) >= min_length:
            return content
    except Exception as e:
        logger.debug(f"抓取正文失败 {url}: {e}")
    return ""


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def run(date: str = None) -> dict[str, list[dict]]:
    config = load_config()
    date = date or today_str()
    hot_topics_path = DATA_DIR / "hot_topics" / f"{date}.json"

    if not hot_topics_path.exists():
        console.print(f"[red]未找到热点文件: {hot_topics_path}，请先运行工具1[/red]")
        return {}

    data = load_json(hot_topics_path)
    topics = data.get("topics", [])
    max_per_topic = config["article_search"]["max_per_topic"]
    min_length = config["article_search"]["min_content_length"]
    sources = config["article_search"]["sources"]

    console.print(f"[bold cyan]═══ 工具2: 文章搜索 (共{len(topics)}个热点) ═══[/bold cyan]")

    session = get_session()
    all_results: dict[str, list[dict]] = {}

    searchers = {
        "weixin": search_weixin,
        "web": search_web_baidu,
        "toutiao": search_toutiao,
        "zhihu": search_zhihu,
    }

    for topic in track(topics[:10], description="搜索文章中..."):
        keyword = topic["title"]
        topic_id = topic["id"]
        topic_articles = []

        for source in sources:
            if source in searchers:
                articles = searchers[source](session, keyword, max_per_topic)
                # 尝试抓取正文（仅对内容不足的文章）
                for art in articles:
                    if len(art.get("content", "")) < min_length and art.get("url"):
                        random_delay(0.5, 1.5)
                        art["content"] = fetch_article_content(session, art["url"], min_length) or art["content"]
                    art["topic_id"] = topic_id
                    art["keyword"] = keyword
                topic_articles.extend(articles)
                random_delay(1.0, 2.0)

        # 过滤掉内容过短的文章
        valid_articles = [a for a in topic_articles if len(a.get("content", "")) >= 50]
        all_results[topic_id] = valid_articles

        # 保存单个热点的文章
        out_path = DATA_DIR / "source_articles" / date / f"{topic_id}.json"
        save_json({
            "topic": topic,
            "keyword": keyword,
            "articles": valid_articles,
        }, out_path)

        console.print(f"  [green]✓[/green] [{keyword}] → {len(valid_articles)} 篇文章")

    console.print(f"\n[green]完成！文章已保存到 data/source_articles/{date}/[/green]")
    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="文章搜索工具")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)")
    args = parser.parse_args()
    run(date=args.date)
