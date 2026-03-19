import os
import logging
from pathlib import Path
from typing import Dict, Any, List

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)


class FileReaderTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
    
    @property
    def name(self) -> str:
        return "read_file"
    
    @property
    def description(self) -> str:
        return "读取当前工程目录下的文件内容。只能读取工程文件夹内的文件，不能读取外部文件。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "相对于工程根目录的文件路径，如 'src/main.py' 或 'README.md'"
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（可选，从1开始）",
                    "default": 1
                },
                "end_line": {
                    "type": "integer",
                    "description": "结束行号（可选，默认读取全部）",
                    "default": -1
                }
            },
            "required": ["file_path"]
        }
    
    def execute(self, file_path: str, start_line: int = 1, end_line: int = -1) -> str:
        try:
            target_path = (self._base_dir / file_path).resolve()
            
            if not str(target_path).startswith(str(self._base_dir)):
                return f"错误: 不允许读取工程目录外的文件。请求路径: {file_path}"
            
            if not target_path.exists():
                return f"错误: 文件不存在: {file_path}"
            
            if not target_path.is_file():
                return f"错误: 路径不是文件: {file_path}"
            
            max_file_size = 1024 * 1024
            if target_path.stat().st_size > max_file_size:
                return f"错误: 文件过大（超过1MB），请使用 start_line 和 end_line 参数分段读取"
            
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            
            total_lines = len(lines)
            
            if start_line < 1:
                start_line = 1
            if end_line < 0 or end_line > total_lines:
                end_line = total_lines
            
            start_idx = start_line - 1
            end_idx = end_line
            
            selected_lines = lines[start_idx:end_idx]
            
            result_lines = []
            for i, line in enumerate(selected_lines, start=start_line):
                result_lines.append(f"{i:4d}→{line.rstrip()}")
            
            result = f"文件: {file_path}\n"
            result += f"总行数: {total_lines}\n"
            result += f"显示: 第 {start_line} 行到第 {min(end_line, total_lines)} 行\n"
            result += "-" * 50 + "\n"
            result += "\n".join(result_lines)
            
            return result
            
        except PermissionError:
            return f"错误: 没有权限读取文件: {file_path}"
        except Exception as e:
            return f"读取文件错误: {str(e)}"


class ListFilesTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
    
    @property
    def name(self) -> str:
        return "list_files"
    
    @property
    def description(self) -> str:
        return "列出当前工程目录下的文件和文件夹。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "相对于工程根目录的文件夹路径，默认为根目录",
                    "default": "."
                },
                "recursive": {
                    "type": "boolean",
                    "description": "是否递归列出子目录",
                    "default": False
                }
            },
            "required": []
        }
    
    def execute(self, directory: str = ".", recursive: bool = False) -> str:
        try:
            target_path = (self._base_dir / directory).resolve()
            
            if not str(target_path).startswith(str(self._base_dir)):
                return f"错误: 不允许访问工程目录外的文件夹"
            
            if not target_path.exists():
                return f"错误: 目录不存在: {directory}"
            
            if not target_path.is_dir():
                return f"错误: 路径不是目录: {directory}"
            
            ignore_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
            ignore_files = {".DS_Store", "Thumbs.db"}
            
            result_lines = [f"目录: {directory or '.'}\n"]
            result_lines.append("-" * 50)
            
            if recursive:
                for root, dirs, files in os.walk(target_path):
                    dirs[:] = [d for d in dirs if d not in ignore_dirs]
                    
                    rel_root = Path(root).relative_to(self._base_dir)
                    level = len(rel_root.parts) - 1 if str(rel_root) != "." else 0
                    indent = "  " * level
                    
                    dir_name = rel_root.name if str(rel_root) != "." else "."
                    result_lines.append(f"{indent}📁 {dir_name}/")
                    
                    for file in sorted(files):
                        if file in ignore_files:
                            continue
                        file_path = Path(root) / file
                        size = file_path.stat().st_size
                        size_str = self._format_size(size)
                        result_lines.append(f"{indent}  📄 {file} ({size_str})")
            else:
                items = sorted(target_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                
                for item in items:
                    if item.name in ignore_dirs or item.name in ignore_files:
                        continue
                    
                    if item.is_dir():
                        result_lines.append(f"📁 {item.name}/")
                    else:
                        size = item.stat().st_size
                        size_str = self._format_size(size)
                        result_lines.append(f"📄 {item.name} ({size_str})")
            
            return "\n".join(result_lines)
            
        except PermissionError:
            return f"错误: 没有权限访问目录: {directory}"
        except Exception as e:
            return f"列出文件错误: {str(e)}"
    
    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"


class FileReaderSkill(BaseSkill):
    def __init__(self, base_dir: str = "."):
        self._base_dir = base_dir
    
    @property
    def name(self) -> str:
        return "file_reader"
    
    @property
    def description(self) -> str:
        return "文件读取能力，可以读取当前工程目录下的文件内容"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    def get_tools(self) -> List[BaseTool]:
        return [
            FileReaderTool(self._base_dir),
            ListFilesTool(self._base_dir)
        ]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        if config.get("base_dir"):
            self._base_dir = config["base_dir"]
        self.logger.info(f"FileReaderSkill loaded with base_dir: {self._base_dir}")
