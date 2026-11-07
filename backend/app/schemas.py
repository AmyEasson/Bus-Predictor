from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Band = Literal["on_time", "minor", "moderate", "severe"]
FactorKey = Literal["weather", "time_of_day", "events"]
ColourBy = Literal["overall", "weather", "time_of_day", "events"]
RiskLevel = Literal["low", "medium", "high"]


class Stop(BaseModel):
    id: str
    name: str
    lat: float
    lon: float


class Status(BaseModel):
    live: bool
    region: str
    updated_at: datetime
    signals: list[str]


class NetworkSummary(BaseModel):
    as_of: datetime
    pct_on_time: int
    delayed_over_5min: int
    avg_delay_minutes: float


class Vehicle(BaseModel):
    id: str
    line: str
    lat: float
    lon: float
    delay_minutes: float
    band: Band


class Weather(BaseModel):
    summary: str
    temp_c: float
    wind_kmh: float


class EventInfo(BaseModel):
    id: str
    name: str
    kind: str
    time_label: str
    lat: float
    lon: float


class Conditions(BaseModel):
    weather: Weather
    events: list[EventInfo]


class Factor(BaseModel):
    key: FactorKey
    label: str
    minutes: float
    description: str


class Segment(BaseModel):
    id: str
    name: str
    from_stop_id: str
    to_stop_id: str
    path: list[list[float]]  # [[lat, lon], ...]
    delay_minutes: float
    band: Band
    breakdown: dict[str, float]


class Callout(BaseModel):
    label: str
    detail: str
    lat: float
    lon: float
    tone: Literal["good", "bad", "neutral"]


class HourBar(BaseModel):
    hour: int
    avg_delay_minutes: float
    band: Band


class WorstSegment(BaseModel):
    segment_id: str
    name: str
    delay_minutes: float


class LegendItem(BaseModel):
    band: Band
    label: str


class DelayMap(BaseModel):
    as_of: datetime
    hour: int
    colour_by: ColourBy
    conditions: Conditions
    factors: list[Factor]
    hourly: list[HourBar]
    segments: list[Segment]
    worst: list[WorstSegment]
    legend: list[LegendItem]


class RouteRequest(BaseModel):
    origin_id: str
    destination_id: str
    mode: Literal["depart", "arrive"] = "depart"
    time: datetime | None = None  # None means now


class RouteOption(BaseModel):
    id: str
    label: str
    rank: int
    depart_at: datetime
    arrive_at: datetime
    timetable_minutes: float
    predicted_delay_minutes: float
    predicted_minutes: float
    risk_level: RiskLevel
    risk_pct: int
    lines: list[str]
    walk_minutes: int
    explanation: str
    factors: list[Factor]
    path: list[list[float]]
    segments: list[Segment]
    callouts: list[Callout]


class ModelInfo(BaseModel):
    confidence: Literal["low", "medium", "high"]
    data_basis: str


class RouteResponse(BaseModel):
    origin: Stop
    destination: Stop
    mode: Literal["depart", "arrive"]
    time: datetime
    conditions: Conditions
    routes: list[RouteOption]
    model: ModelInfo


class TypicalDelay(BaseModel):
    from_id: str
    to_id: str
    hour: int
    typical_delay_minutes: float