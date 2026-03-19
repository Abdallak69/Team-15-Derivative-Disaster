"""Ticker polling service for building the local historical database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from bot.api.roostoo_client import RoostooClient

from .ohlcv_store import OhlcvStore
from .ohlcv_store import TickerSnapshot

LOGGER = logging.getLogger("tradingbot.system")


@dataclass(frozen=True, slots=True)
class PollResult:
    """Summary of a ticker polling cycle."""

    polled_at: str
    snapshot_count: int
    stored_snapshot_count: int
    tracked_pair_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the polling result."""
        return {
            "polled_at": self.polled_at,
            "snapshot_count": self.snapshot_count,
            "stored_snapshot_count": self.stored_snapshot_count,
            "tracked_pair_count": self.tracked_pair_count,
        }


@dataclass(slots=True)
class TickerPoller:
    """Fetch and persist ticker snapshots for the tracked universe."""

    client: RoostooClient
    store: OhlcvStore
    pairs: tuple[str, ...] = ()

    def poll(self) -> PollResult:
        """Fetch tickers from Roostoo and persist them into sqlite."""
        tracked_pairs = set(self.pairs)
        polled_at = datetime.now(timezone.utc)
        raw_tickers = self.client.get_ticker()

        snapshots: list[TickerSnapshot] = []
        malformed_row_count = 0
        for index, row in enumerate(raw_tickers):
            try:
                snapshot = TickerSnapshot.from_api_payload(row, polled_at=polled_at)
            except ValueError:
                malformed_row_count += 1
                if malformed_row_count <= 3:
                    LOGGER.warning(
                        "Skipping malformed ticker row index=%s keys=%s",
                        index,
                        sorted(row) if isinstance(row, dict) else type(row).__name__,
                    )
                continue
            if tracked_pairs and snapshot.pair not in tracked_pairs:
                continue
            snapshots.append(snapshot)

        if malformed_row_count:
            LOGGER.warning(
                "Dropped malformed ticker rows count=%s tracked_pair_count=%s",
                malformed_row_count,
                len(tracked_pairs) or len(snapshots),
            )

        stored_snapshot_count = self.store.upsert_ticker_batch(snapshots)
        return PollResult(
            polled_at=polled_at.isoformat(),
            snapshot_count=len(snapshots),
            stored_snapshot_count=stored_snapshot_count,
            tracked_pair_count=len(tracked_pairs) or len(snapshots),
        )
