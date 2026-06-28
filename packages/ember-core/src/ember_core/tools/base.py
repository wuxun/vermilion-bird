"""BaseTool — abstract base class for all tools.

Tools are pure computation units that accept keyword arguments and return a string.
They have NO awareness of LLMs, protocols, or agent concepts.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Abstract base for all tool implementations.

    A tool is a named, self-describing callable that:
    - Has a name (unique identifier)
    - Has a description (natural language, for LLMs to decide when to call)
    - Has a parameters schema (JSON Schema dict)
    - Has an execute method (the actual implementation)
    - Can serialize itself to OpenAI / Anthropic tool format
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier, used as the function name in LLM calls."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Natural language description of what the tool does."""

    @abstractmethod
    def get_parameters_schema(self) -> Dict[str, Any]:
        """JSON Schema dict describing the tool's input parameters."""

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Execute the tool with given keyword arguments. Returns string result."""

    def to_openai_tool(self) -> Dict[str, Any]:
        """Serialize to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema(),
            },
        }

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Serialize to Anthropic tool-use format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.get_parameters_schema(),
        }
