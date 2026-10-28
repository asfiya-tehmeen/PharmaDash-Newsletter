"""Loads config.yaml and .env, and knows where every folder lives."""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

# The project root is the folder that contains config.yaml. We look in the
# current folder first (so the command works from the project), then walk up,
# then fall back to the PHARMADASH_HOME environment variable.


def find_root() -> Path:
    env = os.environ.get("PHARMADASH_HOME")
    if env:
        return Path(env)
    here = Path.cwd().resolve()
    for folder in [here, *here.parents]:
        if (folder / "config.yaml").exists():
            return folder
    return here


ROOT = find_root()
load_dotenv(ROOT / ".env")

CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
HISTORY_PATH = DATA_DIR / "history.json"
OUTPUT_DIR = ROOT / "output"
TOPICS_DIR = OUTPUT_DIR / "topics"
ISSUES_DIR = OUTPUT_DIR / "issues"
RUNS_DIR = OUTPUT_DIR / "runs"
EXAMPLES_DIR = ROOT / "examples"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"config.yaml not found in {ROOT}. Run `pharmadash init` from the project folder."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_issue_counter(n: int) -> None:
    """Update issue_counter in config.yaml without disturbing comments."""
    text = CONFIG_PATH.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^issue_counter:\s*\d+", f"issue_counter: {n}", text)
    CONFIG_PATH.write_text(text, encoding="utf-8")


def sec_user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "").strip()


def groq_api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()
