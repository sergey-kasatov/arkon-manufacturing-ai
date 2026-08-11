# =============================================================================
# Arkon Manufacturing AI - Shared Notebook Utilities
# =============================================================================
# Provides:
#   get_device()          - CUDA/CPU detection for PyTorch
#   get_mlflow_uri()      - platform-safe SQLite MLflow URI
#   save_figure()         - save matplotlib figure to assets/
#   Timer                 - context manager for training time
#   CheckpointManager     - save/load models to avoid retraining
# =============================================================================

import time
import json
import joblib
import platform
from pathlib import Path

import matplotlib.pyplot as plt

# ── Project root (notebooks/utils/ → project root) ───────────────────────────
_UTILS_DIR  = Path(__file__).resolve().parent          # notebooks/utils/
_NB_DIR     = _UTILS_DIR.parent                        # notebooks/
PROJECT_ROOT = _NB_DIR.parent                          # project root


def _rel_to_project(path: Path) -> str:
    """Display helper: path relative to project root, absolute if outside."""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ─────────────────────────────────────────────────────────────────────────────
# Device
# ─────────────────────────────────────────────────────────────────────────────

def get_device(verbose: bool = True):
    """
    Return the best available PyTorch device.

    Priority: CUDA (GPU) > MPS (Apple Silicon) > CPU

    Usage
    -----
    device = get_device()
    model  = model.to(device)
    X      = X.to(device)
    """
    import torch

    if torch.cuda.is_available():
        device = torch.device("cuda")
        if verbose:
            name  = torch.cuda.get_device_name(0)
            mem   = torch.cuda.get_device_properties(0).total_memory / 1e9
            print(f"✓ Device : CUDA - {name}  ({mem:.1f} GB VRAM)")
            print(f"  CUDA   : {torch.version.cuda}")
            print(f"  PyTorch: {torch.__version__}")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = torch.device("mps")
        if verbose:
            print(f"✓ Device : MPS (Apple Silicon)")
            print(f"  PyTorch: {torch.__version__}")
    else:
        device = torch.device("cpu")
        if verbose:
            print(f"⚠ Device : CPU  (no GPU found)")
            print(f"  PyTorch: {torch.__version__}")
            print(f"  OS     : {platform.system()} {platform.machine()}")

    return device


def recommended_num_workers(device=None) -> int:
    """
    Return a safe number of DataLoader workers.
    - CUDA on Windows : 4  (multiprocessing works but keep it moderate)
    - CPU / MPS       : 0  (safest for notebooks)
    """
    import os
    if device is None:
        import torch
        if torch.cuda.is_available():
            # Windows notebooks can use workers, but 0 is safest default;
            # set to 4 for real speed gains if you're not in a Jupyter kernel
            return 0   # change to 4 if running as .py script
        return 0
    return 4 if (device.type == "cuda") else 0


# ─────────────────────────────────────────────────────────────────────────────
# MLflow URI - platform safe
# ─────────────────────────────────────────────────────────────────────────────

def get_mlflow_uri(db_filename: str = "mlflow.db") -> str:
    """
    Return a cross-platform SQLite URI for MLflow.

    On all platforms (Windows / Mac / Linux) uses the mlflow.db file
    in the project root.  No hardcoded /Users/... paths.

    Usage
    -----
    mlflow.set_tracking_uri(get_mlflow_uri())
    """
    db_path = (PROJECT_ROOT / db_filename).resolve()

    # SQLite URI format:
    #   Unix  : sqlite:////absolute/path/to/file.db  (4 slashes)
    #   Win   : sqlite:///C:/path/to/file.db          (3 slashes + drive)
    #
    # Using as_posix() makes it forward-slash on Windows too, which
    # SQLAlchemy (used by MLflow) handles correctly.
    uri = f"sqlite:///{db_path.as_posix()}"
    return uri


# ─────────────────────────────────────────────────────────────────────────────
# Assets - save figures
# ─────────────────────────────────────────────────────────────────────────────

