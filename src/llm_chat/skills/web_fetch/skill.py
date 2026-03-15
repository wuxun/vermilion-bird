import logging
import re
from typing import Dict, Any, List, Optional

import requests

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    BeautifulSoup = None


class WebFetchTool(BaseTool):
    @property
    def name(self) -> str:
        return "fetch_url"
    
    @property
    def description(self) -> str:
        return "抓取网页完整内容。当需要深入了解某个网页的详细信息时使用此工具。通常在 web_search 之后使用，用于获取搜索结果中某个网页的完整内容。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的网页URL"
                },
                "max_length": {
                    "type": "integer",
                    "description": "返回内容的最大字符数，默认5000",
                    "default": 5000
                }
            },
            "required": ["url"]
        }
    
    def __init__(
        self,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
        timeout: int = 30,
        user_agent: Optional[str] = None
    ):
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self.timeout = timeout
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    def _get_proxies(self) -> Optional[Dict[str, str]]:
        proxies = {}
        if self.http_proxy:
            proxies["http"] = self.http_proxy
        if self.https_proxy:
            proxies["https"] = self.https_proxy
        return proxies if proxies else None
    
    def execute(self, url: str, max_length: int = 5000) -> str:
        logger.info(f"开始抓取网页: url={url}, max_length={max_length}")
        
        try:
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }
            
            proxies = self._get_proxies()
            
            response = requests.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()
            
            logger.info(f"响应状态码: {response.status_code}, 内容长度: {len(response.text)}")
            
            content = self._extract_content(response.text, url)
            
            if len(content) > max_length:
                content = content[:max_length] + "\n\n... [内容已截断]"
            
            logger.info(f"提取内容长度: {len(content)}")
            
            return content
            
        except requests.Timeout:
            error_msg = f"抓取超时: {url}"
            logger.error(error_msg)
            return f"错误: {error_msg}"
        except requests.RequestException as e:
            error_msg = f"抓取失败: {str(e)}"
            logger.error(error_msg)
            return f"错误: {error_msg}"
        except Exception as e:
            error_msg = f"处理失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return f"错误: {error_msg}"
    
    def _extract_content(self, html: str, url: str) -> str:
        if BS4_AVAILABLE:
            return self._extract_with_bs4(html, url)
        else:
            return self._extract_simple(html, url)
    
    def _extract_with_bs4(self, html: str, url: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
            tag.decompose()
        
        title = soup.find("title")
        title_text = title.get_text(strip=True) if title else "无标题"
        
        main_content = (
            soup.find("main") or
            soup.find("article") or
            soup.find("div", class_=re.compile(r"content|article|post|entry|main", re.I)) or
            soup.find("div", id=re.compile(r"content|article|post|entry|main", re.I)) or
            soup.find("body")
        )
        
        if main_content:
            text = main_content.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)
        
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text = "\n".join(lines)
        
        result = f"标题: {title_text}\n来源: {url}\n\n{text}"
        
        return result
    
    def _extract_simple(self, html: str, url: str) -> str:
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<aside[^>]*>.*?</aside>", "", text, flags=re.DOTALL | re.IGNORECASE)
        
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else "无标题"
        
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        
        result = f"标题: {title}\n来源: {url}\n\n{text}"
        
        return result


class WebFetchSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "web_fetch"
    
    @property
    def description(self) -> str:
        return "网页内容抓取能力，支持获取网页完整内容"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    def __init__(self):
        self._http_proxy = None
        self._https_proxy = None
        self._timeout = 30
        self._user_agent = None
    
    def get_tools(self) -> List[BaseTool]:
        return [
            WebFetchTool(
                http_proxy=self._http_proxy,
                https_proxy=self._https_proxy,
                timeout=self._timeout,
                user_agent=self._user_agent
            )
        ]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        self._http_proxy = config.get("http_proxy")
        self._https_proxy = config.get("https_proxy")
        self._timeout = config.get("timeout", 30)
        self._user_agent = config.get("user_agent")
        
        self.logger.info(
            f"WebFetchSkill loaded: "
            f"http_proxy={self._http_proxy}, https_proxy={self._https_proxy}, "
            f"timeout={self._timeout}"
        )
