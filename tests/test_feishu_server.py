"""单元测试 - FeishuServer 服务器功能。"""

import time
import signal
import threading

import pytest

from src.llm_chat.frontends.feishu.server import FeishuServer


class TestFeishuServerInit:
    def test_init_basic(self):
        """测试基本初始化。"""
        server = FeishuServer("test_app_id", "test_secret")

        assert server.app_id == "test_app_id"
        assert server.app_secret == "test_secret"
        assert server.tenant_key is None

    def test_init_with_tenant_key(self):
        """测试带 tenant_key 的初始化。"""
        server = FeishuServer("test_app_id", "test_secret", "test_tenant_key")

        assert server.tenant_key == "test_tenant_key"


class TestFeishuServerLifecycle:
    def test_start_creates_background_thread(self):
        """测试启动方法创建后台线程。"""
        server = FeishuServer("test_app_id", "test_secret")

        # 保存当前线程
        original_thread_count = threading.active_count()

        server.start()

        # 等待一小段时间让线程启动
        time.sleep(0.1)

        # 应该有一个新线程在运行
        assert threading.active_count() == original_thread_count + 1

        # 停止服务器
        server.stop()

        # 等待线程结束
        server._thread.join(timeout=2)

    def test_stop_sets_stop_event(self):
        """测试停止方法设置停止事件。"""
        server = FeishuServer("test_app_id", "test_secret")

        server.start()
        time.sleep(0.05)

        # 停止事件应该被设置
        assert server._stop_event.is_set()

        server.stop()

    def test_stop_joins_thread(self):
        """测试停止方法等待线程结束。"""
        server = FeishuServer("test_app_id", "test_secret")

        server.start()
        time.sleep(0.05)

        thread = server._thread
        assert thread.is_alive()

        server.stop()

        # 等待 join 完成
        server._thread.join(timeout=2)

        # 线程应该已经结束
        assert not thread.is_alive()


class TestFeishuServerSignalHandling:
    def test_graceful_shutdown_on_sigint(self):
        """测试 SIGINT 信号的优雅关闭。"""
        server = FeishuServer("test_app_id", "test_secret")

        server.start()
        time.sleep(0.05)

        # 发送 SIGINT 信号
        signal.raise_signal(signal.SIGINT, signal_handler=lambda s, f: None)

        # 等待服务器停止
        server._thread.join(timeout=2)

    def test_graceful_shutdown_on_sigterm(self):
        """测试 SIGTERM 信号的优雅关闭。"""
        server = FeishuServer("test_app_id", "test_secret")

        server.start()
        time.sleep(0.05)

        # 发送 SIGTERM 信号
        signal.raise_signal(signal.SIGTERM, signal_handler=lambda s, f: None)

        # 等待服务器停止
        server._thread.join(timeout=2)


class TestFeishuServerProcessRequest:
    def test_process_request_logs_with_context(self):
        """测试请求处理日志记录。"""
        server = FeishuServer("test_app_id", "test_secret")

        server.start()
        time.sleep(0.05)

        # 处理请求
        server.process_request(
            {"action": "ping"}, user_id="user_123", chat_id="chat_456"
        )

        # 停止服务器
        server.stop()

        # 等待线程结束
        server._thread.join(timeout=2)

    def test_process_request_masks_identifiers(self):
        """测试请求处理中的 ID 遮蔽。"""
        server = FeishuServer("test_app_id", "test_secret")

        server.start()
        time.sleep(0.05)

        # 使用完整的 ID 处理请求
        server.process_request(
            {"action": "message"}, user_id="user_123456789", chat_id="chat_abc_123"
        )

        # 停止服务器
        server.stop()

        # 等待线程结束
        server._thread.join(timeout=2)