_ASSETS_DIR = PROJECT_ROOT / "assets"


def save_figure(
    fig,
    name: str,
    subfolder: str = "",
    dpi: int = 150,
    fmt: str = "png",
    close: bool = False,
) -> Path:
    """
    Save a matplotlib figure to assets/<subfolder>/<name>.<fmt>.

    Parameters
    ----------
    fig       : matplotlib.figure.Figure
    name      : filename without extension, e.g. 'cmapss_eda_lifetime_hist'
    subfolder : optional subdirectory inside assets/, e.g. 'timeseries'
    dpi       : resolution (150 is good for README, 300 for print)
    fmt       : 'png' (default) | 'svg' | 'pdf'
    close     : if True, closes the figure after saving

    Returns
    -------
    Path to saved file.

    Usage
    -----
    fig, ax = plt.subplots(...)
    ax.plot(...)
    save_figure(fig, 'my_plot', subfolder='timeseries')
    plt.show()
    """
    out_dir = _ASSETS_DIR / subfolder if subfolder else _ASSETS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.{fmt}"
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    print(f"  ✓ Saved → {_rel_to_project(path)}")
    if close:
        plt.close(fig)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Timer - measure training / preprocessing time
# ─────────────────────────────────────────────────────────────────────────────

class Timer:
    """
    Lightweight stopwatch.  Use as context manager or manually.

    Usage (context manager)
    -----------------------
    with Timer() as t:
        model.fit(X_train, y_train)
    # prints "⏱  Training time: 1m 23s"
    train_time = t.report()   # → "1m 23s (83.4s)"

    Usage (manual)
    --------------
    t = Timer().start()
    ...
    t.stop()
    print(t.report())
    """

    def __init__(self, label: str = "Training"):
        self.label   = label
        self._start  = None
        self.elapsed: float | None = None

    def start(self):
        self._start = time.perf_counter()
        return self

    def stop(self):
        if self._start is None:
            raise RuntimeError("Timer.start() was not called.")
        self.elapsed = time.perf_counter() - self._start
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()
        print(f"⏱  {self.label} time: {self._fmt()}")

    def _fmt(self) -> str:
        if self.elapsed is None:
            return "not measured"
        m, s = divmod(int(self.elapsed), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m {s}s  ({self.elapsed:.1f}s total)"
        if m:
            return f"{m}m {s}s  ({self.elapsed:.1f}s total)"
        return f"{self.elapsed:.1f}s"

    def report(self) -> str:
        """Return formatted string for use in metrics tables / MLflow logs."""
        return self._fmt()

    @property
    def seconds(self) -> float:
        """Raw elapsed seconds (float)."""
        return self.elapsed or 0.0


# ─────────────────────────────────────────────────────────────────────────────
# CheckpointManager - skip retraining if model already saved
# ─────────────────────────────────────────────────────────────────────────────

class CheckpointManager:
    """
    Save / load model checkpoints so notebooks don't retrain from scratch.

    Supports:
      • scikit-learn / XGBoost  (.pkl via joblib)
      • PyTorch models          (.pt  via torch.save / torch.load)
      • arbitrary metadata      (JSON sidecar file)

    Usage - sklearn
    ---------------
    ckpt = CheckpointManager('models/checkpoints/scania')

    if ckpt.exists('xgb_v1'):
        xgb, meta = ckpt.load_sklearn('xgb_v1')
        print('Loaded from checkpoint:', meta)
    else:
        xgb = XGBClassifier(**params)
        with Timer() as t:
            xgb.fit(X_train, y_train)
        ckpt.save_sklearn(xgb, 'xgb_v1', metadata={'train_time': t.report()})

    Usage - PyTorch
    ---------------
    ckpt = CheckpointManager('models/checkpoints/casting')

    if ckpt.exists_torch('resnet18_best'):
        state, meta = ckpt.load_torch('resnet18_best')
        model.load_state_dict(state)
    else:
        # ... train ...
        ckpt.save_torch(model.state_dict(), 'resnet18_best',
                        metadata={'epoch': 10, 'val_acc': 0.985})
    """

    def __init__(self, checkpoint_dir=None):
        if checkpoint_dir is None:
            checkpoint_dir = PROJECT_ROOT / "models" / "checkpoints"
        # Resolve so relative dirs passed from notebooks don't break display paths
        self.dir = Path(checkpoint_dir).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)

    # ── sklearn / XGBoost ────────────────────────────────────────────────────

    def exists(self, name: str) -> bool:
        return (self.dir / f"{name}.pkl").exists()

    def save_sklearn(self, model, name: str, metadata: dict = None) -> Path:
        path = self.dir / f"{name}.pkl"
        joblib.dump(model, path)
        if metadata:
            self._save_meta(name, metadata)
        print(f"  ✓ Checkpoint saved → {_rel_to_project(path)}")
        return path

    def load_sklearn(self, name: str):
        """Returns (model, metadata_dict)."""
        path = self.dir / f"{name}.pkl"
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        model = joblib.load(path)
        meta  = self._load_meta(name)
        print(f"  ✓ Checkpoint loaded ← {_rel_to_project(path)}")
        if meta:
            print(f"    metadata: {meta}")
        return model, meta

    # ── PyTorch ──────────────────────────────────────────────────────────────

    def exists_torch(self, name: str) -> bool:
        return (self.dir / f"{name}.pt").exists()

    def save_torch(self, state_dict, name: str, metadata: dict = None) -> Path:
        import torch
        path = self.dir / f"{name}.pt"
        payload = {"state_dict": state_dict}
        if metadata:
            payload["metadata"] = metadata
        torch.save(payload, path)
        if metadata:
            self._save_meta(name, metadata)
        print(f"  ✓ Checkpoint saved → {_rel_to_project(path)}")
        return path

    def load_torch(self, name: str, map_location="cpu"):
        """Returns (state_dict, metadata_dict)."""
        import torch
        path = self.dir / f"{name}.pt"
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        payload = torch.load(path, map_location=map_location)
        state   = payload.get("state_dict")
        meta    = payload.get("metadata", self._load_meta(name))
        print(f"  ✓ Checkpoint loaded ← {_rel_to_project(path)}")
        if meta:
            print(f"    metadata: {meta}")
        return state, meta

    # ── Epoch checkpoints (PyTorch training loop) ────────────────────────────

    def save_epoch(self, model, optimizer, epoch: int, metrics: dict, name: str) -> Path:
        """Save full training state for resuming interrupted training."""
        import torch
        path = self.dir / f"{name}_epoch{epoch:03d}.pt"
        torch.save({
            "epoch":      epoch,
            "state_dict": model.state_dict(),
            "optimizer":  optimizer.state_dict(),
            "metrics":    metrics,
        }, path)
        print(f"  ✓ Epoch checkpoint → {path.name}")
        return path

    def load_latest_epoch(self, name: str, map_location="cpu"):
        """Find the latest epoch checkpoint matching name prefix."""
        import torch
        checkpoints = sorted(self.dir.glob(f"{name}_epoch*.pt"))
        if not checkpoints:
            return None, 0, {}
        path   = checkpoints[-1]
        data   = torch.load(path, map_location=map_location)
        epoch  = data["epoch"]
        print(f"  ✓ Resuming from epoch {epoch} ← {path.name}")
        return data["state_dict"], epoch, data.get("metrics", {})

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _save_meta(self, name: str, metadata: dict):
        path = self.dir / f"{name}_meta.json"
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)

    def _load_meta(self, name: str) -> dict:
        path = self.dir / f"{name}_meta.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    def list_checkpoints(self):
        """Print all checkpoints in this directory."""
        files = sorted(self.dir.glob("*"))
        if not files:
            print("  No checkpoints found.")
        for f in files:
            size = f.stat().st_size / 1e6
            print(f"  {f.name:<40}  {size:.2f} MB")
