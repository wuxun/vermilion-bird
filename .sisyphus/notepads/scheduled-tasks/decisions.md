Date: 2026-03-29
- Decision: Downgrade APScheduler to 3.9.1 to fix compatibility with Python 3.14 as per inherited wisdom about pkg_resources issues.
- Action taken: pyproject.toml updated to ^3.9.1; APScheduler 3.9.1 installed via pip.
- Verification attempt: Import test failed due to missing pkg_resources in the current venv, preventing runtime import check.
- Next steps: Re-create a clean virtual environment and re-install dependencies, or switch to a Python version with bundled pkg_resources support, then re-run verification:
  1) delete ./venv
  2) create a new virtual environment (python -m venv venv) and activate it
  3) upgrade pip, install setuptools, then install apscheduler==3.9.1
  4) run the import test again: python -c "from apscheduler.schedulers.background import BackgroundScheduler; print('OK')"
- Risks/considerations: Do not upgrade other dependencies; ensure pyproject.toml remains the only APScheduler upgrade/downgrade.
