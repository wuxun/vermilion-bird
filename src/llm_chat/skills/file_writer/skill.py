import os
import logging
from pathlib import Path
from typing import Dict, Any, List

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)


class FileWriterTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
    
    @property
    def name(self) -> str:
        return "write_file"
    
    @property
    def description(self) -> str:
        return "写入或创建文件到当前工程目录下。只能在工程文件夹内操作，不能写入外部文件。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "相对于工程根目录的文件路径，如 'src/utils.py' 或 'notes.txt'"
                },
                "content": {
                    "type": "string",
                    "description": "要写入的文件内容"
                },
                "mode": {
                    "type": "string",
                    "description": "写入模式：'write' 覆盖写入（默认），'append' 追加写入",
                    "enum": ["write", "append"],
                    "default": "write"
                }
            },
            "required": ["file_path", "content"]
        }
    
    def execute(self, file_path: str, content: str, mode: str = "write") -> str:
        try:
            target_path = (self._base_dir / file_path).resolve()
            
            if not str(target_path).startswith(str(self._base_dir)):
                return f"错误: 不允许写入工程目录外的文件。请求路径: {file_path}"
            
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            write_mode = "w" if mode == "write" else "a"
            
            with open(target_path, write_mode, encoding="utf-8") as f:
                f.write(content)
            
            action = "覆盖写入" if mode == "write" else "追加写入"
            logger.info(f"{action}文件成功: {file_path}")
            
            return f"成功{action}文件: {file_path}\n写入内容长度: {len(content)} 字符"
            
        except PermissionError:
            return f"错误: 没有权限写入文件: {file_path}"
        except Exception as e:
            return f"写入文件错误: {str(e)}"


class CreateDirectoryTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
    
    @property
    def name(self) -> str:
        return "create_directory"
    
    @property
    def description(self) -> str:
        return "在当前工程目录下创建新文件夹。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "dir_path": {
                    "type": "string",
                    "description": "相对于工程根目录的文件夹路径，如 'src/new_module'"
                }
            },
            "required": ["dir_path"]
        }
    
    def execute(self, dir_path: str) -> str:
        try:
            target_path = (self._base_dir / dir_path).resolve()
            
            if not str(target_path).startswith(str(self._base_dir)):
                return f"错误: 不允许在工程目录外创建文件夹。请求路径: {dir_path}"
            
            target_path.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"创建目录成功: {dir_path}")
            
            return f"成功创建目录: {dir_path}"
            
        except PermissionError:
            return f"错误: 没有权限创建目录: {dir_path}"
        except Exception as e:
            return f"创建目录错误: {str(e)}"


class DeleteFileTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
    
    @property
    def name(self) -> str:
        return "delete_file"
    
    @property
    def description(self) -> str:
        return "删除当前工程目录下的文件。注意：此操作不可恢复！"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "相对于工程根目录的要删除的文件路径"
                }
            },
            "required": ["file_path"]
        }
    
    def execute(self, file_path: str) -> str:
        try:
            target_path = (self._base_dir / file_path).resolve()
            
            if not str(target_path).startswith(str(self._base_dir)):
                return f"错误: 不允许删除工程目录外的文件。请求路径: {file_path}"
            
            if not target_path.exists():
                return f"错误: 文件不存在: {file_path}"
            
            if not target_path.is_file():
                return f"错误: 路径不是文件: {file_path}"
            
            protected_files = {"config.yaml", ".env", "secrets.yaml"}
            if target_path.name in protected_files:
                return f"错误: 受保护的文件，不允许删除: {file_path}"
            
            target_path.unlink()
            
            logger.info(f"删除文件成功: {file_path}")
            
            return f"成功删除文件: {file_path}"
            
        except PermissionError:
            return f"错误: 没有权限删除文件: {file_path}"
        except Exception as e:
            return f"删除文件错误: {str(e)}"


class FileWriterSkill(BaseSkill):
    def __init__(self, base_dir: str = "."):
        self._base_dir = base_dir
    
    @property
    def name(self) -> str:
        return "file_writer"
    
    @property
    def description(self) -> str:
        return "文件写入能力，可以创建、修改和删除当前工程目录下的文件"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    def get_tools(self) -> List[BaseTool]:
        return [
            FileWriterTool(self._base_dir),
            CreateDirectoryTool(self._base_dir),
            DeleteFileTool(self._base_dir)
        ]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        if config.get("base_dir"):
            self._base_dir = config["base_dir"]
        self.logger.info(f"FileWriterSkill loaded with base_dir: {self._base_dir}")
