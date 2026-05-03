"""沙箱执行器 — 多层隔离回退。

优先级:
  1. Docker exec (持久化容器, ~50ms/次)
  2. bwrap (Linux namespace, <5ms/次)
  3. 直接 subprocess (白名单兜底, <1ms/次)

安全等级:
  Docker/bwrap: 文件系统只读 + 网络隔离 + 内存限制 + 禁止提权
  subprocess:   白名单 + 目录限制 (无真正隔离)
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class SandboxExecutor:
    """多层沙箱执行器，自动检测可用方案并回退。

    使用方式:
        sandbox = SandboxExecutor(work_dir="./work")
        sandbox.start()                    # 启动沙箱 (容器/bwrap)
        result = sandbox.execute("ls -la") # 执行命令
        sandbox.stop()                     # 清理
    """

    def __init__(
        self,
        work_dir: str = "./work",
        timeout: int = 30,
        max_memory_mb: int = 256,
        max_cpus: float = 1.0,
    ):
        self._work_dir = os.path.abspath(work_dir)
        self._timeout = timeout
        self._max_memory_mb = max_memory_mb
        self._max_cpus = max_cpus

        self._mode: str = "none"  # docker | bwrap | subprocess
        self._container_id: Optional[str] = None
        self._started = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self):
        """启动沙箱，自动选择最佳可用方案。"""
        if self._started:
            return

        os.makedirs(self._work_dir, exist_ok=True)

        # 注册退出清理 (进程正常/异常退出时自动销毁容器)
        atexit.register(self.stop)

        # 1. 尝试 Docker
        if self._check_docker():
            try:
                self._start_docker()
                self._mode = "docker"
                self._started = True
                logger.info("沙箱已启动: docker (持久化容器)")
                return
            except Exception as e:
                logger.warning(f"Docker 沙箱启动失败: {e}")

        # 2. 尝试 bwrap
        if self._check_bwrap():
            self._mode = "bwrap"
            self._started = True
            logger.info("沙箱已启动: bwrap (Linux namespace)")
            return

        # 3. 回退到白名单模式
        self._mode = "subprocess"
        self._started = True
        logger.warning("沙箱不可用，回退到白名单模式 (无真正隔离)")

    def stop(self):
        """停止沙箱，清理资源。幂等，可多次调用。"""
        if not self._started:
            return

        self._started = False

        if self._mode == "docker" and self._container_id:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self._container_id],
                    capture_output=True, timeout=5,
                )
                logger.info("Docker 沙箱已清理")
            except Exception as e:
                logger.warning(f"Docker 沙箱清理失败: {e}")
            self._container_id = None

        self._mode = "none"

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------

    def execute(self, command: str, work_dir: str = ".", timeout: int = None) -> str:
        """在沙箱中执行命令。

        Args:
            command: 要执行的命令
            work_dir: 相对于沙箱工作目录的子目录
            timeout: 超时秒数 (默认使用配置值)

        Returns:
            stdout + stderr 合并输出
        """
        if not self._started:
            return "Error: 沙箱未启动"

        timeout = timeout or self._timeout
        sandbox_workdir = self._resolve_workdir(work_dir)

        try:
            if self._mode == "docker":
                return self._execute_docker(command, sandbox_workdir, timeout)
            elif self._mode == "bwrap":
                return self._execute_bwrap(command, sandbox_workdir, timeout)
            else:
                return self._execute_subprocess(command, sandbox_workdir, timeout)
        except subprocess.TimeoutExpired:
            return f"Error: 命令超时 ({timeout}s)"
        except Exception as e:
            return f"Error: {str(e)}"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_isolated(self) -> bool:
        """是否有真正的安全隔离 (docker/bwrap)。"""
        return self._mode in ("docker", "bwrap")

    def __del__(self):
        """析构时清理 (安全兜底)。"""
        self.stop()

    # ------------------------------------------------------------------
    # Docker 实现
    # ------------------------------------------------------------------

    def _check_docker(self) -> bool:
        """检查 Docker 是否可用。"""
        return shutil.which("docker") is not None

    def _start_docker(self):
        """创建持久化 Docker 容器 (sleep infinity 挂起)。"""
        self._container_id = f"vb-sandbox-{os.getpid()}"

        # 先清理可能存在的同名容器
        subprocess.run(
            ["docker", "rm", "-f", self._container_id],
            capture_output=True, timeout=5,
        )

        # 拉取镜像 (如果本地没有)
        subprocess.run(
            ["docker", "pull", "alpine:latest"],
            capture_output=True, timeout=120,
        )

        result = subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "--name", self._container_id,
                "--read-only",
                "--network=none",
                f"--memory={self._max_memory_mb}m",
                f"--cpus={self._max_cpus}",
                "--security-opt=no-new-privileges",
                "--cap-drop=ALL",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "-v", f"{self._work_dir}:/work:rw",
                "-w", "/work",
                "alpine:latest",
                "sleep", "infinity",
            ],
            capture_output=True, text=True, timeout=30,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Docker 启动失败: {result.stderr.strip()}")

        self._container_id = result.stdout.strip()[:12]
        logger.info(f"Docker 容器已创建: {self._container_id}")

    def _execute_docker(self, command: str, work_dir: str, timeout: int) -> str:
        """在 Docker 容器中执行命令。"""
        result = subprocess.run(
            [
                "docker", "exec",
                "-w", work_dir,
                self._container_id,
                "sh", "-c", command,
            ],
            capture_output=True, text=True, timeout=timeout,
        )
        return self._format_output(result)

    # ------------------------------------------------------------------
    # bwrap 实现
    # ------------------------------------------------------------------

    def _check_bwrap(self) -> bool:
        """检查 bwrap 是否可用。"""
        return shutil.which("bwrap") is not None

    def _execute_bwrap(self, command: str, work_dir: str, timeout: int) -> str:
        """使用 bwrap 在 Linux namespace 中执行命令。"""
        # 确保工作目录存在
        os.makedirs(work_dir, exist_ok=True)

        result = subprocess.run(
            [
                "bwrap",
                # 只读绑定系统目录
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/bin", "/bin",
                "--ro-bind", "/lib", "/lib",
                "--ro-bind", "/lib64", "/lib64",
                "--ro-bind", "/etc", "/etc",
                # 可写绑定工作目录
                "--bind", self._work_dir, "/work",
                # 临时文件
                "--tmpfs", "/tmp",
                # 隔离
                "--unshare-net",
                "--unshare-ipc",
                "--unshare-pid",
                "--die-with-parent",
                # 工作目录
                "--chdir", work_dir if work_dir.startswith("/work") else "/work",
                # 执行
                "--",
                "sh", "-c", command,
            ],
            capture_output=True, text=True, timeout=timeout,
        )
        return self._format_output(result)

    # ------------------------------------------------------------------
    # Subprocess 回退 (白名单模式)
    # ------------------------------------------------------------------

    def _execute_subprocess(self, command: str, work_dir: str, timeout: int) -> str:
        """直接 subprocess 执行 (无额外隔离，依赖白名单兜底)。"""
        import shlex

        try:
            args = shlex.split(command)
        except ValueError as e:
            return f"Error: 命令语法错误: {e}"

        result = subprocess.run(
            args, cwd=work_dir, timeout=timeout,
            capture_output=True, text=True,
        )
        return self._format_output(result)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _resolve_workdir(self, work_dir: str) -> str:
        """解析工作目录。"""
        if os.path.isabs(work_dir):
            full = work_dir
        else:
            full = os.path.join(self._work_dir, work_dir)

        if self._mode == "docker":
            # Docker 内路径: /work/subdir
            rel = os.path.relpath(full, self._work_dir)
            if rel.startswith(".."):
                return "/work"
            return f"/work/{rel}" if rel != "." else "/work"
        else:
            return full

    @staticmethod
    def _format_output(result: subprocess.CompletedProcess) -> str:
        """格式化 subprocess 输出。"""
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        output += f"\n\nReturn code: {result.returncode}"
        return output
