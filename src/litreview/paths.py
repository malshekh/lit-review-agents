"""Fixed locations inside the repository."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "prompts"
SHARED_PROMPTS_DIR = PROMPTS_DIR / "shared"
AGENT_PROMPTS_DIR = PROMPTS_DIR / "agents"
CONFIG_DIR = REPO_ROOT / "config"
SCHEMAS_DIR = REPO_ROOT / "schemas"
RUNS_DIR = REPO_ROOT / "runs"
