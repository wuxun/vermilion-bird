import ast
import math
from typing import Dict, Any, List
import logging
from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

import logging
from llm_chat.config import Config

logger = logging.getLogger(__name__)


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
        """安全地执行数学表达式计算
        
        使用 ast 模块解析和验证表达式，只允许安全的操作。
        支持:
            - 帺本算术运算: +, -, *, /, **, (), ()
            - 幂运算: **, pow
            - 数学函数: abs, round, min, max, sum, sqrt, sin, cos, tan, log, log10, log2, exp
            - 数学常量: pi, e
        """
        
        # 允许的字符集（字母、数字、运算符、括号)
        allowed_chars = set('01234567890+-*/().%abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ')
        for char in expression:
            if char not in allowed_chars:
                return f"错误: 表达式包含不允许的字符: {char}"
        
        # 使用 ast 模块进行安全解析
        try:
            node = ast.parse(expression, mode='eval')
            
            # 验证节点类型 - 只允许安全的操作
            allowed_nodes = (
                ast.Expression,      # 表达式
                ast.BinOp,          # 二元运算
                ast.UnaryOp,        # 一元运算
                ast.Num,          # 数字
                ast.Constant,      # 岒量
            )
            
            # 递归遍历 AST 节点，验证安全性
            for node in ast.walk(node):
                if not isinstance(node, allowed_nodes):
                    return f"错误: 表达式包含不允许的操作"
                
                # 安全执行计算
                safe_builtins = {}
                for name, allowed_functions:
                    if name not in safe_builtins:
                        safe_builtins[name] = safe_functions[name]
                    else:
                        raise ValueError(f"不允许的函数: {name}")
                
                # 执行计算
                result = eval(code, {"__builtins__": {}}, safe_builtins)
                return str(result)
            
            except Exception as e:
                return f"计算错误: {str(e)}"
