"""Constants for the Ilumi Bluetooth bulbs integration."""
from __future__ import annotations

DOMAIN = "ilumi"

CONF_ADDRESS = "address"
CONF_NETWORK_KEY = "network_key"
CONF_NODE_ID = "node_id"
CONF_SETUP = "setup"

# Taken from PROTOCOL.md of the ilumi-sdk project.
SERVICE_UUID = "f000f0c0-0451-4000-b000-000000000000"
CHAR_UUID = "f000f0c1-0451-4000-b000-000000000000"

# The connection is dropped this long after the last command so that the
# Bluetooth proxy slot is free again for other devices.
IDLE_DISCONNECT_SECONDS = 6
# Pause between two packets that belong to one user action.
COMMAND_GAP_SECONDS = 0.3
# Fade time for on/off in milliseconds.
TRANSIT_MS = 300

SEQ_STORAGE_KEY = "ilumi_seq"
SEQ_STORAGE_VERSION = 1

# Group number written into a bulb when it is set up. Nothing in this
# integration uses groups, the SDK's enroll.py uses 1 as well.
SETUP_GROUP_ID = 1
