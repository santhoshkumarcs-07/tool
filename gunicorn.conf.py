"""
Gunicorn Production WSGI Configuration for AI Tool Discovery
Optimized for Free-Tier Linux Instances (1-2 vCPU, 1-2 GB RAM).
"""

import os
import multiprocessing

# Network binding
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Worker processes and threading
# On low-RAM/free tier VM, 2 workers with 4 threads balances concurrency and memory footprint (~400MB total)
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"

# Timeouts
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "180"))
keepalive = 5

# Memory management: restart workers periodically to avoid memory leaks
max_requests = 500
max_requests_jitter = 50

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Process naming
proc_name = "tool_discovery_wsgi"
