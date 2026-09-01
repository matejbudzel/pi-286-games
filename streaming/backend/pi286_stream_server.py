#!/usr/bin/env python3
"""Compatibility entry point for the modular Pi286 stream backend."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep this module import-compatible for deployments and diagnostics that used
# its original public helpers before the backend was separated by concern.
from streaming.backend.stream_http import WEB_FILES, WEB_STATIC, StreamHTTPServer, make_handler
from streaming.backend.stream_models import (DEFAULTS, KEYS, PCM_CHUNK_BYTES, POLL_HEADER,
                                             RAINBOW_CAT_COM, SESSION_RE, VIDEO_BYTES, VIDEO_HEIGHT,
                                             VIDEO_KEYFRAME_INTERVAL, VIDEO_PACKET_HEADER,
                                             VIDEO_SCALING_MODES, VIDEO_TILE, VIDEO_WIDTH,
                                             GameDefinition, PurePosixPath, read_config,
                                             safe_relative_path)
from streaming.backend.stream_state import StreamState

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = read_config(args.config)
    token = Path(config["token_file"]).read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise SystemExit("token must contain at least 32 characters")
    state = StreamState(config, token)
    server = StreamHTTPServer((config["bind"], int(config["port"])), make_handler(state), state)
    print(f"pi286 stream backend listening on {config['bind']}:{config['port']}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
