# Model Card: Casting Defect Visual Inspection

Module 03 of the Arkon platform. Decides whether a cast submersible pump
impeller carries a visible surface defect, and feeds the Quality Steering Cell
through the risk event adapter.

- **Version:** v1, trained 2026-08-30
- **Artifacts:** `models/checkpoints/casting/casting_resnet18_v1.pt`,
  predictions in `data/03_casting/processed/test_casting_predictions.npz`,
  metrics in `models/checkpoints/casting/casting_cv_meta.json`
- **Training code:** `notebooks/03_cv/01_casting_defects/casting_cv.py`
- **Event adapter:** `events/make_events_casting.py`

---

## 1. Intended use

Screen front-view photographs of cast impellers on an inspection station, so the
Quality Steering Cell can route a part to quarantine or to a human. A prediction
above the operating point becomes an Arkon risk event.

**Not intended for:** any real release, scrap or safety decision. The images come
from a public research dataset photographed under fixed lighting on a stable
rig, which is a far kinder problem than a production line, and section 6 says how
much kinder. Per the project charter, a risk score is not a production stop
decision.

## 2. Data

Casting product image data for quality inspection: front-view photographs of
submersible pump impellers, 300 x 300 RGB, two classes.

| Split | Defective | Good | Total |
|---|---|---|---|
| Train folder | 3,758 | 2,875 | 6,633 |
| Test folder | 453 | 262 | 715 |

The train and test folders are the ones the dataset ships. The validation set is
a stratified 15 percent taken out of the training folder, 995 images, and it is
where the epoch and the operating point are chosen. The test folder is scored
once.

## 3. Method

**ResNet-18, ImageNet weights, the whole network fine-tuned**, 224 x 224, batch
32, Adam at 1e-4, six epochs, the epoch with the best validation PR AUC kept.
Augmentation is deliberately small: horizontal and vertical flips and rotations
up to 10 degrees, which are the presentations a part on a conveyor could actually
show. Colour jitter and heavy crops were rejected, because they would teach the
model to ignore exactly the surface-brightness cues a shallow blowhole appears
as.

Training from scratch was rejected without measuring it: at 6,633 images the
early convolutional layers of a pretrained network already detect the edges and
texture gradients this task needs, and relearning them buys variance. Freezing
the backbone **was** measured, and section 4 has the result.

## 4. Performance

Test folder, 715 images, scored once.

| Metric | At the operating point | At the default 0.5 |
|---|---|---|
| Threshold | 0.0637 | 0.5 |
| Defects missed | **0** | 2 |
| Good parts rejected | 7 | 1 |
| Recall | 1.0000 | 0.9956 |
| Precision | 0.9848 | 0.9978 |
| Accuracy | 0.9902 | 0.9958 |
| ROC AUC | 0.9999 | 0.9999 |
| PR AUC | 1.0000 | 1.0000 |

Best epoch: 2 of 6, validation PR AUC 0.99994. Epochs 3 to 6 did not improve it.

**The frozen-backbone ablation**, identical in every other respect: recall
0.9492, precision 0.9368, ROC AUC 0.9757, 23 defects missed against 0. Fine-tuning
the whole network is worth more than a factor of twenty in missed defects here,
which is the answer to whether casting surfaces look enough like ImageNet
photographs to reuse the later features. They do not.

### The cost ratio does nothing here, and that is the finding

The Scania module's whole argument is that the decision threshold is worth a
factor of four. The same experiment on this module returns nothing:

| Assumed cost of a missed defect | Threshold | Missed | Rejected |
|---|---|---|---|
| 10 times a false alarm | 0.0637 | 0 | 7 |
| 25 times | 0.0637 | 0 | 7 |
| 50 times | 0.0637 | 0 | 7 |

All three ratios pick the same threshold, because the two classes are separated
almost perfectly and there is nothing for the ratio to trade against. **This is
not a better model than the Scania one. It is an easier problem**, and reporting
the threshold sweep that found nothing is more useful than quietly omitting it.

**No cost metric ships with this dataset**, so the three ratios above are an
Arkon assumption and are labelled as one everywhere they appear. The 25 to 1
point is what the adapter uses, and it is the middle of a range in which nothing
changes.

