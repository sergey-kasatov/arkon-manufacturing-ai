"""Scania APS failure classification: the Arkon tabular module.

Module 02 of the Arkon platform. A binary classifier over 170 anonymised
operational counters from heavy trucks, predicting whether a service issue
belongs to the air pressure system. It feeds the Quality Steering Cell through
the risk event adapter, exactly as the CMAPSS module does.

The whole point of this module, and the reason it is worth building beside
CMAPSS rather than instead of it, is in the dataset's own challenge metric:

    cost = 10 * false positives + 500 * false negatives

An unnecessary workshop check costs 10. A missed faulty truck costs 500. That is
a fifty to one asymmetry, and it is the exact thing the CMAPSS model card names
as limitation 5 and does not address: RMSE punishes both directions equally
while the business does not. Here the asymmetry IS the metric, so the decision
threshold is a real decision.

## How the shipped configuration is chosen

Four candidates, from two binary choices that both looked obvious in advance and
were both worth measuring:

  - **missing values**: kept as NaN so XGBoost learns a default direction per
    split, or filled with the training median.
  - **class weighting**: `scale_pos_weight` on, or off.

Every candidate gets its threshold tuned the same way, and the winner is picked
on **out-of-fold cost**, never on the test set. Five-fold stratified
cross-validation on the training rows produces one out-of-fold probability per
row; the threshold that minimises cost on those is the candidate's threshold,
and the cost at that threshold is its score. The model then refits on all the
training rows and that threshold is applied to the test set once.

A single validation split was the first design and it was replaced: the positive
class is 1.7 percent of the rows, so one split's cost-optimal threshold is a
noisy estimate, and the choice being made here is exactly a choice of threshold.

The folds are stratified for the same reason: an unstratified fold can end up
with almost no failures in it.

## What the run reports

Total cost is the headline because it is the challenge metric and the business
one, but it is never reported alone. Two models with the same cost can be very
different to work next to, so the false positive and false negative counts that
produce it are printed beside it. The ablation also prints what an unconsidered
pipeline gets, meaning the default 0.5 threshold, because the gap between that
and a tuned threshold is this module's whole argument.

Run from the repository root:  python notebooks/02_ml/scania_aps.py
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

# Paths and constants
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "02_scania" / "raw"
PROC_DIR = PROJECT_ROOT / "data" / "02_scania" / "processed"
CKPT_DIR = PROJECT_ROOT / "models" / "checkpoints" / "scania"

# The raw files carry a 20-line licence header before the CSV header row.
HEADER_LINES = 20
SEED = 42
FOLDS = 5

# The challenge metric, from data/02_scania/raw/aps_failure_description.txt.
COST_FALSE_POSITIVE = 10   # an unnecessary check by a mechanic
COST_FALSE_NEGATIVE = 500  # a missed faulty truck, which may break down

XGB_PARAMS = {
    "n_estimators": 600,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": SEED,
    "n_jobs": -1,
    "tree_method": "hist",
    "eval_metric": "aucpr",
}

CANDIDATES = [
    ("nan_weighted", False, True),
    ("nan_plain", False, False),
    ("imputed_weighted", True, True),
    ("imputed_plain", True, False),
]


def load(name):
    """Load one raw file. Missing values stay NaN; the label becomes 0/1."""
    frame = pd.read_csv(RAW_DIR / name, skiprows=HEADER_LINES, na_values="na",
                        low_memory=False)
    y = (frame["class"] == "pos").astype(int).to_numpy()
    X = frame.drop(columns=["class"]).astype("float64")
    return X, y


def counts(y_true, y_pred):
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "cost": int(COST_FALSE_POSITIVE * fp + COST_FALSE_NEGATIVE * fn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "true_positives": int(tp),
        "true_negatives": int(tn),
    }


def best_threshold(y_true, scores):
    """The probability cut that minimises cost on these scores.

    Every distinct score is a candidate boundary, so the search is exact rather
    than a grid. A fixed grid can miss the optimum when the scores cluster,
    which they do here because most trucks are obviously healthy.
    """
    order = np.argsort(-scores)
    labels = y_true[order]
    positives = int(labels.sum())
    true_positives = np.concatenate([[0], np.cumsum(labels)])
    predicted = np.arange(len(labels) + 1)
    false_positives = predicted - true_positives
    false_negatives = positives - true_positives
    costs = COST_FALSE_POSITIVE * false_positives + COST_FALSE_NEGATIVE * false_negatives
    k = int(np.argmin(costs))
    sorted_scores = scores[order]
    if k == 0:
        cut = float(sorted_scores[0]) + 1e-9
    elif k >= len(sorted_scores):
        cut = float(sorted_scores[-1])
    else:
        cut = float((sorted_scores[k - 1] + sorted_scores[k]) / 2)
    return cut, int(costs[k])


def evaluate(y_true, scores, threshold):
    result = counts(y_true, (scores >= threshold).astype(int))
    result["threshold"] = round(float(threshold), 6)
    result["roc_auc"] = round(float(roc_auc_score(y_true, scores)), 4)
    result["pr_auc"] = round(float(average_precision_score(y_true, scores)), 4)
    hits = result["true_positives"] + result["false_positives"]
    result["precision"] = round(result["true_positives"] / hits, 4) if hits else 0.0
    result["recall"] = round(
        result["true_positives"] / (result["true_positives"] + result["false_negatives"]), 4)
    return result


def make_model(weighted, y):
    params = dict(XGB_PARAMS)
    if weighted:
        params["scale_pos_weight"] = float((y == 0).sum() / max((y == 1).sum(), 1))
    return XGBClassifier(**params)


def out_of_fold_scores(X, y, weighted):
    """One probability per training row, from a model that never saw that row."""
    scores = np.zeros(len(y), dtype=float)
    splitter = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED)
    for train_index, test_index in splitter.split(X, y):
        model = make_model(weighted, y[train_index])
        model.fit(X.iloc[train_index], y[train_index])
        scores[test_index] = model.predict_proba(X.iloc[test_index])[:, 1]
    return scores


def main():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    CKPT_DIR.mkdir(parents=True, exist_ok=True)

    X_train, y_train = load("aps_failure_training_set.csv")
    X_test, y_test = load("aps_failure_test_set.csv")
    features = list(X_train.columns)
    print("train %s, test %s, %d features" % (X_train.shape, X_test.shape, len(features)))
    print("positives: train %d (%.2f%%), test %d (%.2f%%)"
          % (y_train.sum(), 100 * y_train.mean(), y_test.sum(), 100 * y_test.mean()))
    missing = float(X_train.isna().to_numpy().mean())
    worst = X_train.isna().mean().sort_values(ascending=False)
    print("missing cells: %.1f%% overall, worst column %s at %.1f%%"
          % (100 * missing, worst.index[0], 100 * worst.iloc[0]))

    # Imputation is fitted on the training rows only and reused everywhere.
    imputer = SimpleImputer(strategy="median").fit(X_train)
    imputed_train = pd.DataFrame(imputer.transform(X_train), columns=features)
    imputed_test = pd.DataFrame(imputer.transform(X_test), columns=features)

    print("\nselection, out-of-fold over %d stratified folds" % FOLDS)
    selection = {}
    for name, impute, weighted in CANDIDATES:
        data = imputed_train if impute else X_train
        scores = out_of_fold_scores(data, y_train, weighted)
        threshold, oof_cost = best_threshold(y_train, scores)
        selection[name] = {
            "median_imputation": impute,
            "class_weighting": weighted,
            "threshold": round(threshold, 6),
            "out_of_fold_cost": oof_cost,
            "out_of_fold_pr_auc": round(float(average_precision_score(y_train, scores)), 4),
        }
        print("  %-20s out-of-fold cost %6d   threshold %.6f" % (name, oof_cost, threshold))

    chosen = min(selection, key=lambda k: selection[k]["out_of_fold_cost"])
    impute, weighted = selection[chosen]["median_imputation"], selection[chosen]["class_weighting"]
    threshold = selection[chosen]["threshold"]
    print("chosen on out-of-fold cost: %s" % chosen)

    # Refit the winner on every training row and score the test set once.
    fit_data = imputed_train if impute else X_train
    score_data = imputed_test if impute else X_test
    model = make_model(weighted, y_train)
    model.fit(fit_data, y_train)
    test_scores = model.predict_proba(score_data)[:, 1]
    primary = evaluate(y_test, test_scores, threshold)
    print("TEST  cost %d  FP %d  FN %d  recall %.4f  PR-AUC %.4f"
          % (primary["cost"], primary["false_positives"], primary["false_negatives"],
             primary["recall"], primary["pr_auc"]))

    # Ablation. Every candidate scored on the test set, plus the two contrasts
    # that carry the argument: the default 0.5 threshold, and a linear baseline.
    print("\nablation, test set")
    ablation = {}
    for name, impute_i, weighted_i in CANDIDATES:
        fit_i = imputed_train if impute_i else X_train
        score_i = imputed_test if impute_i else X_test
        model_i = model if name == chosen else make_model(weighted_i, y_train).fit(fit_i, y_train)
        scores_i = test_scores if name == chosen else model_i.predict_proba(score_i)[:, 1]
        ablation[name] = evaluate(y_test, scores_i, selection[name]["threshold"])
        if name == chosen:
            ablation[name + "__default_threshold_0.5"] = evaluate(y_test, scores_i, 0.5)

    # A logistic-regression baseline: the counterpart of the linear regression in
    # the CMAPSS module. It says whether the gradient boosting is doing real work.
    scaler = StandardScaler().fit(imputed_train)
    linear = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED)
    linear.fit(scaler.transform(imputed_train), y_train)
    linear_oof = np.zeros(len(y_train), dtype=float)
    splitter = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED)
    for train_index, test_index in splitter.split(imputed_train, y_train):
        fold = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED)
        fold.fit(scaler.transform(imputed_train.iloc[train_index]), y_train[train_index])
        linear_oof[test_index] = fold.predict_proba(
            scaler.transform(imputed_train.iloc[test_index]))[:, 1]
    linear_threshold, _ = best_threshold(y_train, linear_oof)
    ablation["logistic_regression"] = evaluate(
        y_test, linear.predict_proba(scaler.transform(imputed_test))[:, 1], linear_threshold)

    for name, result in ablation.items():
        print("  %-38s cost %6d   FP %5d   FN %4d   recall %.4f"
              % (name, result["cost"], result["false_positives"],
                 result["false_negatives"], result["recall"]))

    # Persist: the model, the preprocessing the event adapter and any consumer
    # needs, the test predictions, and the metrics.
    joblib.dump(model, CKPT_DIR / "scania_xgboost_v1.pkl")
    joblib.dump({"imputer": imputer if impute else None, "scaler": scaler,
                 "features": features, "median_imputation": impute,
                 "threshold": threshold},
                PROC_DIR / "preprocessing_scania.pkl")

    pd.DataFrame({
        "row_id": np.arange(len(y_test)),
        "true_class": y_test,
        "failure_probability": test_scores,
        "predicted_class": (test_scores >= threshold).astype(int),
    }).to_csv(PROC_DIR / "test_scania_predictions.csv", index=False)

    meta = {
        "dataset": "APS Failure at Scania Trucks, IDA 2016 Industrial Challenge",
        "train_rows": int(len(y_train)),
        "test_rows": int(len(y_test)),
        "features": len(features),
        "positives_train": int(y_train.sum()),
        "positives_test": int(y_test.sum()),
        "missing_cell_fraction": round(missing, 4),
        "cost_false_positive": COST_FALSE_POSITIVE,
        "cost_false_negative": COST_FALSE_NEGATIVE,
        "folds": FOLDS,
        "selection_rule": "lowest out-of-fold cost over the training rows; the test set is scored once",
        "chosen": chosen,
        "chosen_threshold": round(threshold, 6),
        "selection": selection,
        "results": ablation,
        "xgb_params": XGB_PARAMS,
        "published_reference": {
            "note": "Top three of the IDA 2016 challenge, from the dataset description",
            "best_total_cost": 9920,
            "second": 10900,
            "third": 11480,
        },
    }
    (CKPT_DIR / "scania_aps_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print("\nwrote %s" % (CKPT_DIR / "scania_aps_meta.json").relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
