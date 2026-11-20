"""
Server launcher for NHAI AI Road Survey Dashcam.
Starts Uvicorn serving FastAPI backend and frontend PWA.
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NHAI Dashcam Server Launcher")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host IP to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable live auto-reload for dev")
    args = parser.parse_args()

    print(f"=======================================================")
    print(f"  NHAI AI ROAD SURVEY DASHCAM SYSTEM v2.4.0")
    print(f"  Direct Hotspot URL: http://192.168.4.1:{args.port}")
    print(f"  Local Hostname:    http://dashcam.local:{args.port}")
    print(f"  Localhost:         http://localhost:{args.port}")
    print(f"=======================================================")

    uvicorn.run(
        "backend.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
