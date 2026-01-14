"""
RQ Worker settings.

This file is loaded by rq worker via: rq worker -c worker_settings
"""

import os

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Queues to listen on (in priority order)
QUEUES = ["high", "default", "low"]

# Worker settings
WORKER_TTL = 420  # Worker heartbeat TTL (7 minutes)
JOB_TIMEOUT = 3600  # Max job runtime (1 hour)
RESULT_TTL = 86400  # Keep results for 24 hours

# Logging
LOGGING_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOGGING_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
