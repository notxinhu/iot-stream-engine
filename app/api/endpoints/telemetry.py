"""Telemetry endpoints for the IoT Stream Engine."""

import asyncio
import logging
from datetime import datetime
from threading import Lock
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from prometheus_client import Counter, Gauge
from sqlalchemy.orm import Session
from sqlalchemy.exc import DataError, IntegrityError

from app.core.auth import (
    require_admin_permission,
    require_read_permission,
    require_write_permission,
)
from app.db.session import get_db
from app.schemas.telemetry import (
    SensorReadingCreate,
    SensorReadingInDB,
    SensorReadingUpdate,
    DevicesResponse,
    PollingJobConfig,
)
from app.services.iot_service import IoTService
from app.services.kafka_service import KafkaService

router = APIRouter()

# In-memory polling job store and lock
polling_jobs = {}
job_counter = [0]
jobs_lock = Lock()

# Background task management
background_tasks = {}

# Prometheus metrics
telemetry_points_total = Counter(
    "telemetry_points_total", "Total number of telemetry data points"
)
devices_tracked = Gauge("devices_tracked", "Number of devices being tracked")
polling_jobs_active = Gauge("polling_jobs_active", "Number of active polling jobs")

logger = logging.getLogger(__name__)


async def execute_polling_job(job_id: str, device_ids: List[str], interval: int):
    """Execute a polling job to fetch sensor data."""
    logger.info(f"Starting polling job {job_id} for devices {device_ids}")
    
    try:
        # Update job status to running
        with jobs_lock:
            if job_id in polling_jobs:
                polling_jobs[job_id]["status"] = "running"
                polling_jobs[job_id]["last_run"] = datetime.now().isoformat()
        
        # Simulate fetching data for each device
        for device_id in device_ids:
            # Simulate API call delay
            await asyncio.sleep(0.1)
            
            # Fetch mock data via service (or just simulate here)
            # In real implementation, this would call external APIs or Gateways
            import random
            mock_val = 20 + random.uniform(-10, 10)
            
            logger.info(f"Job {job_id}: Fetched reading for {device_id}: {mock_val:.2f}")
            
        # Update job status to completed
        with jobs_lock:
            if job_id in polling_jobs:
                polling_jobs[job_id]["status"] = "completed"
                polling_jobs[job_id]["last_completed"] = datetime.now().isoformat()
                polling_jobs[job_id]["data_points_fetched"] = len(device_ids)
        
        logger.info(f"Completed polling job {job_id}")
        
    except Exception as e:
        logger.error(f"Error in polling job {job_id}: {e}")
        with jobs_lock:
            if job_id in polling_jobs:
                polling_jobs[job_id]["status"] = "failed"
                polling_jobs[job_id]["error"] = str(e)


async def start_polling_job(job_id: str, device_ids: List[str], interval: int):
    """Start a polling job that runs periodically."""
    while True:
        try:
            # Check if job still exists
            with jobs_lock:
                if job_id not in polling_jobs:
                    logger.info(f"Job {job_id} was deleted, stopping execution")
                    break
                
                if polling_jobs[job_id]["status"] == "deleted":
                    logger.info(f"Job {job_id} was marked for deletion, stopping execution")
                    break
            
            # Execute the job
            await execute_polling_job(job_id, device_ids, interval)
            
            # Wait for the next interval
            await asyncio.sleep(interval)
            
        except asyncio.CancelledError:
            logger.info(f"Job {job_id} was cancelled")
            break
        except Exception as e:
            logger.error(f"Unexpected error in polling job {job_id}: {e}")
            await asyncio.sleep(interval)  # Wait before retrying


@router.get("/", response_model=List[SensorReadingInDB])
def get_readings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    device_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_read_permission),
) -> List[SensorReadingInDB]:
    """
    Get sensor readings with optional filtering.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        device_id: Filter by device ID
        db: Database session
        current_user: Authenticated user

    Returns:
        List of sensor reading records
    """
    try:
        if device_id:
            return IoTService.get_readings_by_device(db, device_id, skip, limit)
        return IoTService.get_readings(db, skip, limit)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving readings: {str(e)}",
        )


@router.post("/ingest", status_code=202)
async def ingest_reading(
    reading_data: SensorReadingCreate,
    current_user: str = Depends(require_write_permission),
) -> dict:
    """
    Ingest new sensor reading (Event-Driven).
    
    This endpoint pushes the data to Kafka and returns immediately.
    Data persistence is handled by the background worker.
    """
    try:
        # Create Kafka service
        kafka_service = KafkaService()
        
        # Produce message to Kafka
        success = await kafka_service.produce_message(
            topic="iot_stream_v1",
            key=reading_data.device_id,
            value=reading_data.model_dump()
        )
        
        # Close producer connection (in a real app, use a dependency/singleton)
        await kafka_service.close()

        if not success:
             raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

        # Increment metrics
        telemetry_points_total.inc()
        
        return {
            "message": "Reading queued for processing",
            "data": reading_data.model_dump()
        }
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error ingesting reading: {str(e)}",
        )


