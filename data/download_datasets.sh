#!/bin/bash
# =============================================================================
# Arkon Manufacturing AI - Dataset Download Script
# Run this from the project root on your local Mac:
#   cd <path>/arkon-manufacturing-ai
#   chmod +x data/download_datasets.sh
#   ./data/download_datasets.sh
#
# Requirements:
#   - curl (pre-installed on Mac)
#   - unzip (pre-installed on Mac)
#   - kaggle CLI (for CMAPSS mirror + CV dataset):
#       pip install kaggle
#       Place kaggle.json in ~/.kaggle/  (kaggle.com → Settings → API → Create Token)
# =============================================================================

BASE="$(cd "$(dirname "$0")" && pwd)"

echo "=============================================="
echo "  Arkon Manufacturing AI - Dataset Downloader"
echo "=============================================="

# ──────────────────────────────────────────────────────
# 1. NASA CMAPSS - Time Series (Engine RUL)
# ──────────────────────────────────────────────────────
echo ""
echo "[1/3] NASA CMAPSS - Turbofan Engine Degradation Dataset"
CMAPSS_DIR="$BASE/cmapss/raw"
mkdir -p "$CMAPSS_DIR"

if [ -f "$CMAPSS_DIR/train_FD001.txt" ]; then
    echo "  ✓ Already downloaded, skipping."
else
    # Clean up any bad previous attempt
    rm -f "$CMAPSS_DIR/cmapss.zip"

    CMAPSS_OK=false

    # Option A: Kaggle mirror (most reliable, needs kaggle CLI)
    if command -v kaggle &> /dev/null; then
        echo "  Downloading via Kaggle mirror (behrad3d/nasa-cmaps)..."
        kaggle datasets download -d behrad3d/nasa-cmaps -p "$CMAPSS_DIR" --unzip \
            && CMAPSS_OK=true
    fi

    # Option B: Direct NASA PHM zip (no auth required, but URL may change)
    if [ "$CMAPSS_OK" = false ]; then
        echo "  Trying direct NASA link..."
        curl -L --fail -o "$CMAPSS_DIR/cmapss.zip" \
            "https://ti.arc.nasa.gov/c/6/" \
            --max-time 120 2>/dev/null && CMAPSS_OK=true || true
    fi

    # Option C: NASA data.gov direct asset download
    if [ "$CMAPSS_OK" = false ]; then
        echo "  Trying NASA data.gov asset link..."
        curl -L --fail -o "$CMAPSS_DIR/cmapss.zip" \
            "https://data.nasa.gov/api/assets/1874a775-dde8-4e13-9fa0-af1ec6c0ce14?download=true" \
            --max-time 120 2>/dev/null && CMAPSS_OK=true || true
    fi

    # Validate and extract zip if we got one
    if [ "$CMAPSS_OK" = false ] && [ -f "$CMAPSS_DIR/cmapss.zip" ]; then
        if unzip -t "$CMAPSS_DIR/cmapss.zip" &>/dev/null; then
            echo "  Extracting..."
            unzip -o "$CMAPSS_DIR/cmapss.zip" -d "$CMAPSS_DIR/"
            rm "$CMAPSS_DIR/cmapss.zip"
            CMAPSS_OK=true
        else
            echo "  ⚠️  Downloaded file is not a valid zip (probably an HTML redirect)."
            rm -f "$CMAPSS_DIR/cmapss.zip"
        fi
    elif [ -f "$CMAPSS_DIR/cmapss.zip" ]; then
        echo "  Extracting..."
        unzip -o "$CMAPSS_DIR/cmapss.zip" -d "$CMAPSS_DIR/"
        rm "$CMAPSS_DIR/cmapss.zip"
    fi

    if [ "$CMAPSS_OK" = false ]; then
        echo ""
        echo "  ⚠️  Automatic download failed. Get CMAPSS manually:"
        echo "     1. Kaggle (recommended, ~3 MB):"
        echo "        https://www.kaggle.com/datasets/behrad3d/nasa-cmaps"
        echo "        Extract to: data/01_cmapss/raw/"
        echo ""
        echo "     2. NASA direct (login may be required):"
        echo "        https://ti.arc.nasa.gov/tech/dash/groups/pcoe/prognostic-data-repository/"
        echo "        → 'Turbofan Engine Degradation Simulation Data Set'"
        echo "        Extract to: data/01_cmapss/raw/"
    else
        echo "  ✓ CMAPSS downloaded to data/01_cmapss/raw/"
    fi
