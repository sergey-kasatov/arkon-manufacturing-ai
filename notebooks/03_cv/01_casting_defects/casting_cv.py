"""Casting defect classification: the Arkon computer-vision module.

Module 03 of the Arkon platform. A binary image classifier over front-view
photographs of submersible pump impellers, deciding whether a cast part carries
a visible defect. It feeds the Quality Steering Cell through the risk event
adapter, exactly as the CMAPSS and Scania modules do.

## The decisions

**Transfer learning, ResNet-18, ImageNet weights, whole network fine-tuned.**
The alternative considered and rejected was training a small convolutional
network from scratch. With 6,633 training images that is possible and it is the
wrong trade: the first convolutional layers of a pretrained network already
detect the edges and texture gradients that separate a blowhole from a clean
surface, and relearning them from this many images buys nothing but variance.
Freezing all but the final layer was also rejected and is measured in the
ablation, because casting surfaces do not look like ImageNet photographs and the
later features do need to move.

**The validation split comes out of the training folder, and the test folder is
touched once.** The dataset ships its own train and test folders and they are
kept apart. Everything - the number of epochs, the decision threshold - is
chosen on validation.

**Augmentation is deliberately small: horizontal and vertical flips, and small
rotations.** The parts are photographed centred under fixed lighting, so the
transforms that make sense are the ones a part on a conveyor could actually
present. Colour jitter and heavy crops were rejected: they would teach the model
to ignore exactly the surface-brightness cues that a shallow blowhole shows up
as.

## What is reported, and the one thing this dataset does not give

The Scania module has a published cost metric, so its threshold is a solved
optimisation. This dataset has none, and inventing one and reporting it as if it
came with the data would be dishonest. So two things are reported separately:

  - **Threshold-free quality**: ROC AUC and PR AUC, which do not depend on where
    the boundary is put.
  - **The cost curve under an Arkon assumption**, stated as an assumption: a
    defect shipped is worth more than a good part re-inspected. The run prints
    the operating point for three ratios, 10:1, 25:1 and 50:1, so the reader can
    see how much the choice actually moves and pick their own.

The confusion matrix at the chosen operating point is always printed beside the
headline number, because in inspection the two error directions are two
different conversations with two different people.

Run from the repository root:
    python notebooks/03_cv/01_casting_defects/casting_cv.py
"""

import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import average_precision_score, confusion_matrix, roc_auc_score
from torch.utils.data import DataLoader, Subset
from torchvision import transforms
from torchvision.datasets import ImageFolder
from torchvision.models import ResNet18_Weights, resnet18

# Paths and constants
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "03_casting" / "raw"
PROC_DIR = PROJECT_ROOT / "data" / "03_casting" / "processed"
CKPT_DIR = PROJECT_ROOT / "models" / "checkpoints" / "casting"

SEED = 42
IMAGE_SIZE = 224
BATCH_SIZE = 32
EPOCHS = 6
LEARNING_RATE = 1e-4
VALIDATION_FRACTION = 0.15
# The cost ratios the run reports. None of them ships with the dataset; they are
# an Arkon assumption and are printed as a range for exactly that reason.
COST_RATIOS = [10, 25, 50]

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

TRAIN_TRANSFORM = transforms.Compose([
    transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    transforms.RandomRotation(10),
    transforms.ToTensor(),
    transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
])
EVAL_TRANSFORM = transforms.Compose([
    transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
])


def device():
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_model(freeze_backbone=False):
    model = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
    if freeze_backbone:
        for parameter in model.parameters():
            parameter.requires_grad = False
    model.fc = nn.Linear(model.fc.in_features, 2)
    return model.to(device())


def split_indices(dataset, fraction, seed):
    """Stratified split of an ImageFolder into training and validation indices."""
    targets = np.array(dataset.targets)
    rng = np.random.default_rng(seed)
    train_index, val_index = [], []
    for label in np.unique(targets):
        rows = np.where(targets == label)[0]
        rng.shuffle(rows)
        cut = int(round(len(rows) * fraction))
        val_index.extend(rows[:cut].tolist())
        train_index.extend(rows[cut:].tolist())
    return sorted(train_index), sorted(val_index)


def loader(dataset, indices, transform, shuffle):
    """A loader over a subset, with its own transform.

    ImageFolder holds one transform, and the training and validation subsets of
    the same folder need different ones. Copying the dataset object is the
    cheapest way to give each subset its own: it copies the file list, not the
    images.
    """
    import copy
    view = copy.copy(dataset)
    view.transform = transform
    return DataLoader(Subset(view, indices), batch_size=BATCH_SIZE, shuffle=shuffle,
                      num_workers=0, pin_memory=torch.cuda.is_available())


