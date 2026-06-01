"""
工具4: 配图生成 & 公众号草稿自动化
1. 用 DALL-E 3 生成文章封面图（可选）
2. 导出公众号后台可直接使用的发布包
3. 使用 Playwright 自动登录公众号后台并保存草稿

用法:
    python -m tools.4_wechat_publisher.wechat_publisher
    python -m tools.4_wechat_publisher.wechat_publisher --date 2026-05-12
    python -m tools.4_wechat_publisher.wechat_publisher --article-id abc123
"""

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

import requests
from loguru import logger
from rich.console import Console

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tools.utils import (
    DATA_DIR, load_config, load_json, now_str, save_json, today_str
)

console = Console()
WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"


def _build_images_client(config: dict):
    import openai
    image_config = config["images"]
    api_key = os.getenv("IMAGES_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 IMAGES_API_KEY 环境变量")
    return openai.OpenAI(
        api_key=api_key,
        base_url=image_config["base_url"],
        timeout=120,
        max_retries=2,
    )


def generate_cover_image(keyword: str, title: str, config: dict) -> bytes:
    """使用国内大模型 API 生成封面图，返回图片字节"""
    client = _build_images_client(config)
    image_config = config["images"]

    prompt = (
        f"为微信公众号文章创建一张吸引人的封面图。"
        f"文章话题：{keyword}。文章标题：{title}。"
        f"风格要求：简洁大气，适合中国读者，色彩鲜明，专业感强，"
        f"不要包含任何文字。横版构图，适合公众号封面比例。"
    )

    response = client.images.generate(
        model=image_config["model"],
        prompt=prompt,
        size=image_config["image_size"],
        quality=image_config["image_quality"],
        n=1,
        response_format="url",
    )

    image_url = response.data[0].url
    img_resp = requests.get(image_url, timeout=60)
    img_resp.raise_for_status()
    logger.info(f"封面图生成成功 [{keyword}]")
    return img_resp.content


def save_cover_image(image_bytes: bytes, output_dir: Path, article_id: str) -> Path:
    """将封面图保存到指定目录"""
    output_dir.mkdir(parents=True, exist_ok=True)
    img_path = output_dir / f"{article_id}_cover.jpg"
    with open(img_path, "wb") as f:
        f.write(image_bytes)
    logger.info(f"封面图已保存: {img_path}")
    return img_path


def export_publish_package(article: dict, date: str) -> Path:
    """导出可手动发布到公众号后台的发布包"""
    article_id = article.get("topic_id", article.get("id", "unknown"))
    package_dir = DATA_DIR / "publish_packages" / date / article_id
    package_dir.mkdir(parents=True, exist_ok=True)

    title = article.get("title", article_id)
    body = article.get("body", "")
    html_content = article.get("html_content", body)
    digest = body[:120].replace("\n", "")

    (package_dir / "article.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    (package_dir / "article.html").write_text(html_content, encoding="utf-8")
    (package_dir / "title.txt").write_text(title, encoding="utf-8")
    (package_dir / "digest.txt").write_text(digest, encoding="utf-8")
    (package_dir / "publish_steps.txt").write_text(
        "\n".join([
            "公众号后台手动发布步骤：",
            "1. 登录 mp.weixin.qq.com 后进入 内容与互动 -> 草稿箱。",
            "2. 新建图文。",
            "3. 标题直接复制 title.txt。",
            "4. 摘要直接复制 digest.txt。",
            "5. 正文优先使用 article.html 中内容粘贴到编辑器；如格式不理想可改用 article.md。",
            "6. 如果目录中有 *_cover.jpg，则手动上传为封面图。",
            "7. 检查封面、摘要、正文格式后保存草稿或发布。",
        ]),
        encoding="utf-8",
    )

    save_json(
        {
            "title": title,
            "keyword": article.get("keyword", ""),
            "topic_id": article_id,
            "digest": digest,
            "cover_image_path": article.get("cover_image_path"),
            "html_path": str(package_dir / "article.html"),
            "markdown_path": str(package_dir / "article.md"),
            "exported_at": now_str(),
        },
        package_dir / "metadata.json",
    )
    logger.info(f"发布包已导出: {package_dir}")
    return package_dir


class WeChatClient:
    """微信公众号官方接口客户端（AppID + AppSecret）"""

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
        resp = requests.get(
            f"{WECHAT_API_BASE}/token",
            params={
                "grant_type": "client_credential",
                "appid": self.app_id,
                "secret": self.app_secret,
            },
            timeout=15,
        )
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"获取 access_token 失败: {data}")
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 7200) - 300
        logger.info("微信公众号 access_token 已刷新")

    def upload_image(self, image_bytes: bytes, filename: str) -> str:
        resp = requests.post(
            f"{WECHAT_API_BASE}/material/add_material",
            params={"access_token": self.access_token, "type": "image"},
            files={"media": (filename, image_bytes, "image/jpeg")},
            timeout=30,
        )
        data = resp.json()
        if "media_id" not in data:
            raise RuntimeError(f"上传封面图失败: {data}")
        return data["media_id"]

    def create_draft(self, article: dict) -> str:
        resp = requests.post(
            f"{WECHAT_API_BASE}/draft/add",
            params={"access_token": self.access_token},
            json={"articles": [article]},
            timeout=20,
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"创建草稿失败: {data}")
        return data["media_id"]

    def publish_draft(self, media_id: str) -> str:
        resp = requests.post(
            f"{WECHAT_API_BASE}/freepublish/submit",
            params={"access_token": self.access_token},
            json={"media_id": media_id},
            timeout=20,
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"发布失败: {data}")
        return data.get("publish_id", "")