fi

# Expected files: train_FD001.txt, test_FD001.txt, RUL_FD001.txt (x4 for FD001-FD004)

# ──────────────────────────────────────────────────────
# 2. APS Failure at Scania Trucks - ML Classification
# ──────────────────────────────────────────────────────
echo ""
echo "[2/3] APS Failure at Scania Trucks (UCI ML Repository)"
SCANIA_DIR="$BASE/scania/raw"
mkdir -p "$SCANIA_DIR"

if [ -f "$SCANIA_DIR/aps_failure_training_set.csv" ]; then
    echo "  ✓ Already downloaded, skipping."
else
    echo "  Downloading from UCI..."
    curl -L -k -o "$SCANIA_DIR/scania.zip" \
        "https://archive.ics.uci.edu/static/public/421/aps+failure+at+scania+trucks.zip" \
        --max-time 300

    # Validate
    if unzip -t "$SCANIA_DIR/scania.zip" &>/dev/null; then
        echo "  Extracting..."
        unzip -o "$SCANIA_DIR/scania.zip" -d "$SCANIA_DIR/"
        rm "$SCANIA_DIR/scania.zip"
        echo "  ✓ Scania dataset downloaded to data/02_scania/raw/"
    else
        rm -f "$SCANIA_DIR/scania.zip"
        echo ""
        echo "  ⚠️  Download failed. Get Scania dataset manually:"
        echo "     https://archive.ics.uci.edu/dataset/421/aps+failure+at+scania+trucks"
        echo "     Extract to: data/02_scania/raw/"
    fi
fi

# Expected files:
#   aps_failure_training_set.csv  (60,000 rows × 171 cols, ~170 MB)
#   aps_failure_test_set.csv      (16,000 rows × 171 cols)

# ──────────────────────────────────────────────────────
# 3. Casting Product Defect Detection - Computer Vision
# ──────────────────────────────────────────────────────
echo ""
echo "[3/3] Casting Product Quality Control Dataset (Kaggle)"
DEFECTS_DIR="$BASE/defects/raw"
mkdir -p "$DEFECTS_DIR"

if [ -d "$DEFECTS_DIR/casting_512x512" ] || [ -d "$DEFECTS_DIR/train" ]; then
    echo "  ✓ Already downloaded, skipping."
else
    if command -v kaggle &> /dev/null; then
        echo "  Downloading via Kaggle CLI..."
        kaggle datasets download \
            -d ravirajsinh45/real-life-industrial-dataset-of-casting-product \
            -p "$DEFECTS_DIR" --unzip
        echo "  ✓ Casting dataset downloaded to data/defects/raw/"
    else
        echo ""
        echo "  ⚠️  kaggle CLI not found. Install it:"
        echo "     pip install kaggle"
        echo "     cp ~/Downloads/kaggle.json ~/.kaggle/kaggle.json"
        echo "     chmod 600 ~/.kaggle/kaggle.json"
        echo ""
        echo "  Or download manually:"
        echo "  https://www.kaggle.com/datasets/ravirajsinh45/real-life-industrial-dataset-of-casting-product"
        echo "  Extract to: data/defects/raw/"
    fi
fi

# Expected structure:
#   casting_512x512/train/ok/         ~2312 images
#   casting_512x512/train/def_front/  ~2875 images
#   casting_512x512/test/ok/          ~262 images
#   casting_512x512/test/def_front/   ~300 images

echo ""
echo "=============================================="
echo "  Summary of data/:"
echo ""
ls -lh "$BASE/cmapss/raw/" 2>/dev/null | head -6 || echo "  cmapss/raw/ - empty"
ls -lh "$BASE/scania/raw/" 2>/dev/null | head -6 || echo "  scania/raw/ - empty"
ls -lh "$BASE/defects/raw/" 2>/dev/null | head -6 || echo "  defects/raw/ - empty"
echo "=============================================="
