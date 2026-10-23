"""The test signing hierarchy, held by the signing service only (D34, AUT-33, SEC-12).

The test root and its intermediates are derived from published phrases, so they are not secrets and give no
authority: pilot and production builds trust only the release root (OPS-35). The content intermediate keeps the
development key and id the S1 packs were signed with. Production keys are never here: the signing service reaches them
by reference through `hierarchy.ProductionSigner` (keys in HSMs, two-person control for the root).
"""

from __future__ import annotations

import hashlib

from agent_core.config.trust import Purpose
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEV_KEY_ID = "key_dev_test"  # the content intermediate of the test root
DEV_ROOT_KEY_ID = "key_root_test"
DEV_KEY_IDS: dict[Purpose, str] = {
    Purpose.CONTENT: DEV_KEY_ID,
    Purpose.MODEL: "key_dev_model",
    Purpose.AGENT_BUNDLE: "key_dev_agent_bundle",
    Purpose.UPDATER: "key_dev_updater",
    Purpose.LICENCE: "key_dev_licence",
}
_DEV_PHRASE = b"jana development test signing root: never trusted by pilot or production builds"


def _derived(label: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(label).digest())


def dev_key(purpose: Purpose = Purpose.CONTENT) -> Ed25519PrivateKey:
    """The test hierarchy's intermediate for `purpose` (content by default)."""
    if purpose is Purpose.CONTENT:
        return _derived(_DEV_PHRASE)
    return _derived(_DEV_PHRASE + b": " + purpose.value.encode() + b" intermediate")


def dev_root_key() -> Ed25519PrivateKey:
    return _derived(_DEV_PHRASE + b": root")
