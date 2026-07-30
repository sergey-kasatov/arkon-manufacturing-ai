@echo off
REM =============================================================================
REM  Arkon Manufacturing AI - Windows venv setup
REM  Target: RTX 3070 (CUDA 12.x)  |  Python 3.12
REM
REM  Usage:
REM    1. Open CMD or PowerShell as normal user (no Admin needed)
REM    2. cd D:\-PROJECTS\--Portfolio\arkon-manufacturing-ai
REM    3. setup_windows_venv.bat
REM
REM  Creates venv at: D:\-PROJECTS\--venvs\arkon-manufacturing-ai_win_venv
REM =============================================================================

SET VENV_DIR=D:\-PROJECTS\--venvs\arkon-manufacturing-ai_win_venv
SET PYTHON=py -3.12

echo.
echo ============================================================
echo  Arkon Manufacturing AI - Windows Environment Setup
echo ============================================================
echo  Venv location : %VENV_DIR%
echo  Python        : Python 3.12
echo  GPU target    : RTX 3070 (CUDA 12.x)
echo ============================================================
echo.

REM ── 1. Verify Python 3.12 ────────────────────────────────────────────────
echo [1/6] Checking Python 3.12...
%PYTHON% --version
IF ERRORLEVEL 1 (
    echo ERROR: Python 3.12 not found.
    echo Install from https://www.python.org/downloads/
    pause & exit /b 1
)

REM ── 2. Create virtual environment ────────────────────────────────────────
echo.
echo [2/6] Creating virtual environment at %VENV_DIR%...
IF EXIST "%VENV_DIR%" (
    echo  Venv already exists - skipping creation.
) ELSE (
    %PYTHON% -m venv "%VENV_DIR%"
)

REM ── 3. Activate ──────────────────────────────────────────────────────────
echo.
echo [3/6] Activating venv...
CALL "%VENV_DIR%\Scripts\activate.bat"

REM ── 4. Upgrade pip ───────────────────────────────────────────────────────
echo.
echo [4/6] Upgrading pip...
python -m pip install --upgrade pip setuptools wheel

REM ── 5. Install PyTorch with CUDA 12.4 ────────────────────────────────────
REM  RTX 3070 supports CUDA up to 12.x.
REM  PyTorch stable build for CUDA 12.4 (latest as of 2025):
echo.
echo [5/6] Installing PyTorch with CUDA 12.4 support...
echo  (This downloads ~2.5 GB - grab a coffee...)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

REM ── 6. Install project dependencies ──────────────────────────────────────
echo.
echo [6/6] Installing project dependencies...
pip install -r requirements-windows.txt

echo.
echo ============================================================
echo  Setup complete!
echo ============================================================
echo.
echo  To activate the venv in any terminal:
echo    %VENV_DIR%\Scripts\activate.bat
echo.
echo  To register as Jupyter kernel:
echo    python -m ipykernel install --user --name arkon-win --display-name "Arkon AI (Win+CUDA)"
echo.
echo  To verify GPU:
echo    python -c "import torch; print(torch.cuda.get_device_name(0))"
echo ============================================================
echo.

REM ── Verify GPU ───────────────────────────────────────────────────────────
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"

pause
