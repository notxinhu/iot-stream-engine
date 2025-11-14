"""Telemetry schemas for the IoT Stream Engine."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ReadingResponse(BaseModel):
    """Response model for sensor reading data."""

    model_config = ConfigDict(from_attributes=True)
    device_id: str
    reading_value: float
    timestamp: str
    unit: str


class PollingRequest(BaseModel):
    """Polling request model."""

    model_config = ConfigDict(from_attributes=True)
    device_ids: List[str]
    interval: int


class PollingJobConfig(BaseModel):
    """Polling job configuration model."""

    model_config = ConfigDict(from_attributes=True)
    device_ids: List[str]
    interval: int
    job_id: Optional[str] = None
    status: Optional[str] = None


class PollingResponse(BaseModel):
    """Polling response model."""

    model_config = ConfigDict(from_attributes=True)
    job_id: str
    status: str
    config: PollingRequest


class RollingAverageResponse(BaseModel):
    """Response model for rolling average calculations."""

    model_config = ConfigDict(from_attributes=True)
    device_id: str
    average_value: float
    timestamp: datetime
    window_size: int


class ErrorResponse(BaseModel):
    """Response model for error messages."""

    model_config = ConfigDict(from_attributes=True)
    detail: str


class PollingJobList(BaseModel):
    """List of polling jobs."""

    model_config = ConfigDict(from_attributes=True)
    jobs: List[PollingResponse]


class DeleteAllResponse(BaseModel):
    """Response model for delete all operation."""

    model_config = ConfigDict(from_attributes=True)
    message: str
    deleted_count: int


class SensorReadingBase(BaseModel):
    """Base schema for sensor readings."""

    device_id: str = Field(..., min_length=1, max_length=50, description="IoT Device ID")
    reading_value: float = Field(..., description="Sensor reading value")
    reading_type: str = Field(..., description="Type of reading (e.g. temperature, humidity)")
    unit: str = Field(..., description="Unit of measurement (e.g. Celsius, Volts)")
    battery_level: Optional[float] = Field(None, ge=0, le=100, description="Device battery level percentage")
    raw_data: Optional[str] = Field(None, description="Raw sensor payload")


class SensorReadingCreate(SensorReadingBase):
    """Schema for creating a new sensor reading."""


class SensorReadingUpdate(BaseModel):
    """Schema for updating a sensor reading."""

    device_id: Optional[str] = Field(None, description="IoT Device ID")
    reading_value: Optional[float] = Field(None, description="Sensor reading value")
    reading_type: Optional[str] = Field(None, description="Type of reading")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    battery_level: Optional[float] = Field(None, ge=0, le=100, description="Device battery level")
    raw_data: Optional[str] = Field(None, description="Raw sensor payload")


class SensorReadingInDB(SensorReadingBase):
    """Schema for sensor reading in database."""

    id: int = Field(..., description="Reading ID")
    timestamp: datetime = Field(..., description="Timestamp of the reading")

    class Config:
        """Pydantic model configuration."""
        orm_mode = True


class RawTelemetryBase(BaseModel):
    """Base schema for raw telemetry."""

    device_id: str = Field(..., description="IoT Device ID")
    raw_data: str = Field(..., description="Raw telemetry payload")
    source: str = Field(..., description="Source system or gateway")


class RawTelemetryCreate(RawTelemetryBase):
    """Schema for creating raw telemetry."""


class RawTelemetryInDB(RawTelemetryBase):
    """Schema for raw telemetry in database."""

    id: int = Field(..., description="Raw telemetry ID")
    timestamp: datetime = Field(..., description="Timestamp of the data")
    processed: int = Field(..., description="Processing status (0=pending, 1=processed)")

    class Config:
        """Pydantic model configuration."""
        orm_mode = True


class ProcessedReadingBase(BaseModel):
    """Base schema for processed reading."""

    device_id: str = Field(..., description="IoT Device ID")
    reading_value: float = Field(..., description="Processed value")
    raw_telemetry_id: int = Field(..., description="Raw telemetry ID")


class ProcessedReadingCreate(ProcessedReadingBase):
    """Schema for creating processed reading."""


class ProcessedReadingInDB(ProcessedReadingBase):
    """Schema for processed reading in database."""

    id: int = Field(..., description="Processed reading ID")
    timestamp: datetime = Field(..., description="Timestamp of the data")

    class Config:
        """Pydantic model configuration."""
        orm_mode = True


class DevicesResponse(BaseModel):
    """Response model for devices endpoint."""

    device_ids: List[str]
