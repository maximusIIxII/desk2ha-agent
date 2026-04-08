"""Registry of collectors that require elevated privileges.

Add module paths here for collectors that need admin/root access.
The helper process will probe and activate these automatically.
"""

from __future__ import annotations

# Collectors that require elevated privileges.
# Each must expose a COLLECTOR_CLASS with the standard Collector interface.
ELEVATED_MODULES: list[str] = [
    "desk2ha_agent.collector.vendor.dell_dcm",
]