# Polling job endpoints (require admin permissions)
@router.post("/poll", status_code=201)
async def create_polling_job(
    config: PollingJobConfig = Body(...),
    current_user: str = Depends(require_admin_permission),
) -> dict:
    """
    Create a new polling job for sensor data collection.
    """
    with jobs_lock:
        job_id = f"poll_{job_counter[0] + 1}"
        job_counter[0] += 1

        polling_jobs[job_id] = {
            "id": job_id,
            "config": config.model_dump(),
            "status": "created",
            "created_at": datetime.now().isoformat(),
        }

        polling_jobs_active.set(len(polling_jobs))

    # Start the background task
    task = asyncio.create_task(
        start_polling_job(job_id, config.device_ids, config.interval)
    )
    background_tasks[job_id] = task

    logger.info(f"Started polling job {job_id} for devices {config.device_ids} with interval {config.interval}s")

    return {
        "job_id": job_id,
        "status": "created",
        "config": {
            "device_ids": config.device_ids,
            "interval": config.interval
        },
        "message": "Polling job started successfully"
    }


@router.get("/poll")
async def list_polling_jobs(
    current_user: str = Depends(require_admin_permission),
) -> List[dict]:
    """List all polling jobs."""
    return list(polling_jobs.values())


@router.get("/poll/{job_id}")
async def get_polling_job(
    job_id: str, current_user: str = Depends(require_admin_permission)
) -> dict:
    """Get polling job status."""
    if job_id not in polling_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = polling_jobs[job_id].copy()
    return job


@router.delete("/poll/{job_id}")
async def delete_polling_job(
    job_id: str, current_user: str = Depends(require_admin_permission)
) -> dict:
    """Delete a polling job."""
    with jobs_lock:
        if job_id not in polling_jobs:
            raise HTTPException(status_code=404, detail="Job not found")

        # Mark job for deletion
        polling_jobs[job_id]["status"] = "deleted"
        
        # Cancel the background task
        if job_id in background_tasks:
            background_tasks[job_id].cancel()
            del background_tasks[job_id]

        # Remove from polling jobs
        del polling_jobs[job_id]
        polling_jobs_active.set(len(polling_jobs))

    logger.info(f"Deleted polling job {job_id}")

    return {"message": "Job deleted successfully"}


@router.post("/delete-all-polling-jobs")
async def delete_all_polling_jobs(
    current_user: str = Depends(require_admin_permission),
) -> dict:
    """Delete all polling jobs."""
    with jobs_lock:
        # Cancel all background tasks
        for job_id, task in background_tasks.items():
            task.cancel()
        background_tasks.clear()
        
        # Clear all polling jobs
        polling_jobs.clear()
        polling_jobs_active.set(0)

    logger.info("Deleted all polling jobs")

    return {"message": "All jobs deleted successfully"}


@router.put("/{reading_id}", response_model=SensorReadingInDB)
def update_reading(
    reading_id: int,
    reading_data: SensorReadingUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_write_permission),
) -> SensorReadingInDB:
    """Update sensor reading."""
    try:
        result = IoTService.update_reading(db, reading_id, reading_data)
        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Reading with id {reading_id} not found",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating reading: {str(e)}",
        )


@router.delete("/{reading_id}", status_code=200)
def delete_reading(
    reading_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_admin_permission),
) -> dict:
    """Delete sensor reading."""
    try:
        if not IoTService.delete_reading(db, reading_id):
            raise HTTPException(
                status_code=404,
                detail=f"Reading with id {reading_id} not found",
            )
        return {"message": "Reading deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting reading: {str(e)}",
        )


@router.get("/latest")
def get_latest_reading(
    device_id: str = Query(..., description="Device ID"),
    unit: Optional[str] = Query(None, description="Filter by unit"),
    db: Session = Depends(get_db),
    current_user: str = Depends(require_read_permission),
):
    """
    Get the latest reading for a given device.
    """
    try:
        latest_data = IoTService.get_latest_reading_static(db, device_id, unit)
        if not latest_data:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for device {device_id}"
            )
        
        return {
            "device_id": latest_data.device_id,
            "reading_value": latest_data.reading_value,
            "timestamp": latest_data.timestamp.isoformat(),
            "unit": latest_data.unit,
            "reading_type": latest_data.reading_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting latest reading for {device_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/devices", response_model=DevicesResponse)
def get_devices(
    db: Session = Depends(get_db), current_user: str = Depends(require_read_permission)
):
    """Get all unique devices from telemetry."""
    try:
        devices = IoTService.get_all_devices(db)
        return {"device_ids": devices}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving devices: {str(e)}"
        )


@router.get("/{reading_id}", response_model=SensorReadingInDB)
def get_reading_by_id(
    reading_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_read_permission),
) -> SensorReadingInDB:
    """Get a sensor reading by its ID."""
    try:
        record = IoTService.get_reading_by_id(db, reading_id)
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"Reading with id {reading_id} not found",
            )
        return record
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving reading by id: {str(e)}",
        )


@router.get("/{device_id}/rolling-average", response_model=dict)
def get_rolling_average(
    device_id: str,
    window: int = Query(5, ge=1),
    db: Session = Depends(get_db),
    current_user: str = Depends(require_read_permission),
):
    """Calculate rolling average for a device."""
    logger.info(f"Calculating rolling average for {device_id} with window {window}")
    try:
        result = IoTService.calculate_rolling_average(db, device_id, window)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for device {device_id}",
            )
        
        latest_timestamp = IoTService.get_latest_timestamp(db, device_id)
        timestamp = latest_timestamp if latest_timestamp else datetime.now().isoformat()
        
        return {
            "device_id": device_id,
            "rolling_average": result,
            "window_size": window,
            "timestamp": timestamp,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in rolling average endpoint")
        raise HTTPException(
            status_code=500,
            detail=f"Error calculating rolling average: {str(e)}",
        )
