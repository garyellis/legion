"""
Wake on LAN implementation.

Send a magic packet over UDP to remotely power on a machine.
The target machine must have WoL enabled in BIOS and the NIC
must be connected to power.
"""

from __future__ import annotations  # enables forward references in type hints

import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAC_BYTE_LENGTH: Final[int] = 6
MAGIC_PACKET_HEADER: Final[bytes] = b"\xff" * 6   # 6× 0xFF prefix
MAGIC_PACKET_LENGTH: Final[int] = 102             # 6 + (6 × 16)


# ---------------------------------------------------------------------------
# Type Aliases
# ---------------------------------------------------------------------------

MacAddress = str    # "AA:BB:CC:DD:EE:FF" or "AA-BB-CC-DD-EE-FF" or "AABBCCDDEEFF"
RawMacBytes = bytes  # always exactly 6 bytes internally


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WoLPort(int, Enum):
    """Standard UDP ports used for WoL packets.

    Port 9 (discard) is the convention; any port works because
    the NIC processes the packet at the hardware level before the OS.
    """
    DISCARD = 9   # most common
    ECHO    = 7   # also used


class BroadcastAddress(str, Enum):
    """Common IP broadcast targets.

    Use GLOBAL for cross-subnet WoL via a router that supports
    directed broadcast forwarding. Use subnet-specific addresses
    when keeping traffic on the local segment.
    """
    GLOBAL = "255.255.255.255"


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class WoLError(Exception):
    """Base class for all Wake-on-LAN errors."""


class InvalidMACError(WoLError):
    """Raised when a MAC address string cannot be parsed or is wrong length."""


class PacketBuildError(WoLError):
    """Raised when the magic packet cannot be constructed."""


class SendError(WoLError):
    """Raised when the UDP send fails."""


# ---------------------------------------------------------------------------
# Pydantic Model — validates external / user-supplied input
# ---------------------------------------------------------------------------

class WoLConfig(BaseModel):
    """Validated, immutable configuration for a single WoL send operation.

    Pydantic runs validators on construction, so a WoLConfig instance
    is always in a known-good state — no need to re-validate later.
    """

    mac_address: MacAddress = Field(
        ...,
        description="Target machine MAC address (any standard separator format).",
        examples=["AA:BB:CC:DD:EE:FF", "AA-BB-CC-DD-EE-FF", "AABBCCDDEEFF"],
    )
    broadcast_address: str = Field(
        default=BroadcastAddress.GLOBAL,
        description="Destination broadcast IP address.",
    )
    port: WoLPort = Field(
        default=WoLPort.DISCARD,
        description="UDP port to send the magic packet to.",
    )

    @field_validator("mac_address")
    @classmethod
    def normalize_and_validate_mac(cls, value: str) -> str:
        """Strip separators, uppercase, validate length and hex chars."""
        cleaned = value.replace(":", "").replace("-", "").upper()
        if len(cleaned) != 12:
            raise ValueError(
                f"MAC address must be 12 hex characters, got {len(cleaned)!r} from {value!r}"
            )
        try:
            int(cleaned, 16)
        except ValueError:
            raise ValueError(f"MAC address contains non-hex characters: {value!r}")
        return ":".join(cleaned[i:i+2] for i in range(0, 12, 2))

    model_config = {
        "frozen": True,          # instances are immutable
        "use_enum_values": True, # store enum .value so JSON serialization works
    }


# ---------------------------------------------------------------------------
# Dataclass — internal data structure (no validation overhead)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MagicPacket:
    """An immutable, pre-built Wake-on-LAN magic packet ready to send.

    Attributes:
        mac_bytes: The 6-byte MAC address of the target machine.
        payload:   The full 102-byte packet (header + MAC × 16).
                   Built automatically in __post_init__.
    """

    mac_bytes: RawMacBytes               # 6 bytes, set by caller
    payload:   bytes = field(init=False) # computed, not passed in

    def __post_init__(self) -> None:
        """Validate mac_bytes length and build the payload."""
        if len(self.mac_bytes) != MAC_BYTE_LENGTH:
            raise PacketBuildError(
                f"MAC must be {MAC_BYTE_LENGTH} bytes, got {len(self.mac_bytes)}"
            )
        object.__setattr__(
            self,
            "payload",
            MAGIC_PACKET_HEADER + self.mac_bytes * 16,
        )


# ---------------------------------------------------------------------------
# Protocol — defines an interface without requiring inheritance
# ---------------------------------------------------------------------------

@runtime_checkable
class PacketSender(Protocol):
    """Interface contract for anything that can send a MagicPacket."""

    def send(self, packet: MagicPacket, config: WoLConfig) -> None:
        """Transmit *packet* using the settings in *config*.

        Raises:
            SendError: If the underlying transport fails.
        """
        ...


# ---------------------------------------------------------------------------
# Concrete Implementation
# ---------------------------------------------------------------------------

class UDPSender:
    """Sends a MagicPacket via a UDP broadcast socket."""

    def send(self, packet: MagicPacket, config: WoLConfig) -> None:
        """Open a broadcast UDP socket, send payload, close it.

        Args:
            packet: The pre-built magic packet.
            config: Connection parameters (address, port).

        Raises:
            SendError: Wraps any socket-level OSError.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(packet.payload, (config.broadcast_address, config.port))
        except OSError as exc:
            raise SendError(f"Failed to send WoL packet: {exc}") from exc


# ---------------------------------------------------------------------------
# Helper: MAC string → bytes
# ---------------------------------------------------------------------------

def parse_mac(mac: MacAddress) -> RawMacBytes:
    """Convert a MAC address string to raw bytes.

    Args:
        mac: Normalized "AA:BB:CC:DD:EE:FF" format (as produced by WoLConfig).

    Returns:
        Exactly 6 bytes.

    Raises:
        InvalidMACError: If the string is malformed.
    """
    try:
        raw = bytes.fromhex(mac.replace(":", ""))
    except ValueError as exc:
        raise InvalidMACError(f"Cannot parse MAC address {mac!r}: {exc}") from exc

    if len(raw) != MAC_BYTE_LENGTH:
        raise InvalidMACError(
            f"MAC address must be {MAC_BYTE_LENGTH} bytes, got {len(raw)}"
        )
    return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def wake(
    mac: MacAddress,
    *,
    broadcast: str = BroadcastAddress.GLOBAL,
    port: WoLPort = WoLPort.DISCARD,
    sender: PacketSender | None = None,
) -> None:
    """Send a WoL magic packet to wake the machine with the given MAC.

    Args:
        mac:       Target MAC address string (any standard separator format).
        broadcast: Destination broadcast address.
        port:      UDP port number.
        sender:    Transport implementation (defaults to UDPSender).
                   Inject a mock here in tests.

    Raises:
        InvalidMACError: If *mac* is malformed.
        SendError:       If the packet cannot be transmitted.

    Example:
        >>> wake("AA:BB:CC:DD:EE:FF")
    """
    config    = WoLConfig(mac_address=mac, broadcast_address=broadcast, port=port)
    mac_bytes = parse_mac(config.mac_address)
    packet    = MagicPacket(mac_bytes=mac_bytes)
    transport = sender or UDPSender()
    transport.send(packet, config)

