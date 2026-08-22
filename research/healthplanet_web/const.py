"""Constants confirmed by the authorized 2026-08-22 website research."""

from __future__ import annotations

from dataclasses import dataclass

SOURCE = "healthplanet_web_graph"
GRAPH_PATH = "/graph/graph.json"
JAPAN_TIMEZONE = "Asia/Tokyo"


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    unit: str | None


METRICS: dict[int, MetricDefinition] = {
    1: MetricDefinition("weight", "kg"),
    2: MetricDefinition("body_fat_percentage", "%"),
    3: MetricDefinition("body_fat_mass", "kg"),
    4: MetricDefinition("visceral_fat_level", None),
    5: MetricDefinition("basal_metabolic_rate", "kcal"),
    6: MetricDefinition("muscle_mass", "kg"),
    7: MetricDefinition("estimated_bone_mass", "kg"),
    14: MetricDefinition("metabolic_age", "才"),
    22: MetricDefinition("body_water_percentage", "%"),
    23: MetricDefinition("muscle_quality_score", None),
}

KNOWN_SCHEMA_KEYS = {
    "barMargin",
    "barWidth",
    "code",
    "formatString",
    "from_date",
    "markerSize",
    "numberTicks",
    "synthetic",
    "tickInset",
    "tickInterval",
    "to_date",
    "value1",
    "value1_formatString",
    "value1_max",
    "value1_min",
    "value1_name",
    "value1_unit",
}