def run_epoch(model, data, optimiser, criterion):
    model.train()
    total, correct, loss_sum = 0, 0, 0.0
    for images, labels in data:
        images, labels = images.to(device()), labels.to(device())
        optimiser.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimiser.step()
        loss_sum += loss.item() * labels.size(0)
        correct += (outputs.argmax(1) == labels).sum().item()
        total += labels.size(0)
    return loss_sum / total, correct / total


@torch.no_grad()
def scores_for(model, data):
    """Probability of the defect class for every image, in loader order."""
    model.eval()
    probabilities, truth = [], []
    for images, labels in data:
        outputs = model(images.to(device()))
        probabilities.append(torch.softmax(outputs, dim=1)[:, DEFECT_INDEX].cpu().numpy())
        truth.append(labels.numpy())
    return np.concatenate(probabilities), np.concatenate(truth)


def operating_point(y_true, scores, ratio):
    """The threshold minimising cost when a missed defect costs `ratio` times a false alarm."""
    order = np.argsort(-scores)
    labels = (y_true[order] == DEFECT_INDEX).astype(int)
    positives = int(labels.sum())
    true_positives = np.concatenate([[0], np.cumsum(labels)])
    predicted = np.arange(len(labels) + 1)
    false_positives = predicted - true_positives
    false_negatives = positives - true_positives
    costs = false_positives + ratio * false_negatives
    k = int(np.argmin(costs))
    sorted_scores = scores[order]
    if k == 0:
        return float(sorted_scores[0]) + 1e-9
    if k >= len(sorted_scores):
        return float(sorted_scores[-1])
    return float((sorted_scores[k - 1] + sorted_scores[k]) / 2)


def report(y_true, scores, threshold):
    predicted = (scores >= threshold).astype(int)
    actual = (y_true == DEFECT_INDEX).astype(int)
    tn, fp, fn, tp = confusion_matrix(actual, predicted, labels=[0, 1]).ravel()
    return {
        "threshold": round(float(threshold), 6),
        "accuracy": round(float((tp + tn) / len(actual)), 4),
        "precision": round(float(tp / (tp + fp)), 4) if tp + fp else 0.0,
        "recall": round(float(tp / (tp + fn)), 4) if tp + fn else 0.0,
        "defects_missed": int(fn),
        "good_parts_rejected": int(fp),
        "defects_caught": int(tp),
        "good_parts_passed": int(tn),
        "roc_auc": round(float(roc_auc_score(actual, scores)), 4),
        "pr_auc": round(float(average_precision_score(actual, scores)), 4),
    }


