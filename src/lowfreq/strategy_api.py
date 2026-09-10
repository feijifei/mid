from typing import Protocol, runtime_checkable

from lowfreq.domain import StrategyContext, StrategyMetadata, StrategyResult


@runtime_checkable
class Strategy(Protocol):
    """Trusted plugin interface.

    Invariants:
    - ``context.bars`` contains no rows later than ``context.as_of``.
    - Returned weights are finite, non-negative, and sum to at most 1.
    - A strategy returns targets only; it never performs I/O or sends orders.
    """

    @property
    def metadata(self) -> StrategyMetadata: ...

    def generate(self, context: StrategyContext) -> StrategyResult: ...
