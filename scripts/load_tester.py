"""
Author: Xin Hu | Xenith Technologies LLC
Load testing script for IoT Stream Engine.
"""
import asyncio
import aiohttp
import time
import random
import uuid
import json
from datetime import datetime, timezone
from typing import List

# Configuration
# Configuration
TARGET_URL = "http://localhost:8000/telemetry/ingest"
CONCURRENCY = 500
DURATION_SECONDS = 15
DEVICE_COUNT = 50
API_KEY = "demo-api-key-123"  # Using a valid key from app/core/auth.py

# Generate fake device IDs
DEVICES = [str(uuid.uuid4()) for _ in range(DEVICE_COUNT)]

stats = {
    "requests_sent": 0,
    "success_count": 0,
    "failure_count": 0,
    "errors": []
}

async def simulate_device(session: aiohttp.ClientSession, end_time: float):
    """Simulate a single device sending data until end_time."""
    while time.time() < end_time:
        device_id = random.choice(DEVICES)
        
        # Randomly choose between temperature and voltage reading
        # to simulate diverse data, conforming to the single-reading schema
        reading_type = random.choice(["temperature", "voltage"])
        
        if reading_type == "temperature":
            value = random.uniform(20.0, 100.0)
            unit = "C"
        else:
            value = random.uniform(3.0, 5.0)
            unit = "V"

        payload = {
            "device_id": device_id,
            "reading_value": round(value, 2),
            "reading_type": reading_type,
            "unit": unit,
            "timestamp": datetime.now(timezone.utc).isoformat(), # Client timestamp
            "battery_level": round(random.uniform(10.0, 100.0), 1)
        }
        
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }


        try:
            stats["requests_sent"] += 1
            timeout = aiohttp.ClientTimeout(total=5)
            async with session.post(TARGET_URL, json=payload, headers=headers, timeout=timeout) as response:
                if response.status == 201 or response.status == 200 or response.status == 202:
                    stats["success_count"] += 1
                else:
                    stats["failure_count"] += 1
                    # Record first few errors
                    if len(stats["errors"]) < 5:
                        stats["errors"].append(f"{response.status}: {await response.text()}")
        except Exception as e:
            stats["failure_count"] += 1
            if len(stats["errors"]) < 5:
                stats["errors"].append(repr(e))
        
        # Slight delay to prevent complete event loop starvation if local
        await asyncio.sleep(0.01)

async def reporter_loop(end_time: float):
    """Print stats every second."""
    while time.time() < end_time:
        await asyncio.sleep(1)
        print(f"Sent {stats['requests_sent']} requests... (Success: {stats['success_count']}, Fail: {stats['failure_count']})")

async def main():
    print(f"Starting Load Test on {TARGET_URL}")
    print(f"Simulating {CONCURRENCY} devices for {DURATION_SECONDS} seconds...")
    print("-" * 50)

    end_time = time.time() + DURATION_SECONDS
    
    async with aiohttp.ClientSession() as session:
        tasks = [simulate_device(session, end_time) for _ in range(CONCURRENCY)]
        tasks.append(reporter_loop(end_time))
        
        await asyncio.gather(*tasks)

    # Final Report
    total_time = DURATION_SECONDS # Approx
    total_reqs = stats["requests_sent"]
    rps = total_reqs / total_time if total_time > 0 else 0
    
    print("\n" + "=" * 50)
    print("LOAD TEST RESULTS")
    print("=" * 50)
    print(f"Total Requests Sent: {total_reqs}")
    print(f"Success Count:       {stats['success_count']}")
    print(f"Failure Count:       {stats['failure_count']}")
    print(f"Success Rate:       {(stats['success_count'] / total_reqs * 100) if total_reqs else 0:.2f}%")
    print(f"Failure Rate:       {(stats['failure_count'] / total_reqs * 100) if total_reqs else 0:.2f}%")
    print(f"Requests Per Second: {rps:.2f} RPS")
    print("=" * 50)
    
    if stats["errors"]:
        print("\nTop Errors:")
        for err in stats["errors"]:
            print(f"- {err}")

if __name__ == "__main__":
    # Check if aiohttp is installed
    try:
        import aiohttp
        asyncio.run(main())
    except ImportError:
        print("Error: aiohttp is not installed. Please run: pip install aiohttp")
