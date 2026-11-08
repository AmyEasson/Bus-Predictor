from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Band = Literal["on_time", "minor", "moderate", "severe"]
FactorKey = Literal["weather", "time_of_day", "events"]
ColourBy = Literal["overall", "weather", "time_of_day", "events"]
RiskLevel = Literal["low", "medium", "high"]
DayType = Literal["weekday", "weekend"]


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
    delayed_over_5min: int  # buses more than 5 min late during the hour, on a typical day
    avg_delay_minutes: float
    day_type: DayType | None = None
    buses: int | None = None  # buses seen during the hour, on a typical day


class Vehicle(BaseModel):
    id: str
    line: str
    lat: float
    lon: float
    delay_minutes: float
    band: Band


class Weather(BaseModel):
    summary: str
    temp_c: float | None = None  # None: no live weather feed
    wind_kmh: float | None = None


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
    lines: str | None = None  # comma-separated route numbers using the stretch
    observations: int | None = None  # bus passes behind the numbers


class Hex(BaseModel):
    id: str  # axial "q,r"
    path: list[list[float]]  # 6 corners, [[lat, lon], ...]
    delay_minutes: float
    band: Band
    breakdown: dict[str, float]
    observations: int  # bus passes behind the number
    worst_stretch: str
    worst_stretch_minutes: float
    lines: str


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
    day_type: DayType | None = None
    data_from: str | None = None  # archive window the numbers come from
    data_to: str | None = None
    data_days: int | None = None
    conditions: Conditions
    factors: list[Factor]
    hourly: list[HourBar]
    hex_m: int | None = None  # hexagon width in metres
    hexes: list[Hex] = []
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