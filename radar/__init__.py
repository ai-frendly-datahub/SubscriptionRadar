from __future__ import annotations

import importlib
import sys


_ALIASES = {
    "analyzer": "subscriptionradar.analyzer",
    "collector": "subscriptionradar.collector",
    "exceptions": "subscriptionradar.exceptions",
    "models": "subscriptionradar.models",
    "nl_query": "subscriptionradar.nl_query",
    "reporter": "subscriptionradar.reporter",
    "search_index": "subscriptionradar.search_index",
    "storage": "subscriptionradar.storage",
}


for _name, _target in _ALIASES.items():
    sys.modules[f"{__name__}.{_name}"] = importlib.import_module(_target)


__all__ = sorted(_ALIASES)
