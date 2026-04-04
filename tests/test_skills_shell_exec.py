import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from llm_chat.skills.shell_exec.skill import (
    ShellExecTool,
    ShellExecSkill,
    DEFAULT_WHITELIST,
)


class TestShellExecTool:
    def test_allowed_command_ls(self):
        tool = ShellExecTool(whitelist=["ls"], allowed_workdir="./")
        result = tool.execute(command="ls")
        assert "Return code: 0" in result or "Return code:" in result

    def test_allowed_command_pwd(self):
        tool = ShellExecTool(whitelist=["pwd"], allowed_workdir="./")
        result = tool.execute(command="pwd")
        assert "Return code: 0" in result
        assert os.path.abspath("./") in result

    def test_disallowed_command_rm(self):
        tool = ShellExecTool(whitelist=["ls", "pwd"], allowed_workdir="./")
        result = tool.execute(command="rm test.txt")
        assert "Error:" in result
        assert "not in whitelist" in result

    def test_disallowed_command_echo(self):
        tool = ShellExecTool(whitelist=["ls"], allowed_workdir="./")
        result = tool.execute(command='echo "hello"')
        assert "Error:" in result
        assert "not in whitelist" in result

    def test_workdir_outside_allowed(self):
        tool = ShellExecTool(whitelist=["pwd"], allowed_workdir="./")
        result = tool.execute(command="pwd", workdir="/tmp")
        assert "Error:" in result
        assert "outside the allowed directory" in result

    def test_workdir_not_exist(self):
        tool = ShellExecTool(whitelist=["pwd"], allowed_workdir="./")
        result = tool.execute(command="pwd", workdir="./nonexistent_dir_12345")
        assert "Error:" in result
        assert "does not exist" in result

    def test_timeout(self):
        tool = ShellExecTool(
            whitelist=["sleep"], allowed_workdir="./", max_output_length=10000
        )
        result = tool.execute(command="sleep 10", timeout=2)
        assert "timed out" in result or "Error:" in result

    def test_output_truncation(self):
        tool = ShellExecTool(
            whitelist=["ls"], allowed_workdir="./", max_output_length=50
        )
        result = tool.execute(command="ls")
        if len(result) > 50:
            assert "[Output truncated" in result

    def test_default_whitelist(self):
        tool = ShellExecTool()
        assert "ls" in tool._whitelist
        assert "pwd" in tool._whitelist
        assert "cat" in tool._whitelist

    def test_command_with_args(self):
        tool = ShellExecTool(whitelist=["ls"], allowed_workdir="./")
        result = tool.execute(command="ls -la")
        assert "Return code:" in result


class TestShellExecSkill:
    def test_skill_name(self):
        skill = ShellExecSkill()
        assert skill.name == "shell_exec"

    def test_skill_description(self):
        skill = ShellExecSkill()
        assert "shell" in skill.description.lower() or "Shell" in skill.description

    def test_skill_version(self):
        skill = ShellExecSkill()
        assert skill.version == "1.0.0"

    def test_get_tools(self):
        skill = ShellExecSkill()
        tools = skill.get_tools()
        assert len(tools) == 1
        assert tools[0].name == "shell_exec"

    def test_on_load_config(self):
        skill = ShellExecSkill()
        skill.on_load(
            {
                "whitelist": ["ls", "pwd"],
                "allowed_workdir": "./",
                "max_output_length": 500,
            }
        )
        assert skill._whitelist == ["ls", "pwd"]
        assert skill._max_output_length == 500

    def test_on_load_default_config(self):
        skill = ShellExecSkill()
        skill.on_load()
        assert skill._whitelist == DEFAULT_WHITELIST
        assert skill._max_output_length == 10000

    def test_tool_uses_skill_config(self):
        skill = ShellExecSkill()
        skill.on_load(
            {
                "whitelist": ["ls"],
                "allowed_workdir": "./",
                "max_output_length": 100,
            }
        )
        tool = skill.get_tools()[0]
        result = tool.execute(command="pwd")
        assert "not in whitelist" in result

    def test_tool_can_execute_ls(self):
        skill = ShellExecSkill()
        skill.on_load(
            {
                "whitelist": ["ls"],
                "allowed_workdir": "./",
                "max_output_length": 1000,
            }
        )
        tool = skill.get_tools()[0]
        result = tool.execute(command="ls")
        assert "Return code:" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
