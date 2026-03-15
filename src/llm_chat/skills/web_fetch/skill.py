import logging
import random
import re
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

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

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None
    PlaywrightTimeoutError = None


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


class WebFetchTool(BaseTool):
    @property
    def name(self) -> str:
        return "fetch_url"
    
    @property
    def description(self) -> str:
        return "抓取网页完整内容。当需要深入了解某个网页的详细信息时使用此工具。通常在 web_search 之后使用，用于获取搜索结果中某个网页的完整内容。支持多层降级策略：Jina Reader API → Playwright → 增强请求 → 基础请求。"
    
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
        user_agent: Optional[str] = None,
        use_jina_reader: bool = True,
        jina_reader_url: str = "https://r.jina.ai/",
        use_playwright: bool = True,
        playwright_timeout: int = 60000
    ):
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self.timeout = timeout
        self.user_agent = user_agent
        self.use_jina_reader = use_jina_reader
        self.jina_reader_url = jina_reader_url
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
        self.playwright_timeout = playwright_timeout
    
    def _get_proxies(self) -> Optional[Dict[str, str]]:
        proxies = {}
        if self.http_proxy:
            proxies["http"] = self.http_proxy
        if self.https_proxy:
            proxies["https"] = self.https_proxy
        return proxies if proxies else None
    
    def _get_random_user_agent(self) -> str:
        if self.user_agent:
            return self.user_agent
        return random.choice(USER_AGENTS)
    
    def _get_enhanced_headers(self, url: str) -> Dict[str, str]:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        
        return {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "Referer": f"{parsed_url.scheme}://{domain}/",
        }
    
    def execute(self, url: str, max_length: int = 5000) -> str:
        logger.info(f"开始抓取网页: url={url}, max_length={max_length}")
        
        if self.use_jina_reader:
            result = self._fetch_with_jina_reader(url, max_length)
            if not result.startswith("错误:"):
                return result
            logger.warning(f"Jina Reader 失败，降级: {result[:100]}")
        
        if self.use_playwright:
            result = self._fetch_with_playwright(url, max_length)
            if not result.startswith("错误:"):
                return result
            logger.warning(f"Playwright 失败，降级: {result[:100]}")
        
        result = self._fetch_with_enhanced_requests(url, max_length)
        if not result.startswith("错误:"):
            return result
        logger.warning(f"增强请求失败，降级到基础请求: {result[:100]}")
        
        return self._fetch_with_basic_requests(url, max_length)
    
    def _fetch_with_jina_reader(self, url: str, max_length: int) -> str:
        try:
            jina_url = f"{self.jina_reader_url}{url}"
            
            headers = {
                "User-Agent": self._get_random_user_agent(),
                "Accept": "text/markdown",
            }
            
            proxies = self._get_proxies()
            
            logger.info(f"尝试 Jina Reader API: {jina_url}")
            
            response = requests.get(
                jina_url,
                headers=headers,
                proxies=proxies,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            content = response.text
            
            if not content or len(content) < 100:
                return "错误: Jina Reader 返回空内容"
            
            if len(content) > max_length:
                content = content[:max_length] + "\n\n... [内容已截断]"
            
            logger.info(f"Jina Reader 成功，内容长度: {len(content)}")
            
            return f"来源: {url}\n\n{content}"
            
        except requests.Timeout:
            return "错误: Jina Reader 超时"
        except requests.RequestException as e:
            return f"错误: Jina Reader 请求失败: {str(e)}"
        except Exception as e:
            return f"错误: Jina Reader 处理失败: {str(e)}"
    
    def _fetch_with_playwright(self, url: str, max_length: int) -> str:
        if not PLAYWRIGHT_AVAILABLE:
            return "错误: Playwright 未安装"
        
        try:
            logger.info(f"尝试 Playwright: {url}")
            
            with sync_playwright() as p:
                browser_args = {}
                if self.http_proxy or self.https_proxy:
                    proxy_server = self.https_proxy or self.http_proxy
                    browser_args["proxy"] = {"server": proxy_server}
                
                browser = p.chromium.launch(headless=True, args=browser_args if browser_args else None)
                
                context_args = {
                    "user_agent": self._get_random_user_agent(),
                    "viewport": {"width": 1920, "height": 1080},
                }
                
                context = browser.new_context(**context_args)
                page = context.new_page()
                
                try:
                    page.goto(url, timeout=self.playwright_timeout, wait_until="networkidle")
                    
                    page.wait_for_load_state("domcontentloaded", timeout=self.playwright_timeout // 2)
                    
                    title = page.title()
                    
                    content_selectors = [
                        "article",
                        "main",
                        "[class*='content']",
                        "[class*='article']",
                        "[class*='post']",
                        "#content",
                        "#article",
                        "body"
                    ]
                    
                    content = None
                    for selector in content_selectors:
                        try:
                            element = page.query_selector(selector)
                            if element:
                                content = element.inner_text()
                                if content and len(content) > 200:
                                    break
                        except Exception:
                            continue
                    
                    if not content:
                        content = page.content()
                        content = self._extract_content(content, url)
                    
                    browser.close()
                    
                    if not content or len(content) < 100:
                        return "错误: Playwright 返回空内容"
                    
                    if len(content) > max_length:
                        content = content[:max_length] + "\n\n... [内容已截断]"
                    
                    logger.info(f"Playwright 成功，内容长度: {len(content)}")
                    
                    return f"标题: {title}\n来源: {url}\n\n{content}"
                    
                except PlaywrightTimeoutError:
                    browser.close()
                    return "错误: Playwright 页面加载超时"
                except Exception as e:
                    browser.close()
                    raise e
                    
        except Exception as e:
            return f"错误: Playwright 处理失败: {str(e)}"
    
    def _fetch_with_enhanced_requests(self, url: str, max_length: int) -> str:
        try:
            headers = self._get_enhanced_headers(url)
            proxies = self._get_proxies()
            
            logger.info(f"尝试增强请求: {url}")
            
            response = requests.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()
            
            logger.info(f"增强请求成功，状态码: {response.status_code}, 内容长度: {len(response.text)}")
            
            content = self._extract_content(response.text, url)
            
            if len(content) > max_length:
                content = content[:max_length] + "\n\n... [内容已截断]"
            
            logger.info(f"提取内容长度: {len(content)}")
            
            return content
            
        except requests.Timeout:
            return "错误: 增强请求超时"
        except requests.RequestException as e:
            return f"错误: 增强请求失败: {str(e)}"
        except Exception as e:
            return f"错误: 增强请求处理失败: {str(e)}"
    
    def _fetch_with_basic_requests(self, url: str, max_length: int) -> str:
        try:
            headers = {
                "User-Agent": self._get_random_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
            
            proxies = self._get_proxies()
            
            logger.info(f"尝试基础请求: {url}")
            
            response = requests.get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()
            
            logger.info(f"基础请求成功，状态码: {response.status_code}")
            
            content = self._extract_content(response.text, url)
            
            if len(content) > max_length:
                content = content[:max_length] + "\n\n... [内容已截断]"
            
            return content
            
        except requests.Timeout:
            return f"错误: 抓取超时: {url}"
        except requests.RequestException as e:
            return f"错误: 抓取失败: {str(e)}"
        except Exception as e:
            return f"错误: 处理失败: {str(e)}"
    
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
        return "网页内容抓取能力，支持多层降级策略获取网页完整内容"
    
    @property
    def version(self) -> str:
        return "1.2.0"
    
    def __init__(self):
        self._http_proxy = None
        self._https_proxy = None
        self._timeout = 30
        self._user_agent = None
        self._use_jina_reader = True
        self._jina_reader_url = "https://r.jina.ai/"
        self._use_playwright = True
        self._playwright_timeout = 60000
    
    def get_tools(self) -> List[BaseTool]:
        return [
            WebFetchTool(
                http_proxy=self._http_proxy,
                https_proxy=self._https_proxy,
                timeout=self._timeout,
                user_agent=self._user_agent,
                use_jina_reader=self._use_jina_reader,
                jina_reader_url=self._jina_reader_url,
                use_playwright=self._use_playwright,
                playwright_timeout=self._playwright_timeout
            )
        ]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        self._http_proxy = config.get("http_proxy")
        self._https_proxy = config.get("https_proxy")
        self._timeout = config.get("timeout", 30)
        self._user_agent = config.get("user_agent")
        self._use_jina_reader = config.get("use_jina_reader", True)
        self._jina_reader_url = config.get("jina_reader_url", "https://r.jina.ai/")
        self._use_playwright = config.get("use_playwright", True)
        self._playwright_timeout = config.get("playwright_timeout", 60000)
        
        self.logger.info(
            f"WebFetchSkill loaded: "
            f"http_proxy={self._http_proxy}, https_proxy={self._https_proxy}, "
            f"timeout={self._timeout}, use_jina_reader={self._use_jina_reader}, "
            f"use_playwright={self._use_playwright}, playwright_timeout={self._playwright_timeout}"
        )
