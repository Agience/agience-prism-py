"""The README is the PyPI page, so its claims are asserted here rather than reviewed.

Two things are pinned: every Python block works, and every repository file the README links to is
present. A link to a missing file is a 404 on the published page.

Each block is checked twice, because neither check alone covers it. Running the block catches a
failing import and a wrong name in a decorator or a signature. It cannot catch a name used only
inside a function body the block never calls — a coroutine is defined and never awaited, so nothing
raises. Ruff's F821 reads the block statically and catches that.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

#: An unpacked sdist carries README, LICENSE, NOTICE and the source, and nothing else from the repo
#: root. `PKG-INFO` is written by the build and never exists in the repo, so it is the direct signal
#: for "this tree is a distribution". Repo-shape assertions are about the repository; asserting them
#: against a distribution measures what setuptools chose to pack, not what the project carries.
IS_SDIST = (REPO / "PKG-INFO").is_file()
README = REPO / "README.md"
TEXT = README.read_text(encoding="utf-8")

#: Blocks that describe a shell session rather than a program.
BLOCKS = re.findall(r"```python\n(.*?)```", TEXT, re.S)

#: Files the README and CONTRIBUTING link to by name, which must exist in the repository.
LINKED_FILES = ("LICENSE", "NOTICE", "CONTRIBUTING.md", "SECURITY.md")

#: Documentation the repository carries. A file dropped from a commit leaves a clean-looking tree,
#: so its presence is asserted rather than assumed.
REQUIRED_DOCS = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md",
                 "LICENSE", "NOTICE")


def test_there_are_python_blocks_to_check():
    """Vacuity control. A README whose fences were renamed would pass every test below by having
    nothing to run."""
    assert len(BLOCKS) >= 3, "found %d python blocks — the extraction regex has stopped matching" % len(BLOCKS)


@pytest.mark.parametrize("index", range(len(BLOCKS)))
def test_no_python_block_uses_an_undefined_name(index, tmp_path):
    """The static half. Catches a name the block never gets far enough to evaluate — a helper used
    only inside an uncalled function body, which running the block cannot see."""
    block = tmp_path / ("block_%d.py" % index)
    block.write_text(BLOCKS[index], encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "F821",
         "--output-format", "concise", str(block)],
        capture_output=True, text=True, timeout=120)
    if proc.returncode not in (0, 1):
        pytest.skip("ruff is not available: %s" % proc.stderr.strip()[:200])
    assert proc.returncode == 0, (
        "README python block %d uses an undefined name:\n%s\n---\n%s"
        % (index, BLOCKS[index], proc.stdout.strip()))


@pytest.mark.parametrize("index", range(len(BLOCKS)))
def test_every_python_block_runs(index):
    """Each block, executed verbatim. Fails on an undefined name, a missing import, or an API that
    has moved — the three ways a snippet rots after the code around it changes."""
    source = BLOCKS[index]
    proc = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True,
                          cwd=str(REPO / "src"), timeout=120)
    if proc.returncode != 0 and "ModuleNotFoundError" in proc.stderr:
        missing = proc.stderr.strip().splitlines()[-1]
        if not any(k in missing for k in ("prism",)):
            pytest.skip("block %d needs an extra that is not installed: %s" % (index, missing))
    assert proc.returncode == 0, (
        "README python block %d does not run:\n%s\n---\n%s"
        % (index, source, proc.stderr.strip()[-1500:]))


@pytest.mark.parametrize("name", REQUIRED_DOCS)
def test_the_documented_files_exist(name):
    """The repository carries what its own documents point at."""
    if IS_SDIST:
        pytest.skip("this tree is an unpacked sdist, which packs only a subset of the repo root")
    assert (REPO / name).is_file(), "%s is missing from the repository" % name


@pytest.mark.parametrize("name", LINKED_FILES)
def test_every_linked_repository_file_is_present(name):
    """A README link to a file that is not there is a 404 on the PyPI page."""
    if IS_SDIST:
        pytest.skip("this tree is an unpacked sdist, which packs only a subset of the repo root")
    if name not in TEXT:
        pytest.skip("%s is not linked from the README" % name)
    assert (REPO / name).is_file(), "the README links %s, which is not in the repository" % name


def test_the_install_name_is_the_distribution_name():
    """The README tells a reader what to `pip install`. It has to be what the package is called."""
    import tomllib
    meta = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    dist = meta["project"]["name"]
    assert "pip install %s" % dist in TEXT, (
        "the README does not tell a reader to install %r" % dist)
    stale = re.findall(r"pip install \"?(agience-prism-py[^\"\s\[]*)", TEXT)
    assert not stale, "the README still installs a name that is not the distribution: %s" % stale
