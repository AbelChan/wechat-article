"""
工具3: AI 重写微信公众号文章
读取本地热点文章，调用 Claude API 重写为微信公众号风格文章，保存到本地。

用法:
    python -m tools.3_article_writer.article_writer
    python -m tools.3_article_writer.article_writer --date 2026-05-12 --topic-id abc123
"""

import argparse
import os
import sys
from pathlib import Path

import anthropic
from loguru import logger
from rich.console import Console
from rich.progress import track

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.utils import (
    DATA_DIR, load_config, load_json, new_id, now_str, save_json, today_str
)

console = Console()

WECHAT_ARTICLE_PROMPT = """你是一位资深微信公众号运营专家，擅长写出高阅读量的爆款文章。

## 热点话题
{keyword}

## 参考资料
{reference_articles}

## 写作要求
1. **标题**：吸引眼球，包含热点关键词，字数15-25字，可以使用数字或悬念
2. **开头**：前3行必须抓住读者，可以用问句、数据、故事或反常识的观点引入
3. **正文结构**：
   - 背景/事件介绍（发生了什么）
   - 深度分析（为什么重要/影响是什么）
   - 多角度观点（不同立场的看法）
   - 实际影响（对普通人意味着什么）
4. **结尾**：总结观点 + 引导读者互动（留言/转发）
5. **字数**：{target_length} 字左右
6. **风格**：口语化但有深度，避免过度官方，适当使用emoji增加可读性
7. **分节**：使用「## 小标题」分隔各部分

## 输出格式
直接输出文章内容，第一行是标题（不含"标题："前缀），之后是正文。
"""


def build_reference_text(articles: list[dict], max_chars: int = 8000) -> str:
    """整合参考文章"""
    parts = []
    total = 0
    for i, art in enumerate(articles):
        content = art.get("content", "").strip()
        if not content:
            continue
        snippet = f"【来源{i+1}: {art.get('platform', '')} - {art.get('title', '')}】\n{content[:1500]}"
        if total + len(snippet) > max_chars:
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n\n---\n\n".join(parts) if parts else "暂无参考资料"


def write_article_with_claude(client: anthropic.Anthropic, keyword: str, articles: list[dict], config: dict) -> dict:
    """调用 Claude API 生成文章"""
    target_length = config["article_writer"]["target_length"]
    reference = build_reference_text(articles)

    prompt = WECHAT_ARTICLE_PROMPT.format(
        keyword=keyword,
        reference_articles=reference,
        target_length=target_length,
    )

    try:
        response = client.messages.create(
            model=config["anthropic"]["model"],
            max_tokens=config["anthropic"]["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
        )
        full_text = response.content[0].text.strip()

        # 分离标题和正文
        lines = full_text.splitlines()
        title = lines[0].strip() if lines else keyword
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else full_text

        return {
            "id": new_id(),
            "title": title,
            "body": body,
            "full_text": full_text,
            "word_count": len(full_text.replace(" ", "")),
            "model": config["anthropic"]["model"],
            "created_at": now_str(),
        }
    except Exception as e:
        logger.error(f"Claude API 调用失败: {e}")
        raise


def convert_to_wechat_html(title: str, body: str) -> str:
    """将 Markdown 正文转为微信公众号 HTML 格式"""
    import re

    html_parts = [
        f'<h1 style="text-align:center;font-size:22px;font-weight:bold;margin:20px 0;">{title}</h1>'
    ]

    paragraphs = body.split("\n")
    for line in paragraphs:
        line = line.strip()
        if not line:
            continue
        # 二级标题
        if line.startswith("## "):
            text = line[3:]
            html_parts.append(
                f'<h2 style="font-size:18px;font-weight:bold;color:#333;border-left:4px solid #07C160;'
                f'padding-left:10px;margin:20px 0 10px;">{text}</h2>'
            )
        # 加粗
        elif line.startswith("**") and line.endswith("**"):
            text = line[2:-2]
            html_parts.append(f'<p style="font-weight:bold;margin:8px 0;">{text}</p>')
        else:
            # 处理行内加粗
            line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
            html_parts.append(f'<p style="font-size:16px;line-height:1.8;margin:8px 0;color:#333;">{line}</p>')

    return "\n".join(html_parts)


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def run(date: str = None, topic_id: str = None) -> list[dict]:
    config = load_config()
    date = date or today_str()
    source_dir = DATA_DIR / "source_articles" / date
    output_dir = DATA_DIR / "final_articles" / date

    if not source_dir.exists():
        console.print(f"[red]未找到文章目录: {source_dir}，请先运行工具2[/red]")
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]未设置 ANTHROPIC_API_KEY 环境变量[/red]")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    console.print("[bold cyan]═══ 工具3: AI 写作 ═══[/bold cyan]")

    # 找到所有热点文章文件
    json_files = list(source_dir.glob("*.json"))
    if topic_id:
        json_files = [f for f in json_files if f.stem == topic_id]

    if not json_files:
        console.print(f"[yellow]未找到文章数据[/yellow]")
        return []

    results = []
    for json_file in track(json_files, description="AI 写作中..."):
        data = load_json(json_file)
        topic = data.get("topic", {})
        keyword = data.get("keyword", topic.get("title", ""))
        articles = data.get("articles", [])

        if not articles:
            console.print(f"  [yellow]跳过 [{keyword}]：无参考文章[/yellow]")
            continue

        console.print(f"  正在写作: [bold]{keyword}[/bold] (参考{len(articles)}篇)...")

        try:
            result = write_article_with_claude(client, keyword, articles, config)
            result["topic"] = topic
            result["keyword"] = keyword
            result["topic_id"] = topic.get("id", json_file.stem)
            result["html_content"] = convert_to_wechat_html(result["title"], result["body"])
            result["published"] = False
            result["wechat_media_id"] = None

            # 保存
            out_path = output_dir / f"{result['topic_id']}.json"
            save_json(result, out_path)

            console.print(f"  [green]✓[/green] 《{result['title']}》({result['word_count']}字)")
            results.append(result)
        except Exception as e:
            console.print(f"  [red]✗ 写作失败 [{keyword}]: {e}[/red]")

    console.print(f"\n[green]完成！共生成 {len(results)} 篇文章，保存到 data/final_articles/{date}/[/green]")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 文章写作工具")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--topic-id", type=str, help="指定热点ID，只处理该热点")
    args = parser.parse_args()
    run(date=args.date, topic_id=args.topic_id)
