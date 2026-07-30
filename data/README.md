# Arkon Manufacturing AI - Datasets

All three datasets represent different departments of the fictional **Arkon Manufacturing** factory.

---

## 1. NASA CMAPSS - Engine Health Monitoring (Time Series)
**Department:** Arkon Power Systems - Turbine Maintenance Division

| Property | Value |
|---|---|
| Source | [NASA Prognostics Data Repository](https://data.nasa.gov/Aerospace/CMAPSS-Jet-Engine-Simulated-Data/ff5v-kuh6) |
| License | Public Domain (NASA) |
| Folder | `data/01_cmapss/raw/` |
| Format | Fixed-width text (space-separated) |
| Size | ~12 MB total |

**Contents:**
- 4 sub-datasets (FD001–FD004), each with train/test/RUL files
- 21 sensor measurements + 3 operational settings per engine cycle
- Training: run-to-failure sequences; Test: truncated sequences
- Labels: Remaining Useful Life (RUL) in cycles

**Sub-datasets:**
| ID | Train engines | Test engines | Conditions | Fault modes |
|---|---|---|---|---|
| FD001 | 100 | 100 | 1 | 1 (HPC degradation) |
| FD002 | 260 | 259 | 6 | 1 |
| FD003 | 100 | 100 | 1 | 2 |
| FD004 | 249 | 248 | 6 | 2 |

**Project use:** Predict RUL (Remaining Useful Life) for each engine → LSTM/XGBoost time series model.

---

## 2. APS Failure at Scania Trucks - Pneumatic System (ML Classification)
**Department:** Arkon Fleet Services - Predictive Maintenance Unit

| Property | Value |
|---|---|
| Source | [UCI ML Repository #421](https://archive.ics.uci.edu/dataset/421/aps+failure+at+scania+trucks) |
| License | CC BY 4.0 |
| Folder | `data/02_scania/raw/` |
| Format | CSV |
| Size | ~198 MB (train) + ~28 MB (test) |

**Contents:**
- `aps_failure_training_set.csv`: 60,000 rows × 171 features
- `aps_failure_test_set.csv`: 16,000 rows × 171 features
- Binary classification: `neg` (no failure) vs `pos` (APS failure)
- Heavy class imbalance: ~1.67% positive class
- Many missing values encoded as `na`

**Cost matrix (from UCI):**
- False Negative (miss a failure): cost = 500
- False Positive (unnecessary check): cost = 10

**Project use:** Cost-sensitive binary classifier (XGBoost + threshold tuning) to minimize total maintenance cost.

---

## 3. Casting Product Quality Inspection - Computer Vision
**Department:** Arkon Foundry - Visual QC Line

| Property | Value |
|---|---|
| Source | [Kaggle - ravirajsinh45](https://www.kaggle.com/datasets/ravirajsinh45/real-life-industrial-dataset-of-casting-product) |
| License | CC0 Public Domain |
| Folder | `data/defects/raw/` |
| Format | JPEG images, 512×512 px |
| Size | ~1.5 GB |

**Contents:**
- Submersible pump impeller castings
- Binary classification: `ok` vs `def_front` (defective)
- Train: 2312 ok + 2875 defective images
- Test: 262 ok + 300 defective images

**Project use:** CNN (EfficientNet/ResNet) fine-tuned to detect surface defects → deployed in Streamlit CV module.

---

## Setup

```bash
# Run from project root to download all datasets:
chmod +x data/download_datasets.sh
./data/download_datasets.sh

# For CV dataset, install kaggle CLI first:
pip install kaggle
# Copy ~/.kaggle/kaggle.json  (from kaggle.com -> Settings -> API)
```

## Folder Structure

```
data/
├── cmapss/
│   ├── raw/          ← train_FD00*.txt, test_FD00*.txt, RUL_FD00*.txt
│   └── processed/    ← engineered features, normalized, train/val splits
├── scania/
│   ├── raw/          ← aps_failure_training_set.csv, aps_failure_test_set.csv
│   └── processed/    ← imputed, scaled, balanced
└── defects/
    ├── raw/          ← casting_512x512/ (original Kaggle structure)
    ├── train/        ← ok/ + defective/ (symlinks or copies)
    └── test/         ← ok/ + defective/
```