class WeChatDraftAutomator:
    """基于 Playwright 的公众号草稿自动化"""

    def __init__(self, config: dict):
        self.config = config
        self.publisher_config = config["publisher"]
        self.profile_dir = Path(self.publisher_config["browser_profile_dir"])
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.channel = self.publisher_config.get("browser_channel", "auto")
        self.timeout_ms = int(self.publisher_config.get("timeout_ms", 15000))
        self.author = self.publisher_config.get("author", "小编")
        self._pw = None
        self.context = None
        self.page = None

    def _channel_installed(self, channel: str) -> bool:
        if channel == "msedge":
            candidates = [
                Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ]
            return any(path.exists() for path in candidates) or shutil.which("msedge") is not None
        if channel == "chrome":
            candidates = [
                Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            ]
            return any(path.exists() for path in candidates) or shutil.which("chrome") is not None
        return False

    def _candidate_channels(self) -> list[str | None]:
        configured = (self.channel or "auto").strip().lower()
        channels: list[str | None] = []
        if configured and configured != "auto":
            channels.append(configured)
        else:
            for channel in ("msedge", "chrome"):
                if self._channel_installed(channel):
                    channels.append(channel)
        channels.append(None)
        unique: list[str | None] = []
        for channel in channels:
            if channel not in unique:
                unique.append(channel)
        return unique

    def start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "未安装 playwright，请先执行: pip install playwright && playwright install"
            ) from exc

        self._pw = sync_playwright().start()
        errors = []
        for channel in self._candidate_channels():
            launch_args = {
                "user_data_dir": str(self.profile_dir),
                "headless": False,
                "viewport": {"width": 1440, "height": 960},
                "locale": "zh-CN",
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if channel:
                launch_args["channel"] = channel
            try:
                self.context = self._pw.chromium.launch_persistent_context(**launch_args)
                if channel:
                    console.print(f"[cyan]使用浏览器通道: {channel}[/cyan]")
                else:
                    console.print("[cyan]使用 Playwright 自带 Chromium[/cyan]")
                break
            except Exception as exc:
                label = channel or "chromium"
                errors.append(f"{label}: {exc}")
        if not self.context:
            raise RuntimeError(
                "无法启动可用浏览器。请先安装 Edge/Chrome，或执行 `python -m playwright install`。\n"
                + "\n".join(errors)
            )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self.ensure_logged_in()
        return self

    def close(self):
        if self.context:
            self.context.close()
        if self._pw:
            self._pw.stop()

    def ensure_logged_in(self):
        self.page.goto("https://mp.weixin.qq.com/cgi-bin/home", wait_until="domcontentloaded")
        if "cgi-bin" in self.page.url:
            return
        console.print("[yellow]请在打开的浏览器中扫码登录公众号后台，登录完成后脚本会继续[/yellow]")
        self.page.goto("https://mp.weixin.qq.com/", wait_until="domcontentloaded")
        self.page.wait_for_url(re.compile(r"https://mp\.weixin\.qq\.com/cgi-bin/.*"), timeout=0)

    def _get_token(self) -> str:
        for _ in range(3):
            match = re.search(r"token=(\d+)", self.page.url)
            if match:
                return match.group(1)
            self.page.goto("https://mp.weixin.qq.com/cgi-bin/home", wait_until="domcontentloaded")
        raise RuntimeError("未能从公众号后台 URL 中获取 token")

    def _all_targets(self):
        return [self.page] + [frame for frame in self.page.frames if frame != self.page.main_frame]

    def _find_locator(self, selectors: list[str], require_visible: bool = True):
        last_error = None
        for target in self._all_targets():
            for selector in selectors:
                try:
                    locator = target.locator(selector).first
                    if require_visible:
                        locator.wait_for(state="visible", timeout=2000)
                    return locator
                except Exception as exc:
                    last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError(f"未找到元素: {selectors}")

    def _click_text(self, texts: list[str]) -> bool:
        for text in texts:
            for locator in (
                self.page.get_by_role("button", name=text),
                self.page.get_by_text(text, exact=True),
                self.page.get_by_text(text),
            ):
                try:
                    locator.first.click(timeout=2000)
                    return True
                except Exception:
                    continue
        return False

    def _fill_if_found(self, selectors: list[str], value: str) -> bool:
        if not value:
            return False
        try:
            locator = self._find_locator(selectors)
            locator.click()
            locator.fill(value)
            return True
        except Exception:
            return False

    def _set_editor_html(self, html_content: str):
        editor_selectors = [
            "body[contenteditable='true']",
            ".ql-editor",
            "[contenteditable='true'][role='textbox']",
            "div[contenteditable='true']",
        ]
        for target in self._all_targets():
            for selector in editor_selectors:
                try:
                    locator = target.locator(selector).first
                    locator.wait_for(state="visible", timeout=2000)
                    locator.click()
                    locator.evaluate(
                        """(el, html) => {
                            el.innerHTML = html;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }""",
                        html_content,
                    )
                    return
                except Exception:
                    continue
        raise RuntimeError("未找到公众号正文编辑区域")

    def _upload_cover(self, cover_path: str | None) -> bool:
        if not cover_path or not Path(cover_path).exists():
            return False

        self._click_text(["封面和摘要", "封面", "封面图"])
        file_input_selectors = [
            "input[type='file']",
            "input.accept[type='file']",
        ]
        for selector in file_input_selectors:
            try:
                locator = self.page.locator(selector).first
                locator.set_input_files(cover_path, timeout=3000)
                return True
            except Exception:
                continue
        return False

    def _save_draft(self):
        if self._click_text(["保存为草稿", "保存", "草稿箱"]):
            return
        raise RuntimeError("未找到保存草稿按钮")

    def open_new_article_editor(self):
        token = self._get_token()
        editor_url = (
            f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2"
            f"&action=edit&type=10&isNew=1&lang=zh_CN&token={token}"
        )
        self.page.goto(editor_url, wait_until="domcontentloaded")

    def publish_article(self, article: dict):
        title = article.get("title", "")
        body = article.get("body", "")
        digest = body[:120].replace("\n", "")
        html_content = article.get("html_content", body)

        self.open_new_article_editor()
        self._fill_if_found(
            [
                "input[placeholder*='标题']",
                "textarea[placeholder*='标题']",
                "[contenteditable='true'][data-placeholder*='标题']",
            ],
            title,
        )
        self._fill_if_found(
            [
                "input[placeholder*='作者']",
                "textarea[placeholder*='作者']",
            ],
            self.author,
        )
        self._set_editor_html(html_content)
        self._fill_if_found(
            [
                "textarea[placeholder*='摘要']",
                "input[placeholder*='摘要']",
            ],
            digest,
        )
        cover_uploaded = self._upload_cover(article.get("cover_image_path"))
        self._save_draft()
        article["wechat_draft_created"] = True
        article["wechat_draft_created_at"] = now_str()
        article["wechat_cover_uploaded"] = cover_uploaded
        article["manual_publish_status"] = "drafted"
        logger.info(f"公众号草稿已创建: {title}")
        return article


def ensure_cover_and_package(article: dict, config: dict, date: str) -> dict:
    """生成配图并导出发布包，作为自动化前的兜底产物"""
    keyword = article.get("keyword", "")
    title = article.get("title", "")
    article_id = article.get("topic_id", article.get("id", "unknown"))
    package_dir = DATA_DIR / "publish_packages" / date / article_id

    article.pop("thumb_media_id", None)
    if config["publisher"].get("cover_image", True):
        console.print(f"  生成配图: [bold]{title[:30]}[/bold]...")
        try:
            image_bytes = generate_cover_image(keyword, title, config)
            article["cover_image_path"] = str(save_cover_image(image_bytes, package_dir, article_id))
        except Exception as exc:
            article.pop("cover_image_path", None)
            console.print(f"  [yellow]配图生成失败，将继续导出内容包: {exc}[/yellow]")
    else:
        article.pop("cover_image_path", None)
        console.print("  [yellow]已关闭自动配图，直接使用文章内容[/yellow]")

    package_dir = export_publish_package(article, date)
    article["publish_package_dir"] = str(package_dir)
    article["export_ready"] = True
    article["exported_at"] = now_str()
    article["manual_publish_status"] = article.get("manual_publish_status", "pending")
    return article


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    """按字节数截断字符串，避免截断到半个多字节字符"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated.rstrip() + "…"


def build_wechat_article_payload(article: dict, author: str, thumb_media_id: str | None) -> dict:
    body = article.get("body", "")
    title = article.get("title", "")
    title_orig_len = len(title.encode("utf-8"))
    # 微信 draft/add 接口按 UTF-8 字节计算 title，上限约 64 字节
    title = _truncate_to_bytes(title, 60)
    if len(title.encode("utf-8")) < title_orig_len:
        logger.warning(f"标题超出微信字节限制，已自动截断: {article.get('title', '')}")
    payload = {
        "title": title,
        "author": author,
        "content": article.get("html_content", body),
        "digest": body[:54].replace("\n", ""),
        "show_cover_pic": 1 if thumb_media_id else 0,
    }
    if thumb_media_id:
        payload["thumb_media_id"] = thumb_media_id
    return payload


def publish_via_appsecret(
    article: dict,
    client: WeChatClient,
    config: dict,
    date: str,
    auto_publish: bool,
) -> dict:
    """使用微信公众号官方接口上传封面并创建草稿"""
    author = config["publisher"].get("author", "小编")
    article = ensure_cover_and_package(article, config, date)

    thumb_media_id = None
    if config["publisher"].get("cover_image", True):
        cover_path = article.get("cover_image_path")
        if cover_path and Path(cover_path).exists():
            try:
                thumb_media_id = client.upload_image(Path(cover_path).read_bytes(), Path(cover_path).name)
                article["thumb_media_id"] = thumb_media_id
                console.print("  [green]✓ 封面图已上传到公众号素材库[/green]")
            except Exception as exc:
                article["wechat_publish_error"] = str(exc)
                console.print(f"  [yellow]封面图上传失败，将继续尝试创建草稿: {exc}[/yellow]")

    if not thumb_media_id:
        default_id = config["publisher"].get("default_thumb_media_id", "").strip()
        if default_id:
            thumb_media_id = default_id
            console.print("  [cyan]使用 default_thumb_media_id 作为封面[/cyan]")
        else:
            raise RuntimeError(
                "微信草稿 API 要求 thumb_media_id（封面图必须）。"
                "请启用 cover_image: true，或在 config.yaml 的 publisher.default_thumb_media_id "
                "中填入已上传到素材库的图片 media_id。"
            )

    wx_article = build_wechat_article_payload(article, author, thumb_media_id)
    draft_media_id = client.create_draft(wx_article)
    article["draft_media_id"] = draft_media_id
    article["wechat_draft_created"] = True
    article["wechat_draft_created_at"] = now_str()
    article["manual_publish_status"] = "drafted"
    console.print("  [green]✓ 已通过 AppSecret 接口创建公众号草稿[/green]")

    if auto_publish:
        publish_id = client.publish_draft(draft_media_id)
        article["publish_id"] = publish_id
        article["published"] = True
        article["published_at"] = now_str()
        console.print(f"  [green]✓ 已提交发布，publish_id={publish_id}[/green]")

    return article


def run(date: str = None, article_id: str = None, auto_publish: bool = False) -> list[dict]:
    config = load_config()
    date = date or today_str()
    final_dir = DATA_DIR / "final_articles" / date
    publisher_mode = config["publisher"].get("mode", "appsecret")

    if not final_dir.exists():
        console.print(f"[red]未找到文章目录: {final_dir}，请先运行工具3[/red]")
        return []

    console.print(f"[bold cyan]═══ 工具4: 配图 & 发布 (mode={publisher_mode}) ═══[/bold cyan]")

    json_files = list(final_dir.glob("*.json"))
    if article_id:
        json_files = [f for f in json_files if f.stem == article_id]

    pending_files = []
    for f in json_files:
        data = load_json(f)
        if not data.get("published"):
            pending_files.append((f, data))

    if not pending_files:
        console.print("[yellow]没有待处理的文章[/yellow]")
        return []

    console.print(f"  找到 [green]{len(pending_files)}[/green] 篇待处理文章")
    results = []
    automator = None
    wechat_client = None

    try:
        if publisher_mode == "appsecret":
            app_id = os.getenv("WECHAT_APP_ID", "")
            app_secret = os.getenv("WECHAT_APP_SECRET", "")
            if not app_id or not app_secret or app_id.startswith("your_") or app_secret.startswith("your_"):
                console.print("[red]未配置有效的 WECHAT_APP_ID / WECHAT_APP_SECRET[/red]")
                console.print("[yellow]请在 .env 文件中填入真实的公众号开发者凭据后再运行步骤4[/yellow]")
                return []
            wechat_client = WeChatClient(app_id, app_secret)
        elif publisher_mode == "playwright":
            if auto_publish:
                console.print("[yellow]Playwright 模式当前只会自动保存草稿，不会直接群发发布[/yellow]")
            automator = WeChatDraftAutomator(config).start()

        for json_file, article in pending_files:
            title = article.get("title", json_file.stem)
            console.print(f"\n  处理: [bold]{title[:40]}[/bold]")
            if wechat_client:
                try:
                    article = publish_via_appsecret(article, wechat_client, config, date, auto_publish)
                except Exception as exc:
                    article["wechat_draft_created"] = False
                    article["wechat_publish_error"] = str(exc)
                    console.print(f"  [yellow]AppSecret 上传失败，已保留发布包兜底: {exc}[/yellow]")
            elif automator:
                article = ensure_cover_and_package(article, config, date)
                try:
                    article = automator.publish_article(article)
                    console.print("  [green]✓ 已自动保存到公众号草稿箱[/green]")
                except Exception as exc:
                    article["wechat_draft_created"] = False
                    article["wechat_publish_error"] = str(exc)
                    console.print(f"  [yellow]自动草稿失败，已保留发布包兜底: {exc}[/yellow]")
            else:
                article = ensure_cover_and_package(article, config, date)
                console.print("  [green]✓ 发布包已导出，可手动上传[/green]")

            save_json(article, json_file)
            results.append(article)
    finally:
        if automator:
            automator.close()

    drafted = sum(1 for r in results if r.get("wechat_draft_created"))
    exported = sum(1 for r in results if r.get("export_ready"))
    published = sum(1 for r in results if r.get("published"))
    console.print(
        f"\n[green]完成！{drafted} 篇已生成草稿，{published} 篇已提交发布，{exported} 篇已导出发布包[/green]"
    )
    return results


def upload_thumb(image_path: str):
    """上传一张本地图片到公众号永久素材库，打印返回的 media_id"""
    from dotenv import load_dotenv
    load_dotenv()
    app_id = os.getenv("WECHAT_APP_ID", "")
    app_secret = os.getenv("WECHAT_APP_SECRET", "")
    if not app_id or not app_secret or app_id.startswith("your_"):
        console.print("[red]未配置有效的 WECHAT_APP_ID / WECHAT_APP_SECRET[/red]")
        return
    p = Path(image_path)
    if not p.exists():
        console.print(f"[red]文件不存在: {image_path}[/red]")
        return
    client = WeChatClient(app_id, app_secret)
    media_id = client.upload_image(p.read_bytes(), p.name)
    console.print(f"\n[green]上传成功！[/green]")
    console.print(f"media_id: [bold cyan]{media_id}[/bold cyan]")
    console.print(f"\n将以下内容填入 config/config.yaml：")
    console.print(f"  [bold]default_thumb_media_id: \"{media_id}\"[/bold]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="配图生成 & 公众号上传工具")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--article-id", type=str, help="指定文章ID")
    parser.add_argument("--publish", action="store_true", help="创建草稿后继续提交发布")
    parser.add_argument("--upload-thumb", type=str, metavar="IMAGE_PATH",
                        help="上传本地图片到素材库并打印 media_id，用于设置 default_thumb_media_id")
    args = parser.parse_args()
    if args.upload_thumb:
        upload_thumb(args.upload_thumb)
    else:
        run(date=args.date, article_id=args.article_id, auto_publish=args.publish)
