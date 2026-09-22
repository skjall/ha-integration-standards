"""Constants of the integration.

Anything about the device itself - protocol identifiers, command bytes, wire
constants - belongs in the {{lib_package}} package and is re-exported here, so
the platforms have a single place to import from.
"""

from typing import Final

DOMAIN: Final = "{{domain}}"
MANUFACTURER: Final = "{{manufacturer}}"

CONF_INTERVAL: Final = "interval"

DEFAULT_INTERVAL: Final = 60
MIN_INTERVAL: Final = 10
MAX_INTERVAL: Final = 86400
