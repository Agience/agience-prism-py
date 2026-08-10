"""Alias module — the instrument contract reachable under its `Embodiment` spelling.

The contract itself lives in `prism/instrument.py`, which declares what an instrument must do and is
where the wire asks for the one that was injected. This module forwards those names and binds three
of them to a second spelling:

    Embodiment          is  Instrument
    EmbodimentRequired  is  InstrumentRequired
    EMBODIMENT_MEMBERS  is  INSTRUMENT_MEMBERS

They are bindings rather than a second definition, and that is what holds the two spellings together.
`Embodiment is Instrument` is True — one Protocol object, one member set, one identity — so
`isinstance(stub, Embodiment)` in crystal's suite and `isinstance(stub, Instrument)` elsewhere answer
the same question about the same thing. A shim that re-declared the protocol would be a second copy
free to drift. A `sys.modules` rebind is unavailable here, because the spellings differ:
`from prism.embodiment import Embodiment` resolves, while `prism.instrument` carries only the
primary names.

`test_contract_install_is_pure.py` asserts every alias is identical to its primary-spelling original,
so an edit that redefines rather than rebinds fails. This file is a bridge: a name declared only
here, with no original behind it, would make it a surface of its own.

`prism/instrument.py` carries the whole contract, including why `Conservation` keeps its name and why
the slot name is `contract="embodiment"`.

Consumers that import through this module:

    agience-crystal/tests/test_embodiment_injection.py   Embodiment, EMBODIMENT_MEMBERS,
                                                         EmbodimentRequired  (2 import sites)
    agience-chorus/src/lumen/tests/test_curriculum.py    EmbodimentRequired  (2 import sites)
"""
from __future__ import annotations

from .instrument import (  # noqa: F401
    Accumulator,
    CONSERVATION_MEMBERS,
    Conservation,
    DYNAMICS_MEMBERS,
    DiffractionLimit,
    Dynamics,
    INSTRUMENT_MEMBERS,
    Instrument,
    InstrumentRequired,
    Ledger,
    Propagator,
    READ_MEMBERS,
    Read,
    Screen,
    SpectralRead,
    members_of,
    require,
)

#: The alternate spellings, bound to the objects they name. `is` holds for every one.
Embodiment = Instrument
EmbodimentRequired = InstrumentRequired
EMBODIMENT_MEMBERS = INSTRUMENT_MEMBERS

#: What this file forwards, alternate spellings included, so `from prism.embodiment import *` and
#: `import prism.embodiment` present the same surface.
_RETIRED = {
    "Embodiment": "Instrument",
    "EmbodimentRequired": "InstrumentRequired",
    "EMBODIMENT_MEMBERS": "INSTRUMENT_MEMBERS",
}

__all__ = [
    "Instrument",
    "Read",
    "Dynamics",
    "Conservation",
    "Ledger",
    "Screen",
    "SpectralRead",
    "Accumulator",
    "Propagator",
    "DiffractionLimit",
    "InstrumentRequired",
    "require",
    "members_of",
    "INSTRUMENT_MEMBERS",
    "READ_MEMBERS",
    "DYNAMICS_MEMBERS",
    "CONSERVATION_MEMBERS",
    # the alternate spellings
    "Embodiment",
    "EmbodimentRequired",
    "EMBODIMENT_MEMBERS",
]
