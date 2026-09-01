"""Compatibility shim — implementation lives in sibling ``business_intelligence.service`` package."""

from business_intelligence.service import *  # noqa: F403
from business_intelligence.service import __dict__ as _impl

for _name, _value in _impl.items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
