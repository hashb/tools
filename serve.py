#!/usr/bin/env python3
"""
serve.py - Local dev server: build, serve, and rebuild on changes.

Usage: python serve.py [port]   (default port: 8000)
"""

import http.server
import importlib.util
import os
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

# Files/patterns that trigger a rebuild when changed.
WATCH_SUFFIXES = {".html", ".md", ".py"}
WATCH_EXCLUDE = {"index.html", "404.html", "serve.py"}


def run_build():
    """Import and run build_index.build() in-process."""
    spec = importlib.util.spec_from_file_location("build_index", ROOT / "build_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.build()


def snapshot() -> dict[pathlib.Path, float]:
    """Return {path: mtime} for all watched files."""
    result = {}
    for path in ROOT.iterdir():
        if path.is_file() and path.suffix in WATCH_SUFFIXES and path.name not in WATCH_EXCLUDE:
            result[path] = path.stat().st_mtime
    return result


def watch():
    """Poll for file changes and rebuild when detected."""
    mtimes = snapshot()
    while True:
        time.sleep(1)
        current = snapshot()
        changed = [
            p.name for p, mtime in current.items()
            if mtimes.get(p) != mtime
        ] + [p.name for p in mtimes if p not in current]
        if changed:
            print(f"\n[watch] changed: {', '.join(changed)} — rebuilding...")
            try:
                run_build()
            except Exception as e:
                print(f"[watch] build error: {e}")
            mtimes = snapshot()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Only log non-200 responses to keep output clean
        if args and not str(args[1]).startswith("2"):
            super().log_message(fmt, *args)

    def translate_path(self, path):
        return super().translate_path(path)


def serve():
    os.chdir(ROOT)
    server = http.server.HTTPServer(("", PORT), QuietHandler)
    print(f"[serve] http://localhost:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    print("[build] initial build...")
    run_build()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()

    try:
        serve()
    except KeyboardInterrupt:
        print("\n[serve] stopped.")
