"""Constants for the Ilumi Bluetooth bulbs integration."""
from __future__ import annotations

DOMAIN = "ilumi"

CONF_ADDRESS = "address"
CONF_NETWORK_KEY = "network_key"
CONF_NODE_ID = "node_id"
CONF_SETUP = "setup"
CONF_MODEL = "model"

SUBENTRY_BULB = "bulb"
MODEL_A19 = "A19"
MODEL_BR30 = "BR30"
MODELS = [MODEL_A19, MODEL_BR30]
# Icon of the light entity per shape. The tall bulb keeps the default icon.
MODEL_ICONS = {MODEL_A19: None, MODEL_BR30: "mdi:lightbulb-spot"}

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

# Place in the bulb where the effect is stored, the SDK uses 4 as well.
EFFECT_SCENE_INDEX = 4
# Pauses while a colour pattern is uploaded in chunks, taken from the SDK.
CHUNK_GAP_SECONDS = 0.05
CHUNK_DONE_SECONDS = 0.5
