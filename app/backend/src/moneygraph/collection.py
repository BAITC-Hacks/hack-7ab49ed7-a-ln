from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Collection:
    max_depth: int
    observation_start: str
    observation_end: str
    min_transfer_kzt: float
    direction: str = "outgoing"

    @property
    def expanded_depth(self) -> int:
        # The crawl expanded every hop except the last one, so only those nodes have complete outflows.
        return self.max_depth - 1

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(self.observation_start)

    @property
    def end(self) -> pd.Timestamp:
        return pd.Timestamp(self.observation_end)

    @property
    def observation_days(self) -> int:
        return (self.end - self.start).days

    @property
    def small_amount_ceiling(self) -> float:
        return 2 * self.min_transfer_kzt

    def as_dict(self) -> dict:
        return {
            "max_depth": self.max_depth,
            "observation_start": self.observation_start,
            "observation_end": self.observation_end,
            "min_transfer_kzt": self.min_transfer_kzt,
            "collection_direction": self.direction,
        }
