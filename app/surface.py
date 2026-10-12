"""The one surface classification Loam uses, from OSM tags only.

Shared by GraphHopper paths (via their road_class/surface/track_type details), the trail
graph, map-matching and the UI. Categories: singletrack | doubletrack | gravel | paved,
plus flags. Never from a way's name, and never "doubletrack" just because a tag is missing:
an untagged surface takes the default of its highway class (road -> paved, path ->
singletrack, track -> doubletrack).
"""
from dataclasses import dataclass
from typing import Mapping, Optional

CATEGORIES = ("singletrack", "doubletrack", "gravel", "paved")

PAVED_SURFACES = {"asphalt", "paved", "concrete", "chipseal", "paving_stones", "concrete:plates",
                  "concrete:lanes", "sett", "cobblestone", "metal", "wood"}
GRAVEL_SURFACES = {"gravel", "fine_gravel", "compacted", "crushed_limestone", "pebblestone"}
UNPAVED_SURFACES = {"unpaved", "dirt", "earth", "ground", "grass", "mud", "sand", "rock", "rocks",
                    "roots", "woodchips", "gravel", "fine_gravel", "compacted", "pebblestone",
                    "crushed_limestone", "grass_paver", "stone"}
# Road classes: paved unless the class is `unclassified` with an unpaved surface.
ROAD_CLASSES = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
                "secondary", "secondary_link", "tertiary", "tertiary_link", "residential",
                "service", "living_street", "pedestrian", "road", "busway"}
PATH_CLASSES = {"path", "bridleway", "footway", "steps"}
# GraphHopper reports untagged values as "missing" or "other".
UNKNOWN_VALUES = {"", "missing", "other", "unknown", "none"}


@dataclass(frozen=True)
class SurfaceClass:
    category: str
    snowmobile: bool = False
    informal: bool = False
    steps: bool = False


def _norm(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    return "" if v in UNKNOWN_VALUES else v


def classify_surface(tags: Mapping[str, Optional[str]]) -> SurfaceClass:
    """Classifies an OSM way (or a GraphHopper path span) by its tags."""
    highway = _norm(tags.get("highway") or tags.get("road_class"))
    surface = _norm(tags.get("surface"))
    tracktype = _norm(tags.get("tracktype") or tags.get("track_type"))
    snowmobile = bool(_norm(tags.get("snowmobile")) not in ("", "no")) or _norm(tags.get("route")) == "snowmobile"
    flags = dict(snowmobile=snowmobile, informal=_norm(tags.get("informal")) == "yes", steps=highway == "steps")

    if surface in PAVED_SURFACES:
        return SurfaceClass("paved", **flags)
    if highway in ROAD_CLASSES:
        return SurfaceClass("paved", **flags)
    if highway == "unclassified":
        return SurfaceClass("gravel" if surface in UNPAVED_SURFACES else "paved", **flags)
    if highway == "track":
        if tracktype == "grade1" or surface in GRAVEL_SURFACES:
            return SurfaceClass("gravel", **flags)
        return SurfaceClass("doubletrack", **flags)
    if surface in GRAVEL_SURFACES:
        return SurfaceClass("gravel", **flags)
    if highway in PATH_CLASSES:
        return SurfaceClass("singletrack", **flags)
    if highway == "cycleway":
        # A cycleway with a natural surface rides like a trail; untagged ones are bike paths.
        return SurfaceClass("singletrack" if surface in UNPAVED_SURFACES else "paved", **flags)
    if not highway and snowmobile:
        return SurfaceClass("doubletrack", **flags)
    if surface in UNPAVED_SURFACES:
        return SurfaceClass("singletrack", **flags)
    # Nothing known about the way: count it as road, the conservative choice for the road cap.
    return SurfaceClass("paved", **flags)


def surface_category(tags: Mapping[str, Optional[str]]) -> str:
    return classify_surface(tags).category
