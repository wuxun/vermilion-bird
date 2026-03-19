import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ReplaceTextTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
    
    @property
    def name(self) -> str:
        return "replace_text"
    
    @property
    def description(self) -> str:
        return "替换文件中的文本内容。在指定文件中查找并替换文本。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "相对于工程根目录的文件路径"
                },
                "old_text": {
                    "type": "string",
                    "description": "要被替换的原始文本"
                },
                "new_text": {
                    "type": "string",
                    "description": "替换后的新文本"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换所有匹配项（默认只替换第一个）",
                    "default": False
                }
            },
            "required": ["file_path", "old_text", "new_text"]
        }
    
    def execute(self, file_path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        try:
            target_path = (self._base_dir / file_path).resolve()
            
            if not str(target_path).startswith(str(self._base_dir)):
                return f"错误: 不允许编辑工程目录外的文件"
            
            if not target_path.exists():
                return f"错误: 文件不存在: {file_path}"
            
            if not target_path.is_file():
                return f"错误: 路径不是文件: {file_path}"
            
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if old_text not in content:
                return f"错误: 未找到要替换的文本\n搜索文本: {old_text[:100]}..."
            
            count_before = content.count(old_text)
            
            if replace_all:
                new_content = content.replace(old_text, new_text)
                count_after = 0
            else:
                new_content = content.replace(old_text, new_text, 1)
                count_after = count_before - 1
            
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            
            logger.info(f"替换文本成功: {file_path}, 替换了 {count_before - count_after} 处")
            
            return f"成功替换文本\n文件: {file_path}\n替换次数: {count_before - count_after}\n剩余未替换: {count_after}"
            
        except PermissionError:
            return f"错误: 没有权限编辑文件: {file_path}"
        except Exception as e:
            return f"替换文本错误: {str(e)}"


class InsertTextTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
    
    @property
    def name(self) -> str:
        return "insert_text"
    
    @property
    def description(self) -> str:
        return "在文件的指定位置插入文本。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "相对于工程根目录的文件路径"
                },
                "text": {
                    "type": "string",
                    "description": "要插入的文本内容"
                },
                "line_number": {
                    "type": "integer",
                    "description": "插入位置的行号（从1开始，0表示文件末尾）",
                    "default": 0
                },
                "after_pattern": {
                    "type": "string",
                    "description": "在匹配此模式的行之后插入（可选，优先于line_number）"
                }
            },
            "required": ["file_path", "text"]
        }
    
    def execute(self, file_path: str, text: str, line_number: int = 0, after_pattern: Optional[str] = None) -> str:
        try:
            target_path = (self._base_dir / file_path).resolve()
            
            if not str(target_path).startswith(str(self._base_dir)):
                return f"错误: 不允许编辑工程目录外的文件"
            
            if not target_path.exists():
                return f"错误: 文件不存在: {file_path}"
            
            if not target_path.is_file():
                return f"错误: 路径不是文件: {file_path}"
            
            with open(target_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            insert_line = line_number
            
            if after_pattern:
                found = False
                for i, line in enumerate(lines):
                    if after_pattern in line:
                        insert_line = i + 2
                        found = True
                        break
                
                if not found:
                    return f"错误: 未找到匹配的模式: {after_pattern}"
            
            if insert_line == 0:
                insert_line = len(lines) + 1
            
            if insert_line < 1:
                insert_line = 1
            elif insert_line > len(lines) + 1:
                insert_line = len(lines) + 1
            
            if not text.endswith("\n"):
                text = text + "\n"
            
            lines.insert(insert_line - 1, text)
            
            with open(target_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            
            logger.info(f"插入文本成功: {file_path}, 行号: {insert_line}")
            
            return f"成功插入文本\n文件: {file_path}\n插入位置: 第 {insert_line} 行"
            
        except PermissionError:
            return f"错误: 没有权限编辑文件: {file_path}"
        except Exception as e:
            return f"插入文本错误: {str(e)}"


class DeleteLinesTool(BaseTool):
    def __init__(self, base_dir: str = "."):
        self._base_dir = Path(base_dir).resolve()
    
    @property
    def name(self) -> str:
        return "delete_lines"
    
    @property
    def description(self) -> str:
        return "删除文件中指定行范围的内容。"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "相对于工程根目录的文件路径"
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（从1开始）"
                },
                "end_line": {
                    "type": "integer",
                    "description": "结束行号（包含，默认等于start_line）"
                }
            },
            "required": ["file_path", "start_line"]
        }
    
    def execute(self, file_path: str, start_line: int, end_line: Optional[int] = None) -> str:
        try:
            target_path = (self._base_dir / file_path).resolve()
            
            if not str(target_path).startswith(str(self._base_dir)):
                return f"错误: 不允许编辑工程目录外的文件"
            
            if not target_path.exists():
                return f"错误: 文件不存在: {file_path}"
            
            if not target_path.is_file():
                return f"错误: 路径不是文件: {file_path}"
            
            if end_line is None:
                end_line = start_line
            
            with open(target_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            total_lines = len(lines)
            
            if start_line < 1 or start_line > total_lines:
                return f"错误: 起始行号无效: {start_line}（文件共 {total_lines} 行）"
            
            if end_line < start_line or end_line > total_lines:
                return f"错误: 结束行号无效: {end_line}（文件共 {total_lines} 行）"
            
            deleted_count = end_line - start_line + 1
            del lines[start_line - 1:end_line]
            
            with open(target_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            
            logger.info(f"删除行成功: {file_path}, 删除了第 {start_line}-{end_line} 行")
            
            return f"成功删除行\n文件: {file_path}\n删除范围: 第 {start_line} 行到第 {end_line} 行\n删除行数: {deleted_count}"
            
        except PermissionError:
            return f"错误: 没有权限编辑文件: {file_path}"
        except Exception as e:
            return f"删除行错误: {str(e)}"


class FileEditorSkill(BaseSkill):
    def __init__(self, base_dir: str = "."):
        self._base_dir = base_dir
    
    @property
    def name(self) -> str:
        return "file_editor"
    
    @property
    def description(self) -> str:
        return "文件编辑能力，可以替换、插入和删除当前工程目录下文件的内容"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    def get_tools(self) -> List[BaseTool]:
        return [
            ReplaceTextTool(self._base_dir),
            InsertTextTool(self._base_dir),
            DeleteLinesTool(self._base_dir)
        ]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        if config.get("base_dir"):
            self._base_dir = config["base_dir"]
        self.logger.info(f"FileEditorSkill loaded with base_dir: {self._base_dir}")
