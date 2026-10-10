"""Shared helpers: config, paths, env, logging."""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

log = logging.getLogger("scout")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def load_env() -> None:
    """Minimal .env loader (KEY=VALUE lines) so python-dotenv isn't required."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def run_dir(run_date: str | None = None) -> Path:
    d = DATA / "runs" / (run_date or date.today().isoformat())
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(name: str, run_date: str | None = None) -> Path:
    d = run_dir(run_date) / "cache" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, default=str, indent=1))
