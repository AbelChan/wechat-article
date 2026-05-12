"""
微信公众号自动更新工具 - 主流程编排

按顺序执行四个子工具:
  步骤1: 热榜搜索 & 筛选热点
  步骤2: 搜索相关文章并存储
  步骤3: AI 重写微信公众号文章
  步骤4: 生成配图 & 发布到公众号

用法:
    python main.py                    # 完整流程
    python main.py --step 1           # 只执行步骤1
    python main.py --step 1 2 3       # 执行步骤1-3
    python main.py --step 4 --publish # 执行步骤4并直接发布
    python main.py --date 2026-05-12  # 指定日期
"""

import argparse
import importlib.util
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

console = Console()

TOOL_MODULES = {
    1: ROOT_DIR / "tools" / "1_hot_topics" / "hot_topics.py",
    2: ROOT_DIR / "tools" / "2_article_search" / "article_search.py",
    3: ROOT_DIR / "tools" / "3_article_writer" / "article_writer.py",
    4: ROOT_DIR / "tools" / "4_wechat_publisher" / "wechat_publisher.py",
}

STEP_NAMES = {
    1: "热榜搜索",
    2: "文章搜索",
    3: "AI 写作",
    4: "配图 & 发布",
}


def load_tool(step: int):
    """动态加载工具模块（目录名以数字开头，不能直接 import）"""
    path = TOOL_MODULES[step]
    spec = importlib.util.spec_from_file_location(f"tool_step{step}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(
        description="微信公众号自动更新工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step", nargs="+", type=int, choices=[1, 2, 3, 4],
        help="指定执行的步骤 (1=热榜 2=搜文 3=写作 4=发布)"
    )
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--top", type=int, help="步骤1: 每个平台取前N条热点")
    parser.add_argument("--topic-id", type=str, help="步骤3/4: 只处理指定热点ID")
    parser.add_argument("--publish", action="store_true", help="步骤4: 直接发布（默认仅草稿）")
    args = parser.parse_args()

    steps = args.step or [1, 2, 3, 4]

    console.print(Panel.fit(
        "[bold cyan]微信公众号自动更新工具[/bold cyan]\n"
        f"执行步骤: {[STEP_NAMES[s] for s in steps]}",
        border_style="cyan",
    ))

    # ── 步骤1: 热榜搜索 ──
    if 1 in steps:
        console.rule(f"[bold]步骤1: {STEP_NAMES[1]}")
        tool = load_tool(1)
        hot_topics = tool.run(top_n=args.top)
        if not hot_topics and any(s in steps for s in [2, 3, 4]):
            console.print("[red]未获取到热点，后续步骤终止[/red]")
            return
        console.print(f"[green]步骤1完成: 获取 {len(hot_topics)} 个热点[/green]\n")

    # ── 步骤2: 文章搜索 ──
    if 2 in steps:
        console.rule(f"[bold]步骤2: {STEP_NAMES[2]}")
        tool = load_tool(2)
        articles = tool.run(date=args.date)
        console.print(f"[green]步骤2完成: 搜索完 {len(articles)} 个热点的相关文章[/green]\n")

    # ── 步骤3: AI 写作 ──
    if 3 in steps:
        console.rule(f"[bold]步骤3: {STEP_NAMES[3]}")
        tool = load_tool(3)
        written = tool.run(date=args.date, topic_id=args.topic_id)
        console.print(f"[green]步骤3完成: 生成 {len(written)} 篇文章[/green]\n")

    # ── 步骤4: 配图 & 发布 ──
    if 4 in steps:
        console.rule(f"[bold]步骤4: {STEP_NAMES[4]}")
        tool = load_tool(4)
        published = tool.run(date=args.date, article_id=args.topic_id, auto_publish=args.publish)
        console.print(f"[green]步骤4完成: 处理 {len(published)} 篇文章[/green]\n")

    console.print(Panel.fit("[bold green]全部流程完成！[/bold green]", border_style="green"))


if __name__ == "__main__":
    main()
