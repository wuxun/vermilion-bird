import subprocess
import os
import logging
import shlex
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

if TYPE_CHECKING:
    from .sandbox import SandboxExecutor

logger = logging.getLogger(__name__)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))

DEFAULT_WHITELIST = [
    "ls",
    "pwd",
    "cat",
    "grep",
    "head",
    "tail",
    "wc",
    "du",
    "df",
    "git",
    "find",
    "echo",
    "date",
    "whoami",
    "uname",
    "env",
    "printenv",
]


class ShellExecTool(BaseTool):
    def __init__(
        self,
        whitelist: List[str] = None,
        allowed_workdir: str = "./",
        max_output_length: int = 10000,
        sandbox: "SandboxExecutor" = None,
    ):
        self._whitelist = whitelist or DEFAULT_WHITELIST
        self._allowed_workdir = os.path.abspath(allowed_workdir)
        self._max_output_length = max_output_length
        self._sandbox = sandbox  # 可选沙箱执行器

    @property
    def name(self) -> str:
        return "shell_exec"

    @property
    def description(self) -> str:
        return "在受控环境中执行shell命令，仅允许执行白名单内的命令。"

    def _truncate_output(self, output: str) -> str:
        """截断过长输出。"""
        if len(output) <= self._max_output_length:
            return output
        truncated = len(output) - self._max_output_length
        return (
            output[:self._max_output_length]
            + f"\n\n[Output truncated - {truncated} characters omitted]"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的shell命令，必须在白名单内",
                },
                "workdir": {
                    "type": "string",
                    "description": "工作目录（可选，默认是项目根目录）",
                    "default": "./",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间（秒，可选，默认5秒）",
                    "default": 5,
                },
            },
            "required": ["command"],
        }

    def execute(self, **kwargs) -> str:
        command = kwargs.get("command")
        workdir = kwargs.get("workdir", "./")
        timeout = kwargs.get("timeout", 30)

        base_command = command.strip().split()[0] if command.strip() else ""

        # ── 沙箱模式: 有真正隔离，跳过白名单 ──
        if self._sandbox and self._sandbox.is_isolated:
            try:
                os.makedirs(self._allowed_workdir, exist_ok=True)
                logger.info(
                    f"ShellExecTool [sandbox:{self._sandbox.mode}]: {command}"
                )
                raw_output = self._sandbox.execute(command, workdir, timeout)
                return self._truncate_output(raw_output)
            except Exception as e:
                logger.error(f"沙箱执行失败: {e}")
                return f"Error: 沙箱执行失败: {e}"

        # ── 白名单模式: 无隔离，严格检查 ──
        if base_command not in self._whitelist:
            allowed = ", ".join(self._whitelist)
            error_msg = f"Command '{base_command}' not in whitelist. Allowed: {allowed}"
            logger.warning(f"ShellExecTool: {error_msg}")
            return f"Error: {error_msg}"

        try:
            full_workdir = os.path.abspath(os.path.join(self._allowed_workdir, workdir))
            if not full_workdir.startswith(self._allowed_workdir):
                error_msg = f"Work directory '{workdir}' is outside the allowed directory '{self._allowed_workdir}'"
                logger.warning(f"ShellExecTool: {error_msg}")
                return f"Error: {error_msg}"
            if not os.path.isdir(full_workdir):
                error_msg = f"Work directory '{workdir}' does not exist"
                logger.warning(f"ShellExecTool: {error_msg}")
                return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"Invalid work directory: {str(e)}"
            logger.warning(f"ShellExecTool: {error_msg}")
            return f"Error: {error_msg}"

        try:
            args = shlex.split(command)
        except ValueError as e:
            error_msg = f"Invalid command syntax: {str(e)}"
            logger.warning(f"ShellExecTool: {error_msg}")
            return f"Error: {error_msg}"

        try:
            logger.info(
                f"ShellExecTool: Executing command '{command}' in '{full_workdir}' with timeout {timeout}s"
            )
            result = subprocess.run(
                args, cwd=full_workdir, timeout=timeout, capture_output=True, text=True
            )

            logger.info(
                f"ShellExecTool: Command '{command}' completed with return code {result.returncode}"
            )

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            output += f"\n\nReturn code: {result.returncode}"

            return self._truncate_output(output)

        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after {timeout} seconds"
            logger.warning(f"ShellExecTool: {error_msg}")
            return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"Command execution failed: {str(e)}"
            logger.error(f"ShellExecTool: {error_msg}", exc_info=True)
            return f"Error: {error_msg}"


class ShellExecSkill(BaseSkill):
    def __init__(self):
        self._whitelist = DEFAULT_WHITELIST
        self._allowed_workdir = PROJECT_ROOT
        self._max_output_length = 10000
        self._tool = None
        self._sandbox: Optional[SandboxExecutor] = None

    @property
    def name(self) -> str:
        return "shell_exec"

    @property
    def description(self) -> str:
        return "Shell命令执行技能，支持在受控环境中执行白名单内的系统命令。"

    @property
    def version(self) -> str:
        return "1.0.0"

    def on_unload(self) -> None:
        """卸载时销毁沙箱，防止 Docker 容器泄漏。"""
        if self._sandbox:
            self._sandbox.stop()
            self._sandbox = None
            logger.info("ShellExec 沙箱已销毁")

    def get_tools(self) -> List[BaseTool]:
        if self._tool is None:
            self._tool = ShellExecTool(
                whitelist=self._whitelist,
                allowed_workdir=self._allowed_workdir,
                max_output_length=self._max_output_length,
                sandbox=self._sandbox,
            )
        return [self._tool]

    def on_load(self, config: Dict[str, Any] = None) -> None:
        if config is None:
            config = {}

        self._whitelist = config.get("whitelist", DEFAULT_WHITELIST)
        self._allowed_workdir = os.path.abspath(
            config.get("allowed_workdir", PROJECT_ROOT)
        )
        self._max_output_length = config.get("max_output_length", 10000)
        self._tool = None

        # 初始化沙箱 (仅在显式配置时启用)
        sandbox_enabled = config.get("sandbox_enabled", False)
        if sandbox_enabled:
            from .sandbox import SandboxExecutor

            if self._sandbox:
                self._sandbox.stop()

            self._sandbox = SandboxExecutor(
                work_dir=self._allowed_workdir,
                timeout=config.get("sandbox_timeout", 60),
                max_memory_mb=config.get("sandbox_max_memory_mb", 256),
            )
            self._sandbox.start()
            logger.info(
                f"ShellExec 沙箱已启动: mode={self._sandbox.mode}, "
                f"isolated={self._sandbox.is_isolated}"
            )

        logger.info(
            f"ShellExecSkill loaded: whitelist={self._whitelist}, "
            f"workdir={self._allowed_workdir}, max_output={self._max_output_length}, "
            f"sandbox={self._sandbox.mode if self._sandbox else 'disabled'}"
        )
