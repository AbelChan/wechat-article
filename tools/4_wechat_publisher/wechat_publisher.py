"""
工具4: 配图生成 & 微信公众号发布
1. 用 DALL-E 3 生成文章封面图
2. 上传封面图到微信公众号素材库
3. 创建草稿（或直接发布）

用法:
    python -m tools.4_wechat_publisher.wechat_publisher
    python -m tools.4_wechat_publisher.wechat_publisher --date 2026-05-12
    python -m tools.4_wechat_publisher.wechat_publisher --article-id abc123 --publish
"""

import argparse
import io
import os
import sys
import time
from pathlib import Path

import requests
from loguru import logger
from rich.console import Console
from rich.progress import track

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.utils import (
    DATA_DIR, load_config, load_json, now_str, save_json, today_str
)

console = Console()

WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"


# ─────────────────────────────────────────────
# 微信公众号 API
# ─────────────────────────────────────────────

class WeChatClient:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._access_token = None
        self._token_expires_at = 0

    @property
    def access_token(self) -> str:
        if not self._access_token or time.time() >= self._token_expires_at:
            self._refresh_token()
        return self._access_token

    def _refresh_token(self):
        url = f"{WECHAT_API_BASE}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"获取 access_token 失败: {data}")
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 7200) - 300
        logger.info("微信 access_token 已刷新")

    def upload_image(self, image_bytes: bytes, filename: str = "cover.jpg") -> str:
        """上传永久素材图片，返回 media_id"""
        url = f"{WECHAT_API_BASE}/material/add_material"
        params = {"access_token": self.access_token, "type": "image"}
        files = {"media": (filename, image_bytes, "image/jpeg")}
        resp = requests.post(url, params=params, files=files, timeout=30)
        data = resp.json()
        if "media_id" not in data:
            raise RuntimeError(f"上传图片失败: {data}")
        logger.info(f"图片上传成功: media_id={data['media_id']}")
        return data["media_id"]

    def create_draft(self, articles: list[dict]) -> str:
        """创建草稿，返回 media_id"""
        url = f"{WECHAT_API_BASE}/draft/add"
        params = {"access_token": self.access_token}
        payload = {"articles": articles}
        resp = requests.post(url, params=params, json=payload, timeout=15)
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"创建草稿失败: {data}")
        logger.info(f"草稿创建成功: media_id={data['media_id']}")
        return data["media_id"]

    def publish_draft(self, media_id: str) -> str:
        """发布草稿，返回 publish_id"""
        url = f"{WECHAT_API_BASE}/freepublish/submit"
        params = {"access_token": self.access_token}
        payload = {"media_id": media_id}
        resp = requests.post(url, params=params, json=payload, timeout=15)
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"发布失败: {data}")
        logger.info(f"发布成功: publish_id={data.get('publish_id')}")
        return data.get("publish_id", "")


# ─────────────────────────────────────────────
# 配图生成
# ─────────────────────────────────────────────

def generate_cover_image(keyword: str, title: str, config: dict) -> bytes:
    """使用 DALL-E 3 生成封面图，返回图片字节"""
    import openai

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 OPENAI_API_KEY")

    client = openai.OpenAI(api_key=api_key)
    image_config = config["openai"]

    prompt = (
        f"为微信公众号文章创建一张吸引人的封面图。"
        f"文章话题：{keyword}。文章标题：{title}。"
        f"风格要求：简洁大气，适合中国读者，色彩鲜明，专业感强，"
        f"不要包含任何文字。横版构图，适合公众号封面比例。"
    )

    response = client.images.generate(
        model=image_config["image_model"],
        prompt=prompt,
        size=image_config["image_size"],
        quality=image_config["image_quality"],
        n=1,
        response_format="url",
    )

    image_url = response.data[0].url
    img_resp = requests.get(image_url, timeout=30)
    img_resp.raise_for_status()
    logger.info(f"封面图生成成功 [{keyword}]")
    return img_resp.content


