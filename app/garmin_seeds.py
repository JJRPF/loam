"""
Loop seeds from riders' own imported, map-matched rides.

There are no hand-made seeds. Seeds come only from the `seed_loops` table, which the
Garmin export import fills (Round 7 phase 5); until rides are imported the catalog is empty.
"""
from dataclasses import dataclass
from typing import List


@dataclass
class SeedLoop:
    id: str
    sport: str
    distance_miles: float
    way_ids: List[int]
    segment_ids: List[int]
    retrace: float


class SeedLoopCatalog:
    def get_matching_seeds(
        self,
        lat: float,
        lon: float,
        target_miles: float,
        sport: str = "mtb",
        radius_miles: float = 1.5,
    ) -> List[SeedLoop]:
        """Seed loops near the start for this sport. Empty until rides are imported."""
        return []


seed_catalog = SeedLoopCatalog()
