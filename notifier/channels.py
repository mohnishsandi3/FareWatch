"""Delivery channels for the notifier.

A minimal pluggable interface. The MVP ships ``LogChannel`` (writes the alert to
the log) so the pipeline is demoable without an email provider configured. Swap
in a real transactional-email channel later by implementing ``Channel.send``.
"""
from __future__ import annotations

import logging
from typing import Protocol

from shared.models import NotificationMessage

log = logging.getLogger(__name__)


class Channel(Protocol):
    name: str

    def send(self, msg: NotificationMessage) -> None:
        """Deliver the alert. Raise on failure so the notifier leaves the entry
        unacked for retry."""
        ...


class LogChannel:
    """Stand-in 'email' channel: logs what would be sent."""

    name = "email"

    def send(self, msg: NotificationMessage) -> None:
        route = f"{msg.origin}→{msg.destination}"
        when = msg.depart_date.isoformat() if msg.depart_date else "flexible"
        log.info(
            "[EMAIL -> %s] Deal on %s: $%.0f (%s, score %.2f) depart %s",
            msg.email, route, msg.price, msg.confidence, msg.deal_score, when,
        )


# Channel registry, keyed by the notifications.channel value.
_CHANNELS: dict[str, Channel] = {LogChannel.name: LogChannel()}


def get_channel(name: str) -> Channel:
    try:
        return _CHANNELS[name]
    except KeyError:
        raise ValueError(f"unknown notification channel: {name}")
