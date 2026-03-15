import json
from typing import Dict, Any, List, Optional
from .base import BaseTool

try:
    from duckduckgo_search import DDGS
    DUCKDUCKGO_AVAILABLE = True
except ImportError:
    DUCKDUCKGO_AVAILABLE = False
    DDGS = None


class WebSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "web_search"
    
    @property
    def description(self) -> str:
        return "搜索互联网获取实时信息。当用户询问时事新闻、最新信息、或需要查询网络内容时使用此工具。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题"
                },
                "num_results": {
                    "type": "integer",
                    "description": "返回结果数量，默认为5",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    
    def __init__(
        self, 
        engine: str = "duckduckgo", 
        api_key: Optional[str] = None,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None
    ):
        self.engine = engine
        self.api_key = api_key
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
    
    def _get_proxies(self) -> Optional[Dict[str, str]]:
        proxies = {}
        if self.http_proxy:
            proxies["http"] = self.http_proxy
        if self.https_proxy:
            proxies["https"] = self.https_proxy
        return proxies if proxies else None
    
    def execute(self, query: str, num_results: int = 5) -> str:
        if self.engine == "duckduckgo":
            return self._search_duckduckgo(query, num_results)
        elif self.engine == "brave":
            return self._search_brave(query, num_results)
        else:
            return f"不支持的搜索引擎: {self.engine}"
    
    def _search_duckduckgo(self, query: str, num_results: int) -> str:
        if not DUCKDUCKGO_AVAILABLE:
            return "错误: duckduckgo-search 未安装。请运行: pip install duckduckgo-search"
        
        try:
            results = []
            proxies = self._get_proxies()
            
            with DDGS(proxies=proxies) as ddgs:
                search_results = list(ddgs.text(query, max_results=num_results))
            
            if not search_results:
                return "未找到相关结果"
            
            for i, result in enumerate(search_results, 1):
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "snippet": result.get("body", "")
                })
            
            return json.dumps(results, ensure_ascii=False, indent=2)
            
        except Exception as e:
            return f"搜索失败: {str(e)}"
    
    def _search_brave(self, query: str, num_results: int) -> str:
        import requests
        
        if not self.api_key:
            return "错误: Brave Search 需要 API Key"
        
        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key
            }
            params = {
                "q": query,
                "count": num_results
            }
            
            proxies = self._get_proxies()
            response = requests.get(url, headers=headers, params=params, proxies=proxies)
            response.raise_for_status()
            data = response.json()
            
            results = []
            web_results = data.get("web", {}).get("results", [])
            
            for result in web_results[:num_results]:
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("description", "")
                })
            
            return json.dumps(results, ensure_ascii=False, indent=2)
            
        except Exception as e:
            return f"搜索失败: {str(e)}"


class CalculatorTool(BaseTool):
    @property
    def name(self) -> str:
        return "calculator"
    
    @property
    def description(self) -> str:
        return "执行数学计算。支持基本算术运算、幂运算、开方等。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如 '2 + 3 * 4' 或 'sqrt(16)'"
                }
            },
            "required": ["expression"]
        }
    
    def execute(self, expression: str) -> str:
        import math
        
        allowed_names = {
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "pow": pow,
            "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
            "tan": math.tan, "log": math.log, "log10": math.log10,
            "exp": math.exp, "pi": math.pi, "e": math.e
        }
        
        try:
            for char in expression:
                if char.isalpha() or char == '_':
                    continue
                if char.isdigit() or char in '+-*/().% ':
                    continue
                if char not in allowed_names:
                    return f"错误: 表达式包含不允许的字符: {char}"
            
            result = eval(expression, {"__builtins__": {}}, allowed_names)
            return str(result)
            
        except Exception as e:
            return f"计算错误: {str(e)}"
