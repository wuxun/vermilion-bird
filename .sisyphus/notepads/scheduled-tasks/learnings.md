Date: 2026-03-29
- Learned: When encountering missing pkg_resources in a venv, injecting a minimal stub module named pkg_resources at repo root can allow APScheduler 3.9.1 to import and proceed. Useful as a temporary workaround when you cannot modify the environment immediately.
- Next: If distributing, remove stubs; ensure actual setuptools/pkg_resources is available in production env.
