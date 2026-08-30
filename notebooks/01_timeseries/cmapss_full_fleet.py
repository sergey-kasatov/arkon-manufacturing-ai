"""CMAPSS RUL model trained on the full fleet: FD001, FD002, FD003 and FD004.

Notebooks 01 to 03 build the baseline on FD001 alone, which is the easiest of
the four subsets: one operating condition and one fault mode. That baseline
stays as the comparison point. This script trains one model across all four
subsets, which is what the Arkon story claims - a single steering cell for a
mixed fleet - and it is a harder problem.

Two things in the FD001 pipeline do not survive the move, both verified against
the data rather than assumed:

  1. The dropped-sensor list. Notebook 02 drops s1, s5, s6, s10, s16, s18, s19
     as "flat". Across the full fleet, only s1, s5, s18 and s19 have zero
     variance inside every operating regime; s6, s10 and s16 vary and are kept.
  2. Normalisation. A single global scaler is wrong once six operating regimes
     are present: sensor readings shift with the regime, and global scaling
     flattens the within-regime degradation signal that carries the RUL
     information. Each regime is scaled on its own statistics here.

Reporting is deliberately split two ways, because a single headline number
would flatter the model:
  - all test rows, which is what notebook 03 reports, and
  - the last cycle of each test unit, which is the CMAPSS benchmark task and
    the only figure comparable with published results.

Run from the repository root:  python notebooks/01_timeseries/cmapss_full_fleet.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

# Paths and constants
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "01_cmapss" / "raw" / "CMaps"
PROC_DIR = PROJECT_ROOT / "data" / "01_cmapss" / "processed"
CKPT_DIR = PROJECT_ROOT / "models" / "checkpoints" / "cmapss"
SUBSETS = ["FD001", "FD002", "FD003", "FD004"]
RUL_CAP = 125  # piecewise linear RUL, standard for CMAPSS
WINDOW = 20  # cycles per rolling window; see the ablation at the end of the run

COLUMNS = ["unit", "cycle", "os_1", "os_2", "os_3"] + [f"s{i}" for i in range(1, 22)]
SENSORS = [f"s{i}" for i in range(1, 22)]

XGB_PARAMS = {
    "n_estimators": 600,
    "max_depth": 8,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "n_jobs": -1,
    "tree_method": "hist",
}


def load_subset(name):
    """Load one subset and attach the true RUL to every row."""
    train = pd.read_csv(RAW_DIR / f"train_{name}.txt", sep=r"\s+", header=None, names=COLUMNS)
    test = pd.read_csv(RAW_DIR / f"test_{name}.txt", sep=r"\s+", header=None, names=COLUMNS)
    rul = pd.read_csv(RAW_DIR / f"RUL_{name}.txt", header=None, names=["RUL"])

    # Train: every engine runs to failure, so RUL counts down from the last cycle.
    last = train.groupby("unit")["cycle"].max().rename("max_cycle")
    train = train.merge(last, on="unit")
    train["RUL"] = (train["max_cycle"] - train["cycle"]).clip(upper=RUL_CAP)
    train = train.drop(columns="max_cycle")

    # Test: the series stops before failure, so the remaining RUL comes from the
    # provided file and is added to the countdown.
    last = test.groupby("unit")["cycle"].max().rename("max_cycle").reset_index()
    last["rul_at_end"] = rul["RUL"].values
    test = test.merge(last, on="unit")
    test["RUL"] = (test["rul_at_end"] + test["max_cycle"] - test["cycle"]).clip(upper=RUL_CAP)
    test["is_last_cycle"] = test["cycle"] == test["max_cycle"]
    test = test.drop(columns=["max_cycle", "rul_at_end"])

    # Unit ids repeat across subsets, so make them unique before concatenating.
    for frame in (train, test):
        frame["dataset"] = name
        frame["unit_uid"] = name + "_" + frame["unit"].astype(str)
    return train, test


def assign_regime(df):
    """Label the operating regime from the three operating settings.

    Rounding separates the six regimes exactly in FD002 and FD004, and puts
    FD001 and FD003 into the first of them, so no clustering is needed.
    """
    key = (
        df["os_1"].round(0).astype(int).astype(str)
        + "_"
        + df["os_2"].round(0).astype(int).astype(str)
        + "_"
        + df["os_3"].round(0).astype(int).astype(str)
    )
    return key


def evaluate(y_true, y_pred, label):
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae = float(mean_absolute_error(y_true, y_pred))
    r2 = float(r2_score(y_true, y_pred))
    print(f"  {label:28} RMSE {rmse:7.3f}   MAE {mae:7.3f}   R2 {r2:7.4f}   n={len(y_true):,}")
    return {"rmse": rmse, "mae": mae, "r2": r2, "n": int(len(y_true))}


def main():
    if not RAW_DIR.exists():
        sys.exit(f"CMAPSS raw data not found at {RAW_DIR}")
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    CKPT_DIR.mkdir(parents=True, exist_ok=True)

    # Load and combine all four subsets
    print("Loading subsets")
    trains, tests = [], []
    for name in SUBSETS:
        tr, te = load_subset(name)
        print(f"  {name}: train {len(tr):>7,} rows / {tr['unit'].nunique():>3} units"
              f"   test {len(te):>7,} rows / {te['unit'].nunique():>3} units")
        trains.append(tr)
        tests.append(te)
    train = pd.concat(trains, ignore_index=True)
    test = pd.concat(tests, ignore_index=True)
    print(f"  combined: train {len(train):,} rows, test {len(test):,} rows")

    # Identify operating regimes
    train["regime"] = assign_regime(train)
    test["regime"] = assign_regime(test)
    regimes = sorted(train["regime"].unique())
    print(f"\nOperating regimes found: {len(regimes)}")
    for r in regimes:
        n_tr = int((train["regime"] == r).sum())
        subsets_here = ", ".join(sorted(train.loc[train["regime"] == r, "dataset"].unique()))
        print(f"  {r:>12}  {n_tr:>7,} train rows   ({subsets_here})")

    # Drop sensors that are constant inside every regime - they cannot carry
    # degradation information. Derived from train only.
    within_regime_std = train.groupby("regime")[SENSORS].std().max()
    drop_sensors = [s for s in SENSORS if within_regime_std[s] < 1e-9]
    keep_sensors = [s for s in SENSORS if s not in drop_sensors]
    print(f"\nSensors dropped (zero variance in every regime): {drop_sensors}")
    print(f"Sensors kept: {len(keep_sensors)}")
    fd001_list = ["s1", "s5", "s6", "s10", "s16", "s18", "s19"]
    print(f"  note: the FD001-only pipeline also drops {sorted(set(fd001_list) - set(drop_sensors))}, "
          f"which do vary across the fleet")

    # Per-regime standardisation, fit on train only. Sensor columns are cast to
    # float first: several arrive as int64 and assigning scaled values into an
    # integer column is deprecated in pandas.
    print("\nScaling sensors within each operating regime")
    train[keep_sensors] = train[keep_sensors].astype("float64")
    test[keep_sensors] = test[keep_sensors].astype("float64")
    scalers = {}
    for r in regimes:
        m_tr = train["regime"] == r
        scaler = StandardScaler()
        train.loc[m_tr, keep_sensors] = scaler.fit_transform(train.loc[m_tr, keep_sensors])
        m_te = test["regime"] == r
        if m_te.any():
            test.loc[m_te, keep_sensors] = scaler.transform(test.loc[m_te, keep_sensors])
        scalers[r] = scaler

    # A test regime unseen in train would leave raw values in place; fail loudly
    # rather than train on a silent mix of scaled and unscaled rows.
    unseen = set(test["regime"].unique()) - set(regimes)
    if unseen:
        sys.exit(f"Test data contains operating regimes absent from train: {unseen}")

    # Feature matrix: scaled sensors, the cycle counter, the regime code, and
    # temporal features derived per engine.
    #
    # The temporal features are the point of this module. Without them the model
    # sees one snapshot at a time and has no way to observe a trajectory, so it
    # leans on the raw cycle counter as its only proxy for elapsed time. That is
    # tabular regression on time-indexed rows, not time-series modelling, and it
    # is fragile: a real fleet resets its cycle counter after an overhaul.
    #
    # Each feature is computed inside one engine's own history and uses only past
    # and current cycles, so no future information leaks backwards.
    regime_code = {r: i for i, r in enumerate(regimes)}
    for frame in (train, test):
        frame["regime_code"] = frame["regime"].map(regime_code)

    print(f"\nBuilding temporal features over a {WINDOW}-cycle window")
    temporal_cols = []
    for frame in (train, test):
        frame.sort_values(["unit_uid", "cycle"], inplace=True)
        grouped = frame.groupby("unit_uid", sort=False)[keep_sensors]
        # Rolling mean smooths sensor noise and gives the current level.
        roll_mean = grouped.rolling(WINDOW, min_periods=1).mean().reset_index(level=0, drop=True)
        # Rolling std is the volatility of the signal, which rises near failure.
        roll_std = grouped.rolling(WINDOW, min_periods=1).std().reset_index(level=0, drop=True).fillna(0.0)
        # Difference from the engine's own first cycles: how far it has drifted
        # from its own healthy baseline, which removes unit-to-unit variation.
        baseline = grouped.transform(lambda s: s.iloc[:WINDOW].mean())
        for name, block in [("mean", roll_mean), ("std", roll_std), ("drift", frame[keep_sensors] - baseline)]:
            block = block.add_suffix(f"_{name}{WINDOW}")
            frame[block.columns] = block
            if not temporal_cols or not any(c.endswith(f"_{name}{WINDOW}") for c in temporal_cols):
                temporal_cols.extend(block.columns.tolist())

    feature_cols = keep_sensors + ["cycle", "regime_code"] + temporal_cols
    print(f"  {len(temporal_cols)} temporal features added "
          f"(rolling mean, rolling std, drift from own baseline)")

    X_train = train[feature_cols].to_numpy()
    y_train = train["RUL"].to_numpy()
    X_test = test[feature_cols].to_numpy()
    y_test = test["RUL"].to_numpy()
    print(f"Feature matrix: {X_train.shape[1]} features, {X_train.shape[0]:,} training rows")

    results = {}
    models = {}
    for label, model in [
        ("linear_regression", LinearRegression()),
        ("xgboost", XGBRegressor(**XGB_PARAMS)),
    ]:
        print(f"\n=== {label} ===")
        model.fit(X_train, y_train)
        models[label] = model
        pred = model.predict(X_test)

        res = {"all_rows": evaluate(y_test, pred, "all test rows")}

        # The benchmark task: one prediction per engine, at its last cycle.
        last_mask = test["is_last_cycle"].to_numpy()
        res["last_cycle"] = evaluate(y_test[last_mask], pred[last_mask], "last cycle per unit")

        # Per subset, so the easy and hard subsets are not averaged into silence.
        # All-rows is reported per subset as well, because that is the only
        # figure directly comparable with the FD001-only baseline in notebook 03.
        res["per_subset"] = {}
        for name in SUBSETS:
            in_subset = (test["dataset"] == name).to_numpy()
            res["per_subset"][name] = {
                "all_rows": evaluate(y_test[in_subset], pred[in_subset], f"{name} all rows"),
                "last_cycle": evaluate(
                    y_test[in_subset & last_mask], pred[in_subset & last_mask],
                    f"{name} last cycle"
                ),
            }
        results[label] = res

    # Ablation: does the extra data help, or was it the hyperparameters?
    # Both arms use the notebook-03 hyperparameters and this script's per-regime
    # preprocessing, and both are scored on the FD001 test set, so the only
    # difference left is what the model was trained on.
    print("\n=== ablation: FD001-only vs full fleet, identical settings ===")
    baseline_params = {**XGB_PARAMS, "n_estimators": 300, "max_depth": 6}
    fd001_train = (train["dataset"] == "FD001").to_numpy()
    fd001_test = (test["dataset"] == "FD001").to_numpy()
    ablation = {"hyperparameters": baseline_params}
    for arm, mask in [("trained_on_FD001_only", fd001_train),
                      ("trained_on_full_fleet", np.ones(len(train), dtype=bool))]:
        m = XGBRegressor(**baseline_params)
        m.fit(X_train[mask], y_train[mask])
        p = m.predict(X_test[fd001_test])
        ablation[arm] = {
            "train_rows": int(mask.sum()),
            "all_rows": evaluate(y_test[fd001_test], p, f"{arm} -> FD001 all rows"),
            "last_cycle": evaluate(
                y_test[fd001_test & last_mask], m.predict(X_test[fd001_test & last_mask]),
                f"{arm} -> FD001 last cycle"
            ),
        }
    delta = (ablation["trained_on_FD001_only"]["all_rows"]["rmse"]
             - ablation["trained_on_full_fleet"]["all_rows"]["rmse"])
    print(f"  RMSE change on FD001 from adding the other three subsets: {delta:+.3f}")
    ablation["fd001_all_rows_rmse_delta"] = delta

    # Feature ablation: does treating this as a time series actually pay?
    # Snapshot features alone reduce the module to tabular regression on
    # time-indexed rows, with the raw cycle counter as the only view of time.
    print("\n=== ablation: temporal features, whole fleet ===")
    idx = {c: i for i, c in enumerate(feature_cols)}
    arms = {
        "sensors_only": [idx[c] for c in keep_sensors + ["regime_code"]],
        "sensors_plus_cycle": [idx[c] for c in keep_sensors + ["cycle", "regime_code"]],
        "with_temporal_features": list(range(len(feature_cols))),
    }
    feature_ablation = {"window": WINDOW, "hyperparameters": baseline_params}
    for arm, cols in arms.items():
        m = XGBRegressor(**baseline_params)
        m.fit(X_train[:, cols], y_train)
        feature_ablation[arm] = {
            "n_features": len(cols),
            "all_rows": evaluate(y_test, m.predict(X_test[:, cols]), f"{arm} (all rows)"),
            "last_cycle": evaluate(y_test[last_mask], m.predict(X_test[last_mask][:, cols]),
                                   f"{arm} (last cycle)"),
        }
    gain = (feature_ablation["sensors_plus_cycle"]["last_cycle"]["rmse"]
            - feature_ablation["with_temporal_features"]["last_cycle"]["rmse"])
    print(f"  RMSE change on the benchmark task from the temporal features: {gain:+.3f}")
    feature_ablation["temporal_rmse_gain_last_cycle"] = gain

    # Persist artifacts
    print("\nSaving artifacts")
    import joblib

    joblib.dump({"scalers": scalers, "regimes": regimes, "keep_sensors": keep_sensors,
                 "feature_cols": feature_cols, "rul_cap": RUL_CAP},
                PROC_DIR / "preprocessing_full_fleet.pkl")
    for label, model in models.items():
        joblib.dump(model, CKPT_DIR / f"cmapss_{label}_full_fleet.pkl")

    meta = {
        "trained_on": SUBSETS,
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_units": int(train["unit_uid"].nunique()),
        "test_units": int(test["unit_uid"].nunique()),
        "operating_regimes": len(regimes),
        "sensors_dropped": drop_sensors,
        "sensors_kept": keep_sensors,
        "features": feature_cols,
        "rul_cap": RUL_CAP,
        "normalisation": "StandardScaler fit per operating regime on train only",
        "xgb_params": XGB_PARAMS,
        "window": WINDOW,
        "results": results,
        "ablation": ablation,
        "feature_ablation": feature_ablation,
    }
    (CKPT_DIR / "cmapss_full_fleet_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    train.to_csv(PROC_DIR / "train_full_fleet_processed.csv", index=False)
    test.to_csv(PROC_DIR / "test_full_fleet_processed.csv", index=False)

    # Prediction table for the risk-event adapter. Only the columns the adapter
    # needs, so it does not have to carry 70 feature columns around.
    preds = test[["dataset", "unit", "cycle", "RUL", "is_last_cycle"]].copy()
    preds["pred_RUL"] = models["xgboost"].predict(X_test)
    preds.to_csv(PROC_DIR / "test_full_fleet_predictions.csv", index=False)
    print(f"  preds   -> {PROC_DIR / 'test_full_fleet_predictions.csv'}")
    print(f"  models  -> {CKPT_DIR}")
    print(f"  data    -> {PROC_DIR}")
    print(f"  metrics -> {CKPT_DIR / 'cmapss_full_fleet_meta.json'}")


if __name__ == "__main__":
    main()
