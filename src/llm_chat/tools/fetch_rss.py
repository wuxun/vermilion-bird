"""fetch_rss — LLM 可调用的 RSS 抓取工具。

从配置的 RSS 源拉取最新文章，返回标题、摘要和链接。
"""

import logging
from typing import Dict, Any, List, Optional

from .base import BaseTool

logger = logging.getLogger(__name__)


class FetchRSSTool(BaseTool):
    """RSS 抓取工具 — 供 LLM 在定时任务或手动对话中主动调用。"""

    def __init__(self, config=None):
        self._config = config

    @property
    def name(self) -> str:
        return "fetch_rss"

    @property
    def description(self) -> str:
        return (
            "抓取 RSS 订阅源的最新文章，返回每篇文章的标题、摘要和链接。\n"
            "可以直接传入 RSS URL 列表，也可以使用已配置的订阅源。\n"
            "适用于：获取新闻资讯、技术博客更新、学术论文等订阅内容。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "RSS 源 URL 列表。传入则抓取这些源，"
                        "不传则使用 config.yaml 中配置的 scheduler.proactive_rss_feeds"
                    ),
                },
                "max_per_feed": {
                    "type": "integer",
                    "description": "每个 RSS 源最多返回的文章数，默认 8",
                    "default": 8,
                },
            },
        }

    def execute(self, urls: Optional[List[str]] = None, max_per_feed: int = 8, **kwargs) -> str:
        # 优先用传入的 urls，否则从 config 读取
        if urls:
            feeds = urls
        else:
            feeds = self._get_feeds()

        if not feeds:
            return (
                "未提供 RSS 订阅源。请通过 urls 参数传入 URL 列表，"
                "或在 config.yaml scheduler.proactive_rss_feeds 中配置。"
            )

        try:
            import feedparser
        except ImportError:
            return "feedparser 未安装，无法抓取 RSS。"

        import socket
        import requests

        proxy = self._get_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None

        lines = []
        total_articles = 0
        failed_feeds = 0

        for url in feeds:
            try:
                resp = requests.get(
                    url,
                    proxies=proxies,
                    timeout=15,
                    headers={"User-Agent": "vermilion-bird/1.0"},
                )
                resp.raise_for_status()

                d = feedparser.parse(resp.content)
                feed_title = d.feed.get("title", url[:50])

                entries = d.entries[:max_per_feed]
                if not entries:
                    continue

                lines.append(f"\n### {feed_title} ({len(entries)} 篇)")
                for i, entry in enumerate(entries, 1):
                    title = entry.get("title", "(无标题)")
                    summary = (
                        entry.get("summary", "")
                        or entry.get("description", "")
                        or ""
                    )[:150]
                    link = entry.get("link", "")

                    line = f"{i}. {title}"
                    if summary:
                        line += f"\n   {summary}"
                    if link:
                        line += f"\n   {link}"
                    lines.append(line)

                total_articles += len(entries)

            except requests.RequestException as e:
                logger.info(f"RSS 抓取失败 [{url[:60]}]: {e}")
                failed_feeds += 1
                continue
            except Exception as e:
                logger.warning(f"RSS 解析失败 [{url[:60]}]: {e}")
                failed_feeds += 1
                continue

        if not lines:
            return "所有 RSS 源抓取失败，请检查网络连接或源 URL。"

        header = f"📰 RSS 文章 ({len(feeds) - failed_feeds}/{len(feeds)} 个源, 共 {total_articles} 篇)"
        if failed_feeds:
            header += f"，{failed_feeds} 个源失败"

        return header + "\n".join(lines)

    def _get_feeds(self) -> List[str]:
        if self._config is None:
            return []
        scheduler_cfg = getattr(self._config, "scheduler", None)
        if scheduler_cfg is None:
            return []
        return getattr(scheduler_cfg, "proactive_rss_feeds", None) or []

    def _get_proxy(self) -> Optional[str]:
        if self._config is None:
            return None
        llm_cfg = getattr(self._config, "llm", None)
        if llm_cfg is None:
            return None
        return getattr(llm_cfg, "http_proxy", None) or None
