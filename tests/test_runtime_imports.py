"""The in-app build chain must not load development-only packages.

D-31 splits dependencies into a runtime manifest (requirements.txt, what the
deployed app installs) and a development one (requirements-dev.txt). Anything
the build chain imports at module level has to be in the runtime manifest, so a
module-level import of a dev-only package on the chain would crash the deployed
app on a fresh install while every test here still passed.

The check runs in a fresh interpreter, so nothing already imported by pytest
or another test can mask a violation. When P2.9b adds a module to the chain,
add it to CHAIN.
"""
import subprocess
import sys

import pytest

CHAIN = [
    "src.build",          # P2.9b: the in-app build function
    "src.linkedin",
    "src.ingestion",
    "src.classify_pipeline",
    "src.embeddings",
    "src.projection_3d",
    "src.graph",
    "src.centrality",
]
DEV_ONLY = ["matplotlib", "faker", "dotenv", "pytest"]


@pytest.mark.parametrize("module", CHAIN)
def test_chain_module_loads_no_dev_only_package(module):
    code = (
        "import sys, importlib\n"
        f"importlib.import_module({module!r})\n"
        f"print(','.join(p for p in {DEV_ONLY!r} if p in sys.modules))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    loaded = r.stdout.strip()
    assert loaded == "", f"{module} loads dev-only package(s): {loaded}"
