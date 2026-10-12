"""Communication Adapter layer (SRS Figure 2.2).

The rest of the app imports from here and never touches ``wss_py_wrapper`` directly.
"""

from .base import (
    AdapterStatus,
    CommandRecord,
    CommunicationAdapter,
    ConnectionLostError,
    ConnectionState,
)
from .factory import MODES, add_mode_arguments, create_adapter, load_app_config, resolve_mode
from .fake_adapter import FakeCommunicationAdapter

__all__ = [
    "AdapterStatus",
    "CommandRecord",
    "CommunicationAdapter",
    "ConnectionLostError",
    "ConnectionState",
    "FakeCommunicationAdapter",
    "MODES",
    "add_mode_arguments",
    "create_adapter",
    "load_app_config",
    "resolve_mode",
]
