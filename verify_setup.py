"""
Arkon Manufacturing AI - Windows Setup Verification
Run this script after activating the venv to confirm everything is ready.

    python verify_setup.py
"""
import sys
import platform
from pathlib import Path

PASS = "✓"
FAIL = "✗"
WARN = "⚠"

errors = 0

def check(label, ok, detail=""):
    global errors
    icon = PASS if ok else FAIL
    if not ok:
        errors += 1
    print(f"  {icon}  {label}" + (f"  →  {detail}" if detail else ""))


print("=" * 60)
print("  Arkon Manufacturing AI - Setup Verification")
print(f"  Python  : {sys.version}")
print(f"  OS      : {platform.system()} {platform.machine()}")
print("=" * 60)

# ── Python version ────────────────────────────────────────────────
print("\n[1] Python")
check("Python >= 3.12", sys.version_info >= (3, 12), sys.version.split()[0])

# ── Core packages ─────────────────────────────────────────────────
print("\n[2] Core packages")
packages = ["pandas", "numpy", "sklearn", "xgboost", "matplotlib",
            "seaborn", "mlflow", "streamlit", "joblib"]
for pkg in packages:
    try:
        import importlib
        m = importlib.import_module(pkg if pkg != "sklearn" else "sklearn")
        ver = getattr(m, "__version__", "?")
        check(pkg, True, ver)
    except ImportError:
        check(pkg, False, "NOT INSTALLED")

# ── PyTorch + CUDA ────────────────────────────────────────────────
print("\n[3] PyTorch + CUDA")
try:
    import torch
    import torchvision
    check("torch", True, torch.__version__)
    check("torchvision", True, torchvision.__version__)

    cuda_ok = torch.cuda.is_available()
    check("CUDA available", cuda_ok)
    if cuda_ok:
        check("CUDA version", True, torch.version.cuda)
        check("GPU name", True, torch.cuda.get_device_name(0))
        mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        check("GPU VRAM", True, f"{mem:.1f} GB")
    else:
        print(f"  {WARN}  No CUDA GPU found - will run on CPU (training will be slow)")
except ImportError:
    check("torch", False, "NOT INSTALLED - run setup_windows_venv.bat")

# ── MLflow + project DB ───────────────────────────────────────────
print("\n[4] MLflow")
try:
    import mlflow
    check("mlflow", True, mlflow.__version__)
    project_root = Path(__file__).parent
    db = project_root / "mlflow.db"
    check("mlflow.db exists", db.exists(), str(db))

    # Test that URI resolves
    uri = f"sqlite:///{db.as_posix()}"
    mlflow.set_tracking_uri(uri)
    check("MLflow URI", True, uri[:60])
except ImportError:
    check("mlflow", False, "NOT INSTALLED")

# ── arkon_utils ───────────────────────────────────────────────────
print("\n[5] arkon_utils")
sys.path.insert(0, str(Path(__file__).parent / "notebooks"))
try:
    from utils.arkon_utils import get_device, get_mlflow_uri, save_figure, Timer, CheckpointManager
    check("arkon_utils import", True)
    uri = get_mlflow_uri()
    check("get_mlflow_uri()", True, uri[:60])
    t = Timer()
    t.start(); t.stop()
    check("Timer", True, t.report())
except Exception as e:
    check("arkon_utils", False, str(e))

# ── Data ──────────────────────────────────────────────────────────
print("\n[6] Data")
root = Path(__file__).parent / "data"
datasets = {
    "CMAPSS"          : root / "01_cmapss/raw/CMaps",
    "Scania"          : root / "02_scania/raw",
    "Casting"         : root / "03_casting/raw/train",
    "NEU"             : root / "04_neu/raw",
    "MVTec"           : root / "05_mvtec/raw",
    "GC10"            : root / "06_gc10/raw",
}
for name, path in datasets.items():
    check(name, path.exists(), str(path) if not path.exists() else "found")

# ── Assets + Checkpoints ──────────────────────────────────────────
print("\n[7] Output directories")
dirs = ["assets/timeseries", "assets/ml", "assets/cv/casting",
        "models/checkpoints/cmapss", "models/checkpoints/scania",
        "models/checkpoints/casting"]
for d in dirs:
    p = Path(__file__).parent / d
    check(d, p.exists())

# ── Summary ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
if errors == 0:
    print(f"  {PASS}  All checks passed - ready to run notebooks!")
else:
    print(f"  {FAIL}  {errors} check(s) failed - see above")
print("=" * 60)
