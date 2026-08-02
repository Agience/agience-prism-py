"""The base install is the CONTRACT and it must stay dependency-free.

⚠ WHY THIS IS A GATE AND NOT A CONVENTION. Until 2026-07-30 `prism/__init__.py` imported
`.trust`, `.host` and `.server` at module scope, so `import prism` required python-jose,
cryptography, fastapi, uvicorn, httpx and mcp. Six packages to read one constant.

That was not a tidiness problem, it had a measured cost: `agience-beam` would not take the
dependency and VENDORED a byte-identical copy of `canonical.py`; `agience-bundle` vendored a second
one for its bare installer. **Three copies of the code that decides every content address and every
signature**, kept in step only by a drift gate — because importing the SDK was too expensive.

So the rule is load-bearing in both directions:

  · keep the contract pure  ⇒  beam can import it  ⇒  one canonicaliser instead of three
  · let one eager import in ⇒  fastapi lands on the fiber's install path ⇒ the copies come back

The contract is `canonical`, `capabilities`, `crystal_model`, `config`, `errors`, `structural`,
`environment` — 1,012 lines of stdlib. Everything else is an extra.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

PRISM = pathlib.Path(__file__).resolve().parents[1] / "src" / "prism"

#: The modules a bare `pip install agience-prism` must be able to import.
CONTRACT = ["canonical", "capabilities", "crystal_model", "config", "errors", "structural",
            "environment"]

#: Packages that must NEVER be reachable at import time from the contract.
HEAVY = {"fastapi", "uvicorn", "httpx", "mcp", "jose", "jwt", "starlette", "pydantic"}


def _eager_imports(path: pathlib.Path) -> set[str]:
    """Top-level (module-scope) imports only — an import inside a function is not an install cost."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = {id(n) for n in tree.body}
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) not in top:
            continue
        if isinstance(node, ast.ImportFrom) and node.level:      # relative — intra-package
            continue
        mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module or ""])
        out |= {m.split(".")[0] for m in mods if m}
    return out


@pytest.mark.parametrize("module", CONTRACT)
def test_contract_module_has_no_heavy_eager_import(module):
    found = _eager_imports(PRISM / f"{module}.py") & HEAVY
    assert not found, (
        f"prism/{module}.py imports {sorted(found)} at module scope. The contract must be "
        f"importable on a dependency-free install — move it inside the function that needs it, or "
        f"the module out of the contract.")


def test_package_init_does_not_eagerly_import_a_runtime_surface():
    """⛔ THE ONE THAT ACTUALLY BREAKS THE INSTALL. Importing ANY submodule runs `__init__.py`
    first, so a single eager `from .trust import …` here makes every one of the tests above
    irrelevant — `import prism.canonical` would still pull jose."""
    eager = _eager_imports(PRISM / "__init__.py")
    assert not (eager & HEAVY), f"prism/__init__.py eagerly imports {sorted(eager & HEAVY)}"

    tree = ast.parse((PRISM / "__init__.py").read_text(encoding="utf-8"))
    relative = {n.module for n in tree.body
                if isinstance(n, ast.ImportFrom) and n.level and n.module}
    relative |= {a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    forbidden = relative & {"trust", "host", "server"}
    assert not forbidden, (
        f"prism/__init__.py eagerly imports {sorted(forbidden)}. These are EXTRAS — reach them "
        f"through the `__getattr__` lazy table so the base install stays dependency-free.")


def test_the_contract_imports_in_a_subprocess_with_the_heavy_packages_blocked():
    """⛔ THE REAL PROOF, AND THE ONLY ONE THAT CANNOT LIE.

    Every check above reads source. Source analysis cannot see an import that happens through
    `importlib`, a `__getattr__` that fires on module load, or a transitive pull from a sibling.
    This blocks each heavy package outright — a `meta_path` finder that raises for them — and then
    imports the contract for real. If anything reaches for fastapi, this fails with a traceback
    pointing at the line that did.

    Run in a SUBPROCESS because the packages are installed in this environment: blocking them in
    the current interpreter would not survive the modules already in `sys.modules`."""
    program = f"""
import sys

BLOCKED = {sorted(HEAVY)!r}

class _Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in BLOCKED:
            raise ImportError(
                'BLOCKED BY THE TEST: the contract reached for %r, which is an extra' % name)
        return None

sys.meta_path.insert(0, _Blocker())
for m in list(sys.modules):
    if m.split('.')[0] in BLOCKED:
        del sys.modules[m]

import prism
from prism.canonical import canonical_string
from prism.crystal_model import *          # noqa: F401,F403
from prism import Prism, Capability, PrismError

assert canonical_string({{'b': 1, 'a': 2}}) == '{{"a":2,"b":1}}', 'canonical JSON is wrong'
print('CONTRACT OK')
"""
    r = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                       cwd=str(PRISM.parents[1]))
    assert "CONTRACT OK" in r.stdout, (
        "the contract could not be imported with the extras blocked:\n"
        + (r.stderr or r.stdout)[-2500:])


def test_asking_for_a_runtime_surface_without_its_extra_says_which_extra():
    """The lazy loader must fail with an instruction, not `No module named 'fastapi'`.

    ⚠ NEGATIVE CONTROL for the laziness itself: if `__getattr__` were removed and the imports made
    eager again, this test would fail at `import prism` rather than here — so it also guards the
    mechanism, not just the message."""
    program = """
import sys

class _Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('fastapi', 'starlette'):
            raise ImportError('blocked')
        return None

sys.meta_path.insert(0, _Blocker())
for m in list(sys.modules):
    if m.split('.')[0] in ('fastapi', 'starlette'):
        del sys.modules[m]

import prism                      # must succeed: the contract does not need fastapi
try:
    prism.Host                     # must fail, and say how to fix it
except ImportError as e:
    assert 'agience-prism[host]' in str(e), 'the error does not name the extra: %s' % e
    print('MESSAGE OK')
else:
    print('NO ERROR RAISED')
"""
    r = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                       cwd=str(PRISM.parents[1]))
    assert "MESSAGE OK" in r.stdout, (r.stderr or r.stdout)[-2000:]


def test_the_declared_extras_cover_every_runtime_surface():
    """A surface with no extra is one nobody can install. Reads the manifest, not a memorised list."""
    try:
        import tomllib
    except ModuleNotFoundError:                                  # pragma: no cover
        import tomli as tomllib                                  # type: ignore[no-redef]
    pyproject = tomllib.loads(
        (PRISM.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == [], (
        "the base install grew a dependency — that is the whole thing this file exists to prevent")
    extras = pyproject["project"]["optional-dependencies"]
    for surface in ("trust", "host", "server"):
        assert surface in extras, f"prism.{surface} has no `{surface}` extra to install it with"
        assert extras[surface], f"the `{surface}` extra is empty"
