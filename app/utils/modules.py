"""The seven model modules, described once.

Every module page is the same page with a different entry from this table, so a
module is added by writing a row rather than by writing a file. The numbers are
read out of the tracked `*_meta.json` files at render time and never typed here:
a figure copied into a display is a figure that goes stale silently, which is the
failure this project keeps meeting in its own documents.

The `caveat` field is not decoration either. Every headline number in this
project has one sentence that has to travel with it, and a dashboard is exactly
where that sentence gets dropped.
"""

import functools
import json

from utils import config


def _get(data, path, default=None):
    """Read a dotted path out of a nested dict."""
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


@functools.lru_cache(maxsize=None)
def meta(key):
    """The tracked metrics file for one module, or {} if it is not in the tree."""
    module = MODULES[key]
    path = config.CHECKPOINTS / module["meta"]
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def headline(key):
    """The module's headline numbers as (label, formatted value) pairs."""
    data = meta(key)
    rows = []
    for label, path, fmt in MODULES[key]["headline"]:
        value = _get(data, path)
        if value is None:
            rows.append((label, "not in the metrics file"))
        elif isinstance(value, bool):
            # Before the number check: bool is an int in Python, so True would
            # otherwise arrive at a numeric format string as 1.
            rows.append((label, "yes" if value else "no"))
        elif isinstance(value, list):
            rows.append((label, ", ".join(str(v) for v in value)))
        elif fmt is None:
            rows.append((label, str(value)))
        else:
            rows.append((label, fmt.format(value)))
    return rows


def figures(key):
    """Every tracked figure belonging to this module, in file-name order."""
    module = MODULES[key]
    folder = config.ASSETS / module["figures"][0]
    if not folder.exists():
        return []
    return sorted(p for p in folder.glob(module["figures"][1] + "*.png"))


def card_path(key):
    return config.DOCS / MODULES[key]["card"]


def events_path(key):
    return config.EVENTS / MODULES[key]["events"]


