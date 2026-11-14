#!/usr/bin/env python3
"""Download the published Arianet OpenAPI specs into specs/<service>.json.

Usage: python3 codegen/fetch_specs.py

Each spec's `servers` list is rewritten to the public API gateway address the
SDK talks to, so the committed copies only name the public endpoint. YAML
sources need PyYAML (`pip install pyyaml`).
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "codegen" / "services.json").read_text())


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "arianet-sdk-codegen"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse(url: str, raw: bytes) -> dict:
    if url.endswith((".yaml", ".yml")):
        import yaml  # type: ignore

        return yaml.safe_load(raw)
    return json.loads(raw)


def main() -> int:
    out_dir = ROOT / "specs"
    out_dir.mkdir(exist_ok=True)
    for svc in CONFIG["services"]:
        spec = parse(svc["source"], download(svc["source"]))
        if "paths" not in spec:
            print(f"{svc['key']}: {svc['source']} is not an OpenAPI document", file=sys.stderr)
            return 1
        spec["servers"] = [{"url": CONFIG["gateway"] + svc["prefix"], "description": "Arianet API gateway"}]
        text = json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (out_dir / f"{svc['key']}.json").write_text(text)
        print(f"{svc['key']}: {len(spec['paths'])} paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
