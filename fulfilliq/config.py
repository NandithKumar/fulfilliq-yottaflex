"""Central configuration and deterministic scenario constants."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SAMPLE_DIR = DATA_DIR / "sample"
GENERATED_DIR = DATA_DIR / "generated"
WEB_DIR = ROOT / "web"
SEED_DEFAULT = 20261022
SNAPSHOT_AT = datetime.fromisoformat("2026-11-01T12:00:00+05:30")
ENGINE_VERSION = "1.0.0"

@dataclass(frozen=True)
class GenerationConfig:
    orders: int = 50_000
    seed: int = SEED_DEFAULT
    nodes: int = 20
    carriers: int = 10
    skus: int = 500
    tracking_events: int | None = None
    output: Path = GENERATED_DIR
    snapshot_at: datetime = SNAPSHOT_AT

    @property
    def target_events(self) -> int:
        return self.tracking_events if self.tracking_events is not None else self.orders * 2
