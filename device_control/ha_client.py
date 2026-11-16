"""Compatibility shim: the Home Assistant client now lives in bdh_sdk.ha."""

import requests  # noqa: F401  (kept so tests can patch device_control.ha_client.requests)

from bdh_sdk.ha import (  # noqa: F401
    TIMEOUT,
    HAError,
    call_service,
    get_all_states,
    get_entity_state,
    get_entity_states,
    get_history,
    get_registry,
    get_static,
    ws_commands,
)
# In the container, a call the hub refused (no grant) raises BrokerError, not HAError.
from bdh_sdk.rpc import BrokerError  # noqa: F401

HA_ERRORS = (HAError, BrokerError)
