"""Webhook 事件驱动触发器。

轻量 HTTP 服务器，接收外部 webhook 请求并触发关联的定时任务。
使用标准库 http.server，零额外依赖。
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Callable, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 默认 webhook 端口
DEFAULT_WEBHOOK_PORT = 9100


class WebhookHandler(BaseHTTPRequestHandler):
    """Webhook HTTP 请求处理器。

    路径匹配：POST /hooks/{task_id} → 触发对应 webhook 任务。
    支持可选的 secret 校验 (X-Webhook-Secret header)。
    """

    # 由 WebhookServer 注入
    task_registry: Dict[str, dict] = {}  # task_id → {secret, callback}
    server_instance: Optional[WebhookServer] = None

    def do_POST(self):
        path = urlparse(self.path).path

        # 匹配 /hooks/{task_id}
        if not path.startswith("/hooks/"):
            self._respond(404, {"error": "not found"})
            return

        task_id = path[len("/hooks/"):]
        if not task_id or task_id not in self.task_registry:
            self._respond(404, {"error": f"unknown hook: {task_id}"})
            return

        task_info = self.task_registry[task_id]

        # Secret 校验
        expected_secret = task_info.get("secret")
        if expected_secret:
            provided_secret = self.headers.get("X-Webhook-Secret", "")
            if provided_secret != expected_secret:
                logger.warning(f"Webhook secret mismatch for {task_id}")
                self._respond(403, {"error": "invalid secret"})
                return

        # 读取 body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body.decode("utf-8", errors="replace")}

        # 触发任务 (在后台线程中执行)
        callback = task_info.get("callback")
        if callback:
            logger.info(f"Webhook triggered: {task_id}")
            thread = threading.Thread(
                target=callback,
                args=(task_id, payload),
                daemon=True,
                name=f"webhook-{task_id}",
            )
            thread.start()
            self._respond(200, {"status": "accepted", "task_id": task_id})
        else:
            self._respond(500, {"error": "no callback registered"})

    def do_GET(self):
        """健康检查端点。"""
        path = urlparse(self.path).path
        if path == "/health":
            self._respond(200, {
                "status": "ok",
                "hooks": len(self.task_registry),
            })
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """重定向到 logger。"""
        logger.debug(f"Webhook HTTP: {format % args}")


class WebhookServer:
    """Webhook HTTP 服务器 — 接收外部事件触发任务执行。

    使用方式:
        server = WebhookServer(port=9100)
        server.register_task("task-123", callback=my_executor, secret="optional")
        server.start()   # 后台线程
        ...
        server.stop()
    """

    def __init__(self, port: int = DEFAULT_WEBHOOK_PORT, host: str = "127.0.0.1"):
        self._port = port
        self._host = host
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._tasks: Dict[str, dict] = {}

        # 注入到 handler 类变量 (http.server 每个请求创建新 handler 实例)
        WebhookHandler.task_registry = self._tasks
        WebhookHandler.server_instance = self

    def register_task(
        self,
        task_id: str,
        callback: Callable[[str, dict], None],
        secret: Optional[str] = None,
    ):
        """注册一个 webhook 任务。

        Args:
            task_id: 任务 ID (webhook URL: /hooks/{task_id})
            callback: 触发时调用的函数 (task_id, payload) -> None
            secret: 可选的校验密钥 (X-Webhook-Secret header)
        """
        self._tasks[task_id] = {
            "callback": callback,
            "secret": secret,
        }
        logger.info(
            f"Webhook 任务已注册: {task_id} "
            f"(URL: http://{self._host}:{self._port}/hooks/{task_id})"
        )

    def unregister_task(self, task_id: str):
        """注销 webhook 任务。"""
        self._tasks.pop(task_id, None)
        logger.info(f"Webhook 任务已注销: {task_id}")

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self):
        """启动 HTTP 服务器（后台 daemon 线程）。"""
        if self._httpd:
            logger.warning("Webhook server is already running")
            return

        try:
            self._httpd = HTTPServer((self._host, self._port), WebhookHandler)
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="webhook-server",
                daemon=True,
            )
            self._thread.start()
            logger.info(f"Webhook server started on {self.url}")
        except OSError as e:
            logger.error(f"Failed to start webhook server: {e}")
            self._httpd = None

    def stop(self):
        """停止 HTTP 服务器。"""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            logger.info("Webhook server stopped")
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def get_status(self) -> dict:
        return {
            "running": self.is_running,
            "host": self._host,
            "port": self._port,
            "hooks": list(self._tasks.keys()),
            "hook_count": len(self._tasks),
        }
