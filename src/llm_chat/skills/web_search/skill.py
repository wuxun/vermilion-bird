import json
import logging
from typing import Dict, Any, List, Optional

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)

try:
    from ddgs import DDGS

    DUCKDUCKGO_AVAILABLE = True
    USING_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS

        DUCKDUCKGO_AVAILABLE = True
        USING_DDGS = False
    except ImportError:
        DUCKDUCKGO_AVAILABLE = False
        USING_DDGS = False
        DDGS = None


class WebSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        if self._fallback:
            return (
                "备用网络搜索工具。仅在首选的 MCP 搜索工具（如 tavily_search）"
                "不可用、出错或返回空结果时才使用此工具。"
            )
        return "搜索互联网获取实时信息。当用户询问时事新闻、最新信息、或需要查询网络内容时使用此工具。"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或问题"},
                "num_results": {
                    "type": "integer",
                    "description": "返回结果数量，默认为10，最大20",
                    "default": 10,
                },
                "region": {
                    "type": "string",
                    "description": "搜索区域，如 cn-zh(中文)、us-en(英文)、默认自动检测",
                    "default": "auto",
                },
            },
            "required": ["query"],
        }

    def __init__(
        self,
        engine: str = "duckduckgo",
        api_key: Optional[str] = None,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
        timeout: int = 30,
        fallback: bool = False,
    ):
        self.engine = engine
        self.api_key = api_key
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self.timeout = timeout
        self._fallback = fallback

    def _get_proxy_string(self) -> Optional[str]:
        if self.https_proxy:
            return self.https_proxy
        if self.http_proxy:
            return self.http_proxy
        return None

    def _get_proxies(self) -> Optional[Dict[str, str]]:
        proxies = {}
        if self.http_proxy:
            proxies["http"] = self.http_proxy
        if self.https_proxy:
            proxies["https"] = self.https_proxy
        return proxies if proxies else None

    def _detect_chinese(self, text: str) -> bool:
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                return True
        return False

    def _get_region(self, query: str, region: str) -> str:
        if region != "auto":
            return region
        if self._detect_chinese(query):
            return "cn-zh"
        return "us-en"

    def execute(self, query: str, num_results: int = 5, region: str = "auto") -> str:
        if self.engine == "duckduckgo":
            return self._search_duckduckgo(query, num_results, region)
        elif self.engine == "brave":
            return self._search_brave(query, num_results)
        else:
            return f"不支持的搜索引擎: {self.engine}"

    def _search_duckduckgo(
        self, query: str, num_results: int, region: str = "auto"
    ) -> str:
        if not DUCKDUCKGO_AVAILABLE:
            logger.error("duckduckgo-search 或 ddgs 未安装")
            return "错误: 搜索库未安装。请运行: pip install ddgs"

        try:
            results = []
            proxy = self._get_proxy_string()
            detected_region = self._get_region(query, region)

            logger.info(
                f"开始 DuckDuckGo 搜索: query={query}, num_results={num_results}, region={detected_region}"
            )
            logger.info(f"代理配置: proxy={proxy}")

            if USING_DDGS:
                ddgs = DDGS(proxy=proxy, timeout=self.timeout)

                backends = ["google", "bing", "yahoo", "brave"]
                for backend in backends:
                    try:
                        logger.info(f"尝试后端: {backend}")
                        search_results = list(
                            ddgs.text(
                                query,
                                region=detected_region,
                                max_results=num_results,
                                backend=backend,
                            )
                        )
                        if search_results:
                            logger.info(
                                f"后端 {backend} 返回 {len(search_results)} 个结果"
                            )
                            break
                    except Exception as e:
                        logger.warning(f"后端 {backend} 失败: {e}")
                        search_results = []
            else:
                proxies = self._get_proxies()
                with DDGS(proxies=proxies, timeout=self.timeout) as ddgs:
                    search_results = list(ddgs.text(query, max_results=num_results))

            logger.info(
                f"搜索返回结果数量: {len(search_results) if search_results else 0}"
            )
            logger.debug(f"搜索结果详情: {search_results}")

            if not search_results:
                logger.warning(f"未找到相关结果: query={query}")
                return "未找到相关结果"

            for i, result in enumerate(search_results, 1):
                title = result.get("title", "")
                url = result.get("href", "")
                snippet = result.get("body", "")[:100] if result.get("body") else ""
                logger.info(f"搜索结果 {i}: title={title}, url={url}")
                logger.debug(f"  snippet: {snippet}...")
                results.append(
                    {"title": title, "url": url, "snippet": result.get("body", "")}
                )

            results = self._deduplicate_and_sort_results(results, query)

            result_json = json.dumps(results, ensure_ascii=False, indent=2)
            logger.info(f"返回结果: {result_json[:200]}...")
            return result_json

        except Exception as e:
            logger.error(f"搜索失败: {str(e)}", exc_info=True)
            return f"搜索失败: {str(e)}"

    def _deduplicate_and_sort_results(
        self, results: List[Dict], query: str
    ) -> List[Dict]:
        seen_urls = set()
        unique_results = []

        for result in results:
            url = result.get("url", "")
            if not url:
                continue

            normalized_url = self._normalize_url(url)
            if normalized_url in seen_urls:
                continue

            seen_urls.add(normalized_url)
            unique_results.append(result)

        unique_results.sort(
            key=lambda r: self._calculate_relevance_score(r, query), reverse=True
        )

        logger.info(f"去重后结果数量: {len(unique_results)}")
        return unique_results

    def _normalize_url(self, url: str) -> str:
        from urllib.parse import urlparse, urlunparse

        try:
            parsed = urlparse(url)
            normalized = urlunparse(
                (
                    parsed.scheme.lower(),
                    parsed.netloc.lower(),
                    parsed.path.rstrip("/") or "/",
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
            return normalized
        except Exception:
            return url.lower()

    def _calculate_relevance_score(self, result: Dict, query: str) -> float:
        score = 0.0

        title = result.get("title", "").lower()
        snippet = result.get("snippet", "").lower()
        url = result.get("url", "").lower()

        query_terms = [term.strip().lower() for term in query.split() if term.strip()]

        for term in query_terms:
            if term in title:
                score += 3.0
            if term in snippet:
                score += 1.5
            if term in url:
                score += 1.0

        content_length = len(snippet)
        if content_length > 100:
            score += min(content_length / 500, 1.0)

        return score

    def _search_brave(self, query: str, num_results: int) -> str:
        import requests

        if not self.api_key:
            return "错误: Brave Search 需要 API Key"

        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            }
            params = {"q": query, "count": num_results}

            proxies = self._get_proxies()
            response = requests.get(
                url,
                headers=headers,
                params=params,
                proxies=proxies,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()

            results = []
            web_results = data.get("web", {}).get("results", [])

            for result in web_results[:num_results]:
                results.append(
                    {
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "snippet": result.get("description", ""),
                    }
                )

            results = self._deduplicate_and_sort_results(results, query)

            return json.dumps(results, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"搜索失败: {str(e)}"


class WebSearchSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "网络搜索能力，支持 DuckDuckGo 和 Brave 搜索引擎"

    @property
    def version(self) -> str:
        return "1.0.0"

    def __init__(self):
        self._engine = "duckduckgo"
        self._api_key = None
        self._http_proxy = None
        self._https_proxy = None
        self._timeout = 30
        self._fallback = False

    def get_tools(self) -> List[BaseTool]:
        return [
            WebSearchTool(
                engine=self._engine,
                api_key=self._api_key,
                http_proxy=self._http_proxy,
                https_proxy=self._https_proxy,
                timeout=self._timeout,
                fallback=self._fallback,
            )
        ]

    def on_load(self, config: Dict[str, Any]) -> None:
        self._engine = config.get("engine", "duckduckgo")
        self._api_key = config.get("api_key")
        self._http_proxy = config.get("http_proxy")
        self._https_proxy = config.get("https_proxy")
        self._timeout = config.get("timeout", 30)
        self._fallback = config.get("prefer_external", False)

        self.logger.info(
            f"WebSearchSkill loaded: engine={self._engine}, "
            f"api_key={'*' * 8 if self._api_key else 'None'}, "
            f"http_proxy={self._http_proxy}, https_proxy={self._https_proxy}, "
            f"timeout={self._timeout}, fallback={self._fallback}"
        )