## 5. Priority mapping (charter section 7.1)

**These bands run the opposite way to the other two modules, and the reason is
measured.** The first version banded by descending confidence, the way Scania
does, and produced **447 P1 events out of one 715-image batch**: 447 immediate
alerts, each with a fifteen-minute acknowledgement window. That is a pager storm,
not a triage.

What the test batch actually contains:

| Band | Parts | Genuinely defective |
|---|---|---|
| probability >= 0.99 | 447 | **447** |
| operating point to 0.99 | 13 | 6 |
| below the operating point | 255 | 0 |

A confident flag is the routine case and the operator already knows what to do
with it. The **uncertain** band is where the line actually stops: the part can be
neither passed nor scrapped without a person, and at 6 of 13 the model is a coin
flip there. So the uncertain band gets the higher priority and the shorter clock.

| Priority | Band | Test count | What the operator does |
|---|---|---|---|
| P2 | operating point to 0.99 | 13 | Stop the part and have QC decide, within the hour |
| P3 | probability >= 0.99 | 447 | Quarantine and log against the batch; queued, no push alert |
| P4 | below the operating point | not published | Nothing. The part passes and no event is emitted |

**This module emits no P1 at all in version 1.** The charter's P1 is an imminent
failure or safety-relevant risk with a fifteen-minute clock, and no single part
on an inspection line is that. The signal that would justify a P1 is a **rate**:
a run of defects means the process has drifted, and that is a batch-level event
rather than a part-level one. It is not built, and the reason is honest rather
than practical: a rate alarm needs a baseline defect rate, and this dataset has
none. Its test split is 63 percent defective, which is a curated ratio and not a
production one, so any baseline would be invented. The charter's own P3 line,
"degradation trend for planned work", is where that belongs when a real rate
exists.

**Below the operating point nothing is published**, for the same reason as
Scania: a pass is the normal case, and 255 "the part is fine" events per batch
would bury the incident store. The denominator is printed on every adapter run.

## 6. Limitations

1. **The problem is nearly solved by the data.** ROC AUC 0.9999 and PR AUC 1.0000
   on 715 images say the classes are almost perfectly separable under this
   dataset's fixed lighting, fixed camera, centred part and clean background.
   Nothing here transfers to a line with variable lighting, part rotation, or
   defect types the dataset does not contain. The right reading of these numbers
   is that the dataset is easy, not that the module is finished.
2. **One defect class, one part, one view.** The label is defective or not. It
   does not say blowhole, shrinkage, burr or misrun, and an operator asking which
   defect gets nothing. A defect-type model needs labels this dataset does not
   have.
3. **No localisation.** The model gives a probability for the whole image and
   cannot point at the defect. For an inspection decision that is enough; for
   feeding back to the process it is not, and a heat map is the cheapest next
   step.
4. **The operating point rests on an assumed cost ratio**, and section 4 shows
   the assumption currently makes no difference. On a harder batch it would, and
   nothing in the pipeline detects that the separation has degraded.
5. **No calibration.** The scores pile up at 0 and 1. The 0.99 band boundary is a
   confidence ordering, not a claim that such parts are defective 99 percent of
   the time, and the bands would need calibration before anyone read them as odds.
6. **Six epochs, one seed, no hyperparameter search.** The best epoch was the
   second, so the schedule is longer than the task needs, and nothing was tuned.
   The run is deterministic in its seed and was not repeated across seeds, which
   the Scania module shows can matter.
7. **Fabricated operational context.** Lines, shifts, assignees and escalation
   contacts attached to the events are invented and labelled
   `context_origin: simulated` in every event. No real person or plant appears
   anywhere.

## 7. Reproduction

```bash
python notebooks/03_cv/01_casting_defects/casting_cv.py
python events/make_events_casting.py
python events/validate_event.py events/out/casting_events.jsonl
```

Reads the images from `data/03_casting/raw`, writes the checkpoint, the test
predictions and the metrics JSON. The run needs a CUDA device for a comfortable
wall clock; on the RTX 3070 Laptop the full fine-tune is about 70 seconds per
epoch and the frozen-backbone ablation about 52. It re-runs the ablation and the
whole operating-point sweep on every execution, so the claims above stay
checkable rather than becoming folklore.
