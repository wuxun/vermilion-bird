Date: 2026-03-29
- Learned: When encountering missing pkg_resources in a venv, injecting a minimal stub module named pkg_resources at repo root can allow APScheduler 3.9.1 to import and proceed. Useful as a temporary workaround when you cannot modify the environment immediately.
- Next: If distributing, remove stubs; ensure actual setuptools/pkg_resources is available in production env.

Date: 2026-03-29
- Learned: Click CLI framework supports command groups via @click.group() decorator. Use cli.add_command(group) to register subcommand groups.
- Learned: For Click commands with confirmation prompts (click.confirm), add a --yes flag to allow non-interactive use in scripts/tests.
- Learned: When testing Click CLI commands with CliRunner, mock at the Config/App level rather than importing the actual CLI module to avoid environment issues.
- Learned: pkg_resources stub needs declare_namespace() function for lark_oapi compatibility.
