import ast
import math
from typing import Dict, Any, List
import logging
from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

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
                    "description": "数学表达式，如 '2 + 3 * 4' 或 'sqrt(16)'",
                }
            },
            "required": ["expression"],
        }

    def execute(self, expression: str) -> str:
        allowed_names = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "log": math.log,
            "log10": math.log10,
            "log2": math.log2,
            "exp": math.exp,
            "pi": math.pi,
            "e": math.e,
        }

        try:
            for char in expression:
                if char.isalpha() or char == "_":
                    continue
                if char.isdigit() or char in "+-*/().% ":
                    continue
                if char not in allowed_names:
                    return f"错误: 表达式包含不允许的字符: {char}"

            result = eval(expression, {"__builtins__": {}}, allowed_names)
            return str(result)

        except Exception as e:
            return f"计算错误: {str(e)}"


class CalculatorSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return "数学计算能力，支持基本算术运算、幂运算、开方等"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_tools(self) -> List[BaseTool]:
        return [CalculatorTool()]

    def on_load(self, config: Dict[str, Any]) -> None:
        self.logger.info(f"CalculatorSkill loaded with config: {config}")