def save_cover_image_locally(image_bytes: bytes, article_id: str, date: str) -> Path:
    """将封面图保存到本地"""
    img_dir = DATA_DIR / "final_articles" / date / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    img_path = img_dir / f"{article_id}_cover.jpg"
    with open(img_path, "wb") as f:
        f.write(image_bytes)
    logger.info(f"封面图已保存: {img_path}")
    return img_path


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def process_article(article: dict, wechat: WeChatClient, config: dict, date: str, auto_publish: bool) -> dict:
    """处理单篇文章：生成配图 → 上传 → 创建草稿 → (发布)"""
    keyword = article.get("keyword", "")
    title = article.get("title", "")
    article_id = article.get("topic_id", article.get("id", "unknown"))

    # 生成封面图
    console.print(f"  生成配图: [bold]{title[:30]}[/bold]...")
    try:
        image_bytes = generate_cover_image(keyword, title, config)
        img_path = save_cover_image_locally(image_bytes, article_id, date)
        article["cover_image_path"] = str(img_path)
    except Exception as e:
        console.print(f"  [yellow]配图生成失败，跳过: {e}[/yellow]")
        image_bytes = None

    # 上传封面图
    thumb_media_id = None
    if image_bytes:
        try:
            thumb_media_id = wechat.upload_image(image_bytes, filename=f"{article_id}.jpg")
            article["thumb_media_id"] = thumb_media_id
        except Exception as e:
            console.print(f"  [yellow]图片上传失败: {e}[/yellow]")

    # 构建微信文章对象
    wx_article = {
        "title": title,
        "author": "小编",
        "content": article.get("html_content", article.get("body", "")),
        "content_source_url": "",
        "digest": article.get("body", "")[:120].replace("\n", ""),
        "show_cover_pic": 1 if thumb_media_id else 0,
    }
    if thumb_media_id:
        wx_article["thumb_media_id"] = thumb_media_id

    # 创建草稿
    try:
        draft_media_id = wechat.create_draft([wx_article])
        article["draft_media_id"] = draft_media_id
        article["draft_created_at"] = now_str()
        console.print(f"  [green]✓ 草稿已创建[/green]")
    except Exception as e:
        console.print(f"  [red]✗ 草稿创建失败: {e}[/red]")
        return article

    # 发布
    if auto_publish:
        try:
            publish_id = wechat.publish_draft(draft_media_id)
            article["publish_id"] = publish_id
            article["published"] = True
            article["published_at"] = now_str()
            console.print(f"  [green]✓ 已发布！publish_id={publish_id}[/green]")
        except Exception as e:
            console.print(f"  [red]✗ 发布失败: {e}[/red]")

    return article


def run(date: str = None, article_id: str = None, auto_publish: bool = False) -> list[dict]:
    config = load_config()
    date = date or today_str()
    final_dir = DATA_DIR / "final_articles" / date

    if not final_dir.exists():
        console.print(f"[red]未找到文章目录: {final_dir}，请先运行工具3[/red]")
        return []

    app_id = os.getenv("WECHAT_APP_ID")
    app_secret = os.getenv("WECHAT_APP_SECRET")
    if not app_id or not app_secret:
        console.print("[red]未设置 WECHAT_APP_ID / WECHAT_APP_SECRET 环境变量[/red]")
        return []

    wechat = WeChatClient(app_id, app_secret)
    auto_publish = auto_publish or config["publisher"]["auto_publish"]

    console.print(f"[bold cyan]═══ 工具4: 配图 & 发布 (auto_publish={auto_publish}) ═══[/bold cyan]")

    json_files = list(final_dir.glob("*.json"))
    if article_id:
        json_files = [f for f in json_files if f.stem == article_id]

    # 过滤掉已发布的
    pending_files = []
    for f in json_files:
        data = load_json(f)
        if not data.get("published"):
            pending_files.append((f, data))

    if not pending_files:
        console.print("[yellow]没有待发布的文章[/yellow]")
        return []

    console.print(f"  找到 [green]{len(pending_files)}[/green] 篇待发布文章")
    results = []

    for json_file, article in pending_files:
        title = article.get("title", json_file.stem)
        console.print(f"\n  处理: [bold]{title[:40]}[/bold]")
        updated = process_article(article, wechat, config, date, auto_publish)
        save_json(updated, json_file)
        results.append(updated)

    published = sum(1 for r in results if r.get("published"))
    drafted = sum(1 for r in results if r.get("draft_media_id") and not r.get("published"))
    console.print(f"\n[green]完成！{published} 篇已发布，{drafted} 篇已保存为草稿[/green]")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="配图生成 & 公众号发布工具")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--article-id", type=str, help="指定文章ID")
    parser.add_argument("--publish", action="store_true", help="直接发布（默认仅保存草稿）")
    args = parser.parse_args()
    run(date=args.date, article_id=args.article_id, auto_publish=args.publish)
