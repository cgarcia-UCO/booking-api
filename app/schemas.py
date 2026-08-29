"""
app/schemas.py
----------------
Pydantic models: read-only catalog entities, plus the request/response
schemas for bookings and availability checks.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import config

HOUR_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

BookingType = Literal["hotel_room", "restaurant_table", "activity"]
BookingStatus = Literal["pending", "confirmed", "cancelled", "completed", "no_show"]


# ---------------------------------------------------------------------------
# Generic pagination wrapper used by every list endpoint
# ---------------------------------------------------------------------------
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    total: int = Field(description="Total number of items matching the filters")
    count: int = Field(description="Number of items in this page")
    limit: int
    offset: int
    items: List[T]


# ---------------------------------------------------------------------------
# Catalog entities (read-only)
# ---------------------------------------------------------------------------
class City(BaseModel):
    city_id: int
    name: str


class Hotel(BaseModel):
    hotel_id: int
    name: str
    description: str
    category: int
    type: str
    city: str
    check_in_time: str
    check_out_time: str
    reception_24h: bool
    services: List[str]
    pet_friendly: bool
    accessible: bool
    rating: float
    review_count: int
    price_range: str


class RoomType(BaseModel):
    room_type_id: int
    hotel_id: int
    name: str
    description: str
    max_adults: int
    max_children: int
    bed_configuration: str
    size_m2: int
    bathroom_type: str
    services: List[str]
    accessible: bool
    base_price_per_night: float
    breakfast_included: bool
    cancellation_policy: str


class Room(BaseModel):
    room_id: int
    hotel_id: int
    room_type_id: int
    room_number: str
    floor: int
    status: str
    notes: str


class Restaurant(BaseModel):
    restaurant_id: int
    name: str
    description: str
    cuisine_types: List[str]
    city: str
    opening_hours: str
    price_range: str
    rating: float
    review_count: int
    services: List[str]
    accessible: bool
    pet_friendly: bool
    dress_code: str
    max_capacity: int


class RestaurantTable(BaseModel):
    table_id: int
    restaurant_id: int
    table_number: int
    capacity: int
    location: str
    accessible: bool
    status: str


class Dish(BaseModel):
    dish_id: int
    restaurant_id: int
    name: str
    description: str
    category: str
    price: float
    currency: str
    ingredients: List[str]
    allergens: List[str]
    dietary_tags: List[str]
    spicy_level: int
    calories: int
    available: bool


class Activity(BaseModel):
    activity_id: int
    name: str
    description: str
    activity_type: str
    category: str
    city: str
    opening_hours: str
    duration_minutes: int
    min_age: int
    max_age: Optional[int] = None
    accessible: bool
    indoor_outdoor: str
    max_capacity: int
    rating: float
    review_count: int
    services: List[str]
    price: float


class Customer(BaseModel):
    customer_id: int
    first_name: str
    last_name: str
    date_of_birth: date


class Booking(BaseModel):
    booking_id: int
    booking_reference: str
    customer_id: int
    booking_type: BookingType
    status: BookingStatus
    hotel_id: Optional[int] = None
    room_id: Optional[int] = None
    restaurant_id: Optional[int] = None
    table_id: Optional[int] = None
    activity_id: Optional[int] = None
    init_day: date
    end_day: date
    hour: Optional[str] = None
    num_people: int
    total_price: float
    currency: str
    created_at: datetime
    created_by_session: str = Field(
        description=f"Session key (X-Session-Id) that created the booking, or "
                    f"'{config.SEED_SESSION}' for bookings that ship with the seed dataset."
    )


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
class RoomAvailability(BaseModel):
    room_id: int
    hotel_id: int
    room_type_id: int
    room_number: str
    init_day: date
    end_day: date
    available: bool
    conflicting_booking_ids: List[int] = []


class TableAvailability(BaseModel):
    table_id: int
    restaurant_id: int
    table_number: int
    capacity: int
    day: date
    hour: str
    available: bool
    conflicting_booking_ids: List[int] = []


class ActivityAvailability(BaseModel):
    activity_id: int
    day: date
    max_capacity: int
    booked_count: int
    remaining_capacity: int
    requested_people: Optional[int] = None
    available: bool


# ---------------------------------------------------------------------------
# Booking creation
# ---------------------------------------------------------------------------
class BookingCreateRequest(BaseModel):
    customer_id: int
    booking_type: BookingType
    room_id: Optional[int] = Field(
        default=None, description="Required (and only used) when booking_type = hotel_room"
    )
    table_id: Optional[int] = Field(
        default=None, description="Required (and only used) when booking_type = restaurant_table"
    )
    activity_id: Optional[int] = Field(
        default=None, description="Required (and only used) when booking_type = activity"
    )
    init_day: date = Field(description="Check-in day / reservation day / visit day")
    end_day: Optional[date] = Field(
        default=None,
        description="Check-out day for hotel_room bookings (must be after init_day). "
                    "Ignored for restaurant_table/activity, where it always equals init_day.",
    )
    hour: Optional[str] = Field(
        default=None, description="Required for restaurant_table, format HH:MM (24h)."
    )
    num_people: int = Field(ge=1, le=50)

    @model_validator(mode="after")
    def _validate_consistency(self) -> "BookingCreateRequest":
        ids_by_type = {
            "hotel_room": self.room_id,
            "restaurant_table": self.table_id,
            "activity": self.activity_id,
        }
        expected_id = ids_by_type[self.booking_type]
        if expected_id is None:
            required_field = {"hotel_room": "room_id", "restaurant_table": "table_id",
                               "activity": "activity_id"}[self.booking_type]
            raise ValueError(f"'{required_field}' is required when booking_type='{self.booking_type}'")

        other_fields = {k: v for k, v in ids_by_type.items() if k != self.booking_type}
        provided_others = [k for k, v in other_fields.items() if v is not None]
        if provided_others:
            raise ValueError(
                f"Only the identifier matching booking_type='{self.booking_type}' may be "
                f"provided; got unexpected value(s) for: {', '.join(provided_others)}"
            )

        if self.booking_type == "hotel_room":
            if self.end_day is None:
                raise ValueError("'end_day' (check-out date) is required for booking_type='hotel_room'")
            if self.end_day <= self.init_day:
                raise ValueError("'end_day' must be strictly after 'init_day'")
            if self.hour is not None:
                raise ValueError("'hour' must not be set for booking_type='hotel_room'")
        else:
            if self.end_day is not None and self.end_day != self.init_day:
                raise ValueError(
                    "'end_day' must equal 'init_day' (or be omitted) for "
                    "restaurant_table/activity bookings"
                )
            self.end_day = self.init_day

        if self.booking_type == "restaurant_table":
            if not self.hour or not HOUR_RE.match(self.hour):
                raise ValueError("'hour' is required for booking_type='restaurant_table' and must "
                                  "match 24h format HH:MM, e.g. '20:30'")
        elif self.booking_type == "activity" and self.hour is not None:
            raise ValueError("'hour' must not be set for booking_type='activity'")

        if self.init_day > config.MAX_BOOKING_DATE or self.end_day > config.MAX_BOOKING_DATE:
            raise ValueError(f"Bookings are not accepted for dates after {config.MAX_BOOKING_DATE.isoformat()}")

        if self.init_day < date.today():
            raise ValueError("'init_day' cannot be in the past")

        return self


class BookingCreateResponse(BaseModel):
    success: bool
    message: str
    booking: Optional[Booking] = None


# ---------------------------------------------------------------------------
# LLM chat endpoint
# ---------------------------------------------------------------------------
class LLMMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=config.LLM_MAX_MESSAGE_CHARS)


class LLMChatRequest(BaseModel):
    """
    The client supplies the *entire* messages list — typically a system
    prompt followed by the running conversation history and the latest
    user turn — exactly like the OpenAI Chat Completions `messages`
    parameter. This is intentional for the workshop: attendees are meant
    to design their own system prompts and history-management strategy.

    Model, max output tokens, temperature, tools, etc. are still fixed
    server-side (see app/config.py and app/routers/llm.py) and are not
    exposed here. Any unexpected field in the request is rejected outright
    (422) rather than silently ignored.
    """
    model_config = ConfigDict(extra="forbid")

    messages: List[LLMMessage] = Field(
        min_length=1,
        max_length=config.LLM_MAX_MESSAGES,
        description=(
            "Full list of messages to send to the model, in order (e.g. a system "
            "message followed by prior user/assistant turns and the latest user "
            f"message). Max {config.LLM_MAX_MESSAGES} messages; you are responsible "
            "for deciding how much history to keep/truncate."
        ),
    )

    @model_validator(mode="after")
    def _validate_total_size(self) -> "LLMChatRequest":
        total_chars = sum(len(m.content) for m in self.messages)
        if total_chars > config.LLM_MAX_TOTAL_CHARS:
            raise ValueError(
                f"Combined length of all messages ({total_chars} chars) exceeds the "
                f"{config.LLM_MAX_TOTAL_CHARS}-character limit for a single call."
            )
        return self


class LLMChatResponse(BaseModel):
    reply: str
    model: str
    usage: Optional[dict] = None