def train(train_data, val_data, freeze_backbone, epochs, tag):
    """Fit, keeping the epoch with the best validation PR AUC."""
    torch.manual_seed(SEED)
    model = build_model(freeze_backbone)
    criterion = nn.CrossEntropyLoss()
    optimiser = torch.optim.Adam(
        [p for p in model.parameters() if p.requires_grad], lr=LEARNING_RATE)
    best = {"pr_auc": -1.0, "state": None, "epoch": 0}
    history = []
    for epoch in range(1, epochs + 1):
        started = time.time()
        loss, accuracy = run_epoch(model, train_data, optimiser, criterion)
        val_scores, val_truth = scores_for(model, val_data)
        val_pr = float(average_precision_score((val_truth == DEFECT_INDEX).astype(int), val_scores))
        history.append({"epoch": epoch, "train_loss": round(loss, 5),
                        "train_accuracy": round(accuracy, 4), "val_pr_auc": round(val_pr, 5),
                        "seconds": round(time.time() - started, 1)})
        print("  [%s] epoch %d  loss %.4f  train acc %.4f  val PR-AUC %.5f  (%.0fs)"
              % (tag, epoch, loss, accuracy, val_pr, time.time() - started))
        if val_pr > best["pr_auc"]:
            best = {"pr_auc": val_pr, "epoch": epoch,
                    "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}}
    model.load_state_dict(best["state"])
    print("  [%s] best epoch %d, val PR-AUC %.5f" % (tag, best["epoch"], best["pr_auc"]))
    return model, history, best["epoch"]


def main():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    print("device:", device(), "|", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu")

    full_train = ImageFolder(RAW_DIR / "train", transform=EVAL_TRANSFORM)
    test_set = ImageFolder(RAW_DIR / "test", transform=EVAL_TRANSFORM)
    global DEFECT_INDEX
    DEFECT_INDEX = full_train.class_to_idx["def_front"]
    print("classes:", full_train.class_to_idx, "| defect index:", DEFECT_INDEX)

    train_index, val_index = split_indices(full_train, VALIDATION_FRACTION, SEED)
    train_loader = loader(full_train, train_index, TRAIN_TRANSFORM, shuffle=True)
    val_loader = loader(full_train, val_index, EVAL_TRANSFORM, shuffle=False)
    test_loader = DataLoader(test_set, batch_size=BATCH_SIZE, shuffle=False,
                             num_workers=0, pin_memory=torch.cuda.is_available())
    print("train %d, validation %d, test %d images"
          % (len(train_index), len(val_index), len(test_set)))

    print("\nfine-tuning the whole network")
    model, history, best_epoch = train(train_loader, val_loader, False, EPOCHS, "full")

    val_scores, val_truth = scores_for(model, val_loader)
    test_scores, test_truth = scores_for(model, test_loader)

    # Operating points: chosen on validation, reported on test, one per assumed
    # cost ratio. None of the ratios comes with the dataset.
    print("\noperating points, threshold chosen on validation and applied to test")
    points = {}
    for ratio in COST_RATIOS:
        threshold = operating_point(val_truth, val_scores, ratio)
        points["missed_defect_costs_%dx" % ratio] = report(test_truth, test_scores, threshold)
        row = points["missed_defect_costs_%dx" % ratio]
        print("  %2d:1  threshold %.4f  missed %2d  rejected %2d  recall %.4f  precision %.4f"
              % (ratio, threshold, row["defects_missed"], row["good_parts_rejected"],
                 row["recall"], row["precision"]))

    neutral = report(test_truth, test_scores, 0.5)
    print("  0.5   threshold 0.5000  missed %2d  rejected %2d  recall %.4f  precision %.4f"
          % (neutral["defects_missed"], neutral["good_parts_rejected"],
             neutral["recall"], neutral["precision"]))
    print("  threshold-free: ROC AUC %.4f, PR AUC %.4f" % (neutral["roc_auc"], neutral["pr_auc"]))

    # Ablation: the frozen backbone, which is the decision the docstring claims
    # would be wrong on casting surfaces.
    print("\nablation: final layer only, backbone frozen")
    frozen, frozen_history, frozen_best = train(train_loader, val_loader, True, EPOCHS, "frozen")
    frozen_scores, _ = scores_for(frozen, test_loader)
    frozen_report = report(test_truth, frozen_scores, 0.5)
    print("  frozen backbone at 0.5: recall %.4f  precision %.4f  ROC AUC %.4f"
          % (frozen_report["recall"], frozen_report["precision"], frozen_report["roc_auc"]))

    torch.save(model.state_dict(), CKPT_DIR / "casting_resnet18_v1.pt")
    np.savez(PROC_DIR / "test_casting_predictions.npz",
             paths=np.array([p for p, _ in test_set.samples]),
             true_label=test_truth, defect_probability=test_scores)

    meta = {
        "dataset": "Casting product image data for quality inspection, front view of submersible pump impellers",
        "architecture": "resnet18, ImageNet weights, whole network fine-tuned",
        "image_size": IMAGE_SIZE,
        "batch_size": BATCH_SIZE,
        "epochs": EPOCHS,
        "best_epoch": best_epoch,
        "learning_rate": LEARNING_RATE,
        "seed": SEED,
        "classes": full_train.class_to_idx,
        "train_images": len(train_index),
        "validation_images": len(val_index),
        "test_images": len(test_set),
        "augmentation": "horizontal and vertical flip, rotation up to 10 degrees",
        "threshold_note": ("this dataset ships no cost metric; the operating points below are "
                           "an Arkon assumption about the ratio of a missed defect to a "
                           "re-inspected good part, chosen on validation and reported on test"),
        "history": history,
        "operating_points": points,
        "at_threshold_0.5": neutral,
        "ablation_frozen_backbone": {
            "best_epoch": frozen_best,
            "history": frozen_history,
            "at_threshold_0.5": frozen_report,
        },
    }
    (CKPT_DIR / "casting_cv_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print("\nwrote %s" % (CKPT_DIR / "casting_cv_meta.json").relative_to(PROJECT_ROOT))


DEFECT_INDEX = 0

if __name__ == "__main__":
    main()
