import logging
from typing import Dict, Any, List

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ExampleTool(BaseTool):
    @property
    def name(self) -> str:
        return "example_tool"
    
    @property
    def description(self) -> str:
        return "这是一个示例工具，用于演示如何创建自定义工具"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input_text": {
                    "type": "string",
                    "description": "输入文本"
                }
            },
            "required": ["input_text"]
        }
    
    def execute(self, input_text: str) -> str:
        logger.info(f"ExampleTool executed with input: {input_text}")
        return f"处理结果: {input_text}"


class ExampleSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "example_skill"
    
    @property
    def description(self) -> str:
        return "示例技能，用于演示如何创建自定义 Skill"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    def get_tools(self) -> List[BaseTool]:
        return [ExampleTool()]
    
    def on_load(self, config: Dict[str, Any]) -> None:
        self.logger.info(f"ExampleSkill loaded with config: {config}")
    
    def on_unload(self) -> None:
        self.logger.info("ExampleSkill unloaded")