# The table. Order is the order the modules were built, which is also the order
# the charter tells the story in.
MODULES = {
    "cmapss": {
        "title": "Engine remaining useful life",
        "icon": "gear",
        "source_module": "cmapss_rul",
        "business_domain": "asset_reliability",
        "dataset": "NASA CMAPSS, four subsets, 709 training and 707 test engines",
        "task": "Regression on remaining cycles",
        "meta": "cmapss/cmapss_full_fleet_meta.json",
        "card": "Model_Card_CMAPSS_RUL.md",
        "figures": ("timeseries", ""),
        "events": "cmapss_events_full_fleet.jsonl",
        "headline": [
            ("RMSE, benchmark task", "results.xgboost.last_cycle.rmse", "{:.2f}"),
            ("MAE, benchmark task", "results.xgboost.last_cycle.mae", "{:.2f}"),
            ("R2, benchmark task", "results.xgboost.last_cycle.r2", "{:.3f}"),
            ("Engines scored", "results.xgboost.last_cycle.n", "{:,}"),
            ("RMSE, all test rows", "results.xgboost.all_rows.rmse", "{:.2f}"),
            ("Rows scored", "results.xgboost.all_rows.n", "{:,}"),
        ],
        "caveat": "The three RMSE figures are not on one basis. The benchmark task is one "
                  "prediction per engine at its last observed cycle; the second is every test "
                  "row. The whole gain is in the temporal features, worth 5.32 RMSE on the "
                  "benchmark task against 1.67 for the cycle counter.",
    },
    "scania": {
        "title": "Truck air pressure system faults",
        "icon": "truck",
        "source_module": "scania_aps",
        "business_domain": "fleet_reliability",
        "dataset": "APS Failure at Scania Trucks, IDA 2016 challenge, 170 features",
        "task": "Binary classification under an asymmetric cost",
        "meta": "scania/scania_aps_meta.json",
        "card": "Model_Card_Scania_APS.md",
        "figures": ("ml", ""),
        "events": "scania_events.jsonl",
        "headline": [
            ("Total cost, the dataset's own metric", "results.nan_plain.cost", "{:,}"),
            ("Recall", "results.nan_plain.recall", "{:.4f}"),
            ("ROC AUC", "results.nan_plain.roc_auc", "{:.4f}"),
            ("Needless checks", "results.nan_plain.false_positives", "{:,}"),
            ("Missed failures", "results.nan_plain.false_negatives", "{:,}"),
            ("Best of the 2016 challenge", "published_reference.best_total_cost", "{:,}"),
        ],
        "caveat": "The cost is 10 per needless workshop check and 500 per missed failure, so "
                  "the decision threshold is worth a factor of 3.8 while every structural "
                  "choice sits inside the noise of the selection: three fold seeds produced "
                  "three different winners.",
    },
    "casting": {
        "title": "Casting defect inspection",
        "icon": "search",
        "source_module": "casting_cv",
        "business_domain": "visual_inspection",
        "dataset": "Casting product images, submersible pump impellers, front view",
        "task": "Binary image classification",
        "meta": "casting/casting_cv_meta.json",
        "card": "Model_Card_Casting_CV.md",
        "figures": ("cv", "casting"),
        "events": "casting_events.jsonl",
        "headline": [
            ("Recall at the shipped operating point", "operating_points.missed_defect_costs_25x.recall", "{:.4f}"),
            ("Defects missed", "operating_points.missed_defect_costs_25x.defects_missed", "{:,}"),
            ("Good parts rejected", "operating_points.missed_defect_costs_25x.good_parts_rejected", "{:,}"),
            ("ROC AUC", "operating_points.missed_defect_costs_25x.roc_auc", "{:.4f}"),
            ("Test images", "test_images", "{:,}"),
            ("Decision threshold", "operating_points.missed_defect_costs_25x.threshold", "{:.4f}"),
        ],
        # The metrics come from casting_cv_meta.json, the run the model card and
        # the charter quote and the run the events were built from. The sibling
        # casting_cv_notebook_meta.json is the 2026-09-01 notebook rebuild and
        # disagrees with it on exactly the fields that are known unstable:
        # threshold 0.0256 against 0.0637, and 15 good parts rejected against 7.
        # That disagreement is the caveat below, measured rather than argued.
        "caveat": "Two qualifications belong with the zero. The published test folder shares "
                  "64 byte-identical images with training, all of them good parts, so recall "
                  "is clean and the false-alarm rate is measured on a partly seen set. And "
                  "the operating point is not reproducible: four runs from one seed span 0 to "
                  "2 missed defects, so the zero is one draw rather than a guarantee.",
    },
    "neu": {
        "title": "Steel surface defect classification",
        "icon": "layers",
        "source_module": "neu_surface",
        "business_domain": "visual_inspection",
        "dataset": "NEU-DET, hot-rolled steel strip, six defect classes",
        "task": "Six-class image classification",
        "meta": "neu/neu_cv_meta.json",
        "card": "Model_Card_NEU_Surface.md",
        "figures": ("cv", "neu"),
        "events": "neu_events.jsonl",
        "headline": [
            ("Accuracy", "test_performance.accuracy", "{:.4f}"),
            ("Macro F1", "test_performance.macro_f1", "{:.4f}"),
            ("Errors", "test_performance.errors", "{:,}"),
            ("Images scored", "test_images", "{:,}"),
            ("1-NN on un-finetuned features", "benchmark_difficulty.one_nearest_neighbour_on_imagenet_features", "{:.4f}"),
            ("Chance", "benchmark_difficulty.chance", "{:.4f}"),
        ],
        "caveat": "The 1.0000 must not be quoted without the row under it. A 1-nearest-"
                  "neighbour classifier over un-finetuned ImageNet features reaches 0.9750 on "
                  "the same folder, so this benchmark is close to saturated. And 6.8 per cent "
                  "of images carry a second defect class the folder label discards, which is "
                  "a ceiling on any single-label model.",
    },
    "mvtec": {
        "title": "Component anomaly detection",
        "icon": "alert-triangle",
        "source_module": "mvtec_anomaly",
        "business_domain": "visual_inspection",
        "dataset": "MVTec AD, four categories: grid, metal_nut, screw, transistor",
        "task": "Unsupervised anomaly detection, fitted on sound parts only",
        "meta": "mvtec/mvtec_cv_meta.json",
        "card": "Model_Card_MVTec_Anomaly.md",
        "figures": ("cv", "mvtec"),
        "events": "mvtec_events.jsonl",
        "headline": [
            ("Mean image AUROC", "test_performance.mean_image_auroc", "{:.4f}"),
            ("Mean pixel AUROC", "test_performance.mean_pixel_auroc", "{:.4f}"),
            ("Categories", "categories", None),
            ("False-alarm budget", "operating_point.false_alarm_budget", "{:.0%}"),
            ("Reproduces exactly", "reproduction.exact", None),
            ("Trained", "trained", None),
        ],
        "caveat": "The four category rows matter more than the mean: they span 0.0350 from "
                  "0.9650 on screw to 1.0000 on metal_nut, and the realised false-alarm rate "
                  "spans 9.8 to 22.7 per cent against a declared budget of 5. This module "
                  "trains nothing: it stores feature vectors from sound parts and measures a "
                  "distance.",
    },
    "gc10": {
        "title": "Steel sheet defect detection",
        "icon": "crosshair",
        "source_module": "gc10_detect",
        "business_domain": "visual_inspection",
        "dataset": "GC10-DET, steel sheet photographs, ten classes with boxes",
        "task": "Object detection, the only module that answers where",
        "meta": "gc10/gc10_cv_meta.json",
        "card": "Model_Card_GC10_Detection.md",
        "figures": ("cv", "gc10"),
        "events": "gc10_events.jsonl",
        "headline": [
            ("mAP at 0.5", "test_performance.map_50", "{:.4f}"),
            ("mAP at 0.75", "test_performance.map_75", "{:.4f}"),
            ("Boxes located", "test_performance.boxes_found", "{:,}"),
            ("Boxes present", "test_performance.boxes_present", "{:,}"),
            ("Boxes claimed that are not there", "test_performance.boxes_claimed_not_there", "{:,}"),
            ("Detection threshold", "operating_point.detection_threshold", "{:.2f}"),
        ],
        "caveat": "Three qualifications lead the card. It does not reproduce: refitting from "
                  "the same seed moved test mAP from 0.6260 to 0.6462. It cannot pass a "
                  "sheet, because this dataset contains none anyone certified clean, so "
                  "silence is a failure to find rather than a pass. And the per-class spread "
                  "is not the sample sizes: the class with the most boxes scores 0.2676.",
    },
    "nhtsa": {
        "title": "Consumer complaint field quality",
        "icon": "message-square",
        "source_module": "nhtsa_nlp",
        "business_domain": "field_quality",
        "dataset": "NHTSA consumer complaints 2020-2024, 24 component classes",
        "task": "Multi-label text classification, then a trend over the output",
        "meta": "nhtsa/nhtsa_nlp_meta.json",
        "card": "Model_Card_NHTSA_Field_Quality.md",
        "figures": ("nlp", ""),
        "events": "nhtsa_events.jsonl",
        "headline": [
            ("Micro F1", "performance.test.micro_f1", "{:.4f}"),
            ("Macro F1", "performance.test.macro_f1", "{:.4f}"),
            ("At least one component right", "performance.test.any_label_hit", "{:.2%}"),
            ("Exact set right", "performance.test.exact_set", "{:.2%}"),
            ("Cells tested for a trend", "trend.cells_tested", "{:,}"),
            ("Cells published as events", "trend.cells_published", "{:,}"),
        ],
        "caveat": "Nothing this module publishes is evidence that a part failed: its input is "
                  "what a member of the public wrote about their own vehicle. It is also the "
                  "only module here whose published batch can be scored, and it scores "
                  "precision 0.520 against the held-out labels, so about half of what it "
                  "publishes is not confirmed.",
    },
}

ORDER = list(MODULES)
