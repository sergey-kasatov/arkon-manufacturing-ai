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

**The two shipped folders are not disjoint.** 64 of the 715 test images are
byte-identical copies of images in the train folder, matched both on the file
bytes and on a SHA-256 of the decoded pixels, which agree. All 64 are good
parts and none of them is a defect. 55 fell on the training side of the 85/15
split and were fitted on; the other 9 went to validation. This is a property of
the dataset as published, not of anything done here, and limitation 8 says what
it costs. Measured over all 7,348 files by
`notebooks/03_cv/01_casting_defects/01_casting_eda.ipynb`, 2026-09-01.

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

**Read this whole table as "this model, this run".** Re-running the identical
experiment from the identical seed on the same machine does not give it back.
Over the four runs recorded in section 7 the missed defects range 0 to 2, the
good parts rejected 2 to 11, and even the epoch the run keeps is not fixed:
it was 2, 2, 2 and 5.

What is stable is the frozen-backbone ablation, which comes back bit-identical
every time, the threshold-free AUCs, which stay between 0.9998 and 1.0000, and the
fact that all three cost ratios always agree on one cut. What is not stable is
every number in the operating-point column above.

**The frozen-backbone ablation**, identical in every other respect: recall
0.9492, precision 0.9368, ROC AUC 0.9757, 23 defects missed.

**Compared on one basis.** The ablation is scored at 0.5, so the fine-tuned
column to read beside it is the 0.5 one: 23 defects missed against 2, a factor
of 11.5. An earlier version of this card put the 23 next to the 0 of the
operating-point column, which is two different thresholds under one comparison.
The conclusion is unchanged on either basis, and it is the answer to whether
casting surfaces look enough like ImageNet photographs to reuse the later
features. They do not.

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
6. **Six epochs, one seed, no hyperparameter search, and the seed does not pin
   the result.** The best epoch was the second, so the schedule is longer than
   the task needs, and nothing was tuned. An earlier version of this line called
   the run "deterministic in its seed". It is not, and section 7 has the
   measurement: re-running the identical experiment from the identical seed
   reproduces the frozen-backbone ablation exactly and the fine-tuned arm only
   approximately, because the cuDNN convolution backward kernels accumulate in
   an order that `torch.backends.cudnn.deterministic`, left at its default of
   `False`, does not fix. It reaches the decisions and not only the digits
   behind them: across four runs the kept epoch, the operating point and every
   confusion-matrix count at it all move. Nor was anything repeated across
   seeds, which the Scania module shows can matter - and the seed turns out not
   to be the only thing that was never varied deliberately.
7. **Fabricated operational context.** Lines, shifts, assignees and escalation
   contacts attached to the events are invented and labelled
   `context_origin: simulated` in every event. No real person or plant appears
   anywhere.
8. **The published test split overlaps the training folder, and it is one-sided.**
   Section 2 has the census: 64 duplicated images, all good parts, 55 of them
   fitted on. The two headline numbers are therefore not equally trustworthy.
   **Recall is untouched** - no defect is duplicated, so the 0 missed of 453 is
   measured on parts the model has never seen. **The false-alarm count is not**:
   7 of 262 is measured on a set where 55 good parts were in the training data.
   Scoring the same shipped predictions over only the 198 good parts that appear
   nowhere in the train folder gives 6 rejected, 3.03 percent against the 2.67
   percent above. The effect is real, it runs in the direction that flatters the
   model, and it is small: exactly one of the seven false alarms is an image the
   model was fitted on. The honest reading is that this module's false-alarm
   rate is about 3 percent rather than about 2.7, and that no published number
   here should be quoted to three digits.

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

The notebook trio is the second route to the same result, and the one to read
rather than run:

```bash
jupyter nbconvert --to notebook --execute --inplace notebooks/03_cv/01_casting_defects/01_casting_eda.ipynb
jupyter nbconvert --to notebook --execute --inplace notebooks/03_cv/01_casting_defects/02_casting_preprocessing.ipynb
jupyter nbconvert --to notebook --execute --inplace notebooks/03_cv/01_casting_defects/03_casting_modeling.ipynb
```

They build the experiment from the raw images without importing anything from
`casting_cv.py`, so their agreement with this card is a reproduction and not a
tautology. Notebook 03 reads the metrics file before it trains anything, trains
both arms, and prints a value-by-value comparison at the end. **It writes its own
artifacts under their own names and does not overwrite the shipped ones**,
because unlike the CMAPSS and Scania rebuilds this one cannot promise an exact
match. It takes about eight minutes on the RTX 3070 Laptop.

### What the rebuild found: this experiment does not reproduce itself

Notebook 03 was run 3 times on 2026-09-01, from the same seed, on the same
machine, over the same split. The two training arms behave differently, and the
difference between them is the whole diagnosis:

- **The frozen-backbone ablation reproduced the August run exactly**, all 35
  recorded values, five decimals of training loss included, in all three runs.
  It trains one linear layer and its backward pass touches no convolution.
- **The fine-tuned arm reproduced nothing exactly**, neither the August run nor
  the other notebook runs. It trains every convolution, and cuDNN accumulates
  those backward kernels in an order it does not promise to repeat.
  `torch.backends.cudnn.deterministic` is left at its default of `False`, which
  is what the shipped script does too.

A notebook that had actually diverged from the script would have moved the
frozen arm as well. This one did not, so what moves is the GPU rather than the
code.

**The consequence is not confined to the last digits.** The operating point is
chosen by minimising cost on a validation split where the two classes are almost
perfectly separated, so the cost curve is nearly flat across orders of magnitude,
and a probability change too small to see in the training curve is enough to move
the minimum onto a different plateau:

| Run | Threshold | Defects missed | Good parts rejected |
|---|---|---|---|
| shipped, 2026-08-30 | 0.0637 | 0 | 7 |
| notebook, run 1 | 0.0436 | 0 | 7 |
| notebook, run 2 | 0.2203 | 2 | 2 |
| notebook, run 3 | 0.1163 | 2 | 11 |

All four runs agree that the three cost ratios pick a single cut, so that
conclusion is stable. Almost nothing else about the operating point is. Where
the cut lands moves by a factor of 5.0, the epoch the run keeps was
2, 2, 2 and 5, and whether this module misses a defect at all changes
with it. **The 0 in the table
of section 4 is one draw, not a property of the method**, and the honest range
over four runs is 0 to 2 defects missed of 453 against 2 to 11 good parts
rejected of 262.

Pinning it would take `torch.use_deterministic_algorithms(True)` and the cuBLAS
workspace environment variable, at a cost in speed, and neither the script nor
the notebook does that today. **The better fix is not a pinned seed but a
threshold that does not balance on a knife edge**: the scores pile up at 0 and 1
with only a couple of dozen test images anywhere between, so the cost curve has
no well-determined minimum to find and the search returns whichever empty gap
happens to win. That is limitation 5 and this limitation meeting.
