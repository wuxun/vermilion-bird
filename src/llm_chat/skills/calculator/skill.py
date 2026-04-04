import ast
import math
import operator
from typing import Dict, Any, List, Optional, Union
import logging
from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)


class SafeCalculator(ast.NodeVisitor):
    """安全的数学表达式计算器，使用 AST 解析"""

    # 允许的操作符
    _operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    # 允许的函数
    _functions = {
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
    }

    # 允许的常量
    _constants = {
        "pi": math.pi,
        "e": math.e,
    }

    def evaluate(self, expression: str) -> Union[int, float]:
        """计算表达式"""
        tree = ast.parse(expression, mode="eval")
        return self._visit(tree.body)

    def _visit(self, node: ast.AST) -> Union[int, float]:
        """访问 AST 节点"""
        method = f"_visit_{type(node).__name__}"
        visitor = getattr(self, method, self._generic_visit)
        return visitor(node)

    def _visit_Constant(self, node: ast.Constant) -> Union[int, float]:
        """处理常量节点（Python 3.8+）"""
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"不允许的常量类型: {type(node.value)}")

    def _visit_Num(self, node: ast.Num) -> Union[int, float]:
        """处理数字节点（Python 3.7 及以下兼容）"""
        return node.n

    def _visit_Name(self, node: ast.Name) -> Union[int, float]:
        """处理名称节点（常量或函数引用）"""
        if node.id in self._constants:
            return self._constants[node.id]
        if node.id in self._functions:
            return self._functions[node.id]
        raise ValueError(f"不允许的名称: {node.id}")

    def _visit_BinOp(self, node: ast.BinOp) -> Union[int, float]:
        """处理二元操作符"""
        op_type = type(node.op)
        if op_type not in self._operators:
            raise ValueError(f"不允许的操作符: {op_type.__name__}")

        left = self._visit(node.left)
        right = self._visit(node.right)
        return self._operators[op_type](left, right)

    def _visit_UnaryOp(self, node: ast.UnaryOp) -> Union[int, float]:
        """处理一元操作符"""
        op_type = type(node.op)
        if op_type not in self._operators:
            raise ValueError(f"不允许的操作符: {op_type.__name__}")

        operand = self._visit(node.operand)
        return self._operators[op_type](operand)

    def _visit_Call(self, node: ast.Call) -> Union[int, float]:
        """处理函数调用"""
        if not isinstance(node.func, ast.Name):
            raise ValueError("只允许简单的函数调用")

        func_name = node.func.id
        if func_name not in self._functions:
            raise ValueError(f"不允许的函数: {func_name}")

        func = self._functions[func_name]
        args = [self._visit(arg) for arg in node.args]
        kwargs = {kw.arg: self._visit(kw.value) for kw in node.keywords}

        return func(*args, **kwargs)

    def _visit_Expr(self, node: ast.Expr) -> Union[int, float]:
        """处理表达式节点"""
        return self._visit(node.value)

    def _generic_visit(self, node: ast.AST) -> None:
        """处理未识别的节点"""
        raise ValueError(f"不允许的表达式结构: {type(node).__name__}")


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
        try:
            calculator = SafeCalculator()
            result = calculator.evaluate(expression)
            return str(result)

        except Exception as e:
            logger.warning(f"计算错误: {str(e)}, 表达式: {expression}")
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
