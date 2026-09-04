"""Where the cockpit reads from, and how to point it somewhere else.

Every path is derived from this file's own location and every endpoint has an
environment override, so the same app runs from a checkout on a laptop and from
a container on the NAS without a line changing. The container reaches n8n and
Langflow by their network aliases; the laptop reaches them by host name.
"""

import os
import pathlib

# Paths. app/utils/config.py -> app/utils -> app -> the repository root.
REPO = pathlib.Path(__file__).resolve().parents[2]
ASSETS = REPO / "assets"
CHECKPOINTS = REPO / "models" / "checkpoints"
DOCS = REPO / "docs"
EVENTS = REPO / "events" / "out"


def _secrets():
    """Read `.streamlit/secrets.toml` from the repository, if it is there.

    Streamlit's own `st.secrets` finds that file relative to the process working
    directory, which is not the repository when the app is started by absolute
    path. Resolving it from `REPO` instead makes the lookup independent of where
    the server was launched from. The file is gitignored; on the NAS the same
    values arrive as environment variables from the compose file.
    """
    path = REPO / ".streamlit" / "secrets.toml"
    if not path.exists():
        return {}
    try:
        import tomllib

        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


_SECRETS = _secrets()


def _env(name, default):
    value = os.environ.get(name, "").strip() or str(_SECRETS.get(name, "")).strip()
    return value or default


# The n8n Steering Cell. The status API is the only way this app reads incidents:
# it never opens the JSONL store, because the store holds the state an incident
# was raised in and the API is what folds the transition log onto it.
STATUS_API = _env("ARKON_STATUS_API", "http://AK2101:5678/webhook/arkon-incident-status")
TRANSITION_API = _env("ARKON_TRANSITION_API", "http://AK2101:5678/webhook/arkon-incident-transition")

# Langflow, for the assistant page. The key is passed in by the environment and
# never stored here: on the NAS it comes from the compose file, which is not in
# this repository. Without it the assistant page says so rather than failing.
LANGFLOW_URL = _env("ARKON_LANGFLOW_URL", "http://AK2101:7860")
LANGFLOW_API_KEY = _env("ARKON_LANGFLOW_API_KEY", "")
ASSISTANT_FLOW = _env("ARKON_ASSISTANT_FLOW", "arkon-quality-assistant")

# Charter 7.1 acknowledgement windows, in minutes. P3 and P4 have none. Repeated
# here only to label a column; every number the cockpit shows is computed by the
# status API from the transition log, not by this app.
ACK_WINDOW_MINUTES = {"P1": 15, "P2": 60}

# Charter 7.2, in order.
LIFECYCLE = ["new", "acknowledged", "in_containment", "resolved", "closed", "false_positive"]

REPO_URL = "https://github.com/sergey-kasatov/arkon-manufacturing-ai"
