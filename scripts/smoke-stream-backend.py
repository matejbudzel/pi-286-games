#!/usr/bin/env python3
"""Exercise cache miss -> upload -> DOSBox -> two Xvfb frame dumps -> stop.

It uploads only an in-memory, synthetic mode-13h DOS COM program.  No private
game file is read, retained in the repository, or needed for this smoke test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request


def request(base, token, method, path, body=None, content_type="application/json"):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read(), response.headers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:28680")
    parser.add_argument("--token-file", default="/etc/pi286-stream.token")
    args = parser.parse_args()
    token = open(args.token_file, encoding="utf-8").read().strip()
    for _ in range(20):
        try:
            request(args.url, token, "GET", "/v1/status")
            break
        except urllib.error.URLError:
            time.sleep(0.1)
    else:
        raise RuntimeError("backend did not become ready")
    # COM: set VGA 320x200x256, paint all 64000 pixels colour 3, then loop.
    # The trailing nonce is unreachable after the infinite loop and guarantees
    # this invocation exercises a cache miss instead of a warm-cache shortcut.
    payload = bytes.fromhex("b81300cd10b800a08ec031ffb003b900faf3aaebfe") + os.urandom(8)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {"blobs": [{"sha256": digest, "size": len(payload)}]}
    missing = json.loads(request(args.url, token, "POST", "/v1/manifest", manifest)[0])["missing"]
    session = {"game_id": "smoke", "executable": "SMOKE.COM", "files": {"SMOKE.COM": digest}}
    if missing != [digest]:
        raise RuntimeError("new synthetic asset was unexpectedly already cached")
    try:
        request(args.url, token, "POST", "/v1/sessions", session)
    except urllib.error.HTTPError as error:
        if error.code != 400 or "absent from cache" not in error.read().decode():
            raise
    else:
        raise RuntimeError("session unexpectedly started without its asset")
    request(args.url, token, "PUT", "/v1/blobs/" + digest, payload, "application/octet-stream")
    if json.loads(request(args.url, token, "POST", "/v1/manifest", manifest)[0])["missing"]:
        raise RuntimeError("uploaded asset was not retained in cache")
    try:
        started = json.loads(request(args.url, token, "POST", "/v1/sessions", session)[0])
        session_id = started["id"]
        time.sleep(1)
        first = json.loads(request(args.url, token, "POST", f"/v1/sessions/{session_id}/frames", {})[0])
        time.sleep(0.2)
        second = json.loads(request(args.url, token, "POST", f"/v1/sessions/{session_id}/frames", {})[0])
        for frame in (first, second):
            body, _ = request(args.url, token, "GET", frame["path"])
            if len(body) != frame["bytes"] or len(body) < 100:
                raise RuntimeError("invalid XWD frame download")
        print(json.dumps({"session": session_id, "frames": [first, second], "result": "ok"}, sort_keys=True))
    finally:
        if "session_id" in locals():
            request(args.url, token, "DELETE", f"/v1/sessions/{session_id}")


if __name__ == "__main__":
    main()
