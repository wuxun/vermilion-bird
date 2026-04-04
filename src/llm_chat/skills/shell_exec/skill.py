import subprocess
import os
import logging
import shlex
from typing import Dict, Any, List
from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

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
    "wc",
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
    ):
        self._whitelist = whitelist or DEFAULT_WHITELIST
        self._allowed_workdir = os.path.abspath(allowed_workdir)
        self._max_output_length = max_output_length

    @property
    def name(self) -> str:
        return "shell_exec"

    @property
    def description(self) -> str:
        return "在受控环境中执行shell命令，仅允许执行白名单内的命令。"

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
        timeout = kwargs.get("timeout", 5)

        base_command = command.strip().split()[0] if command.strip() else ""
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
            if result.stdout:
                logger.debug(f"ShellExecTool stdout: {result.stdout[:200]}...")
            if result.stderr:
                logger.debug(f"ShellExecTool stderr: {result.stderr[:200]}...")

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            if len(output) > self._max_output_length:
                truncated_length = len(output) - self._max_output_length
                output = (
                    output[: self._max_output_length]
                    + f"\n\n[Output truncated - {truncated_length} characters omitted]"
                )

            output += f"\n\nReturn code: {result.returncode}"

            return output

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

    @property
    def name(self) -> str:
        return "shell_exec"

    @property
    def description(self) -> str:
        return "Shell命令执行技能，支持在受控环境中执行白名单内的系统命令。"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_tools(self) -> List[BaseTool]:
        if self._tool is None:
            self._tool = ShellExecTool(
                whitelist=self._whitelist,
                allowed_workdir=self._allowed_workdir,
                max_output_length=self._max_output_length,
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

        logger.info(
            f"ShellExecSkill loaded: whitelist={self._whitelist}, "
            f"workdir={self._allowed_workdir}, max_output={self._max_output_length}"
        )
