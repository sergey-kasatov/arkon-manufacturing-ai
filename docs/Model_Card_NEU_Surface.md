# Model Card: NEU Steel Surface Defect Classification

Module 04 of the Arkon platform. Names which of six defect types is present on a
hot-rolled steel strip surface, and feeds the Quality Steering Cell through the
risk event adapter. Second module to publish in the `visual_inspection` domain,
after casting.

- **Version:** v1, trained 2026-09-01
- **Artifacts:** `models/checkpoints/neu/neu_resnet18_v1.pt`,
  predictions in `data/04_neu/processed/test_neu_predictions.npz`,
  metrics in `models/checkpoints/neu/neu_cv_meta.json`
- **Training code:** `notebooks/03_cv/02_neu_steel_defects/03_neu_modeling.ipynb`.
  There is no separate training script: the notebook is the code, and every cell
  in it carries the output of the run that produced these numbers.
- **Event adapter:** `events/make_events_neu.py`
- **MLflow:** experiment `arkon-cv-neu`, run `neu_resnet18_v1`

---

## 1. Intended use

Classify the defect type on a surface already known to be defective, so the
Quality Steering Cell can record what was found against a coil and route the
uncertain cases to a QC Engineer.

**This module cannot decide whether a surface is defective at all.** NEU-DET has
no good-surface class: all six of its classes are defects, so nothing in the
training data represents a clean strip. Handed a picture of sound steel it will
still return one of six defect names with high confidence. It is a *what is it*
model downstream of a *is there anything* decision that this platform does not
yet make. Casting makes that first decision for a different product on a
different line and the two are not composable as they stand.

**Not intended for:** any real release, scrap or downgrade decision. Per the
project charter, a risk score is not a production stop decision.

## 2. Data

NEU-DET surface defect database, Northeastern University: greyscale photographs
of hot-rolled steel strip, 200 x 200, six defect classes, shipped with Pascal VOC
bounding boxes as well as class subfolders.

| Folder | Per class | Total | Used here as |
|---|---|---|---|
| `train/` | 240 | 1,440 | 1,224 fitting + 216 selection, stratified 85/15 at seed 42 |
| `validation/` | 60 | 360 | the test set, scored once |

**The dataset ships no test folder, and this is the single most important thing
to know when reading section 4.** It publishes `train/` and `validation/` only.
This module therefore cuts the train folder for its own model selection and holds
the shipped `validation/` folder back entirely, scoring it once at the end. Every
number in section 4 was measured on those 360 images, which no fitting step and
no threshold choice ever touched. Where this card says "test folder" it means the
folder the dataset itself calls `validation/`.

**The folders are disjoint, and this was checked rather than assumed.** Casting's
published test folder turned out to share 64 byte-identical images with its train
folder, so the check is now standard. Here it comes back clean on three separate
measures:

- no image is byte-identical or pixel-identical across the two folders;
- no test image sits closer than 0.9823 cosine to anything in the fitting set, in
  an un-finetuned ImageNet feature space, so there are no re-crops of one
  photograph either;
- the control settles it. A test image sits about as close to the rest of the
  **test** folder (median 0.9428) as it does to the fitting set (median 0.9378).
  The fitting folder is not special, which is what the absence of a leak looks
  like.

**One duplicate pair exists and it is inside the train folder**, `patches_101`
and `patches_105`. A plain stratified split put one copy on each side of the
fitting/selection cut, which would have put an already-fitted image into the set
that chooses the operating point. Notebook 02 detects this and repairs it with a
same-class swap, leaving the class counts exactly 204 and 36.

### Two label systems over the same pictures, and they do not fully agree

Each image carries a class from the folder it sits in *and* a list of bounding
boxes. Over all 1,800 images and 4,189 boxes:

- The folder class is **never wrong**: in no image is the folder's class absent
  from that image's own boxes.
- The folder class is **incomplete for 123 images, 6.8 per cent**, which contain a
  second defect class the folder name discards. The common pairs are physically
  sensible: scratches with inclusion (49), pitted surface with patches (37),
  patches with inclusion (29). 23 of the 123 are in the test folder.

A single-label classifier cannot be right about both classes at once, so those
123 images are a ceiling on what any model of this shape can score against the
folder label. Section 4 reports where that ceiling actually bit.

### Two defects in the published files

Both found by `01_neu_eda.ipynb`, both properties of the dataset as distributed:

1. **`crazing_240` is filed on both sides of the split.** Its image is in
   `train/images/crazing`, its annotation is in `validation/annotations`. Every
   other stem agrees with itself. For the classification task this costs nothing
   because the boxes are never loaded; a detection loader that pairs the folders
   by split would silently drop a training image and gain a label with no picture
   under it.
2. **A zero-byte file sits in `train/annotations`**, `.crazing_21.xml.BXARk2LvYS`,
   left by a file-sync client. It is not a label. A loader globbing the directory
   rather than `*.xml` would try to parse it.

Neither is corrected in the raw data, which stays immutable per charter section 5.

## 3. Method

**ResNet-18, ImageNet weights, the whole network fine-tuned**, 224 x 224, batch
32, Adam at 1e-4, twelve epochs, the epoch with the best selection-set macro F1
kept. The third epoch won.

**The augmentation is two mirrors and a small rotation, and the exclusion is the
interesting part.** Horizontal and vertical flips, plus rotation up to 10 degrees.
A quarter turn is excluded, and not on taste: the six classes separate on texture
direction, measured as the imbalance between vertical and horizontal gradient
energy, over a range of 0.290 between class means. A mirror leaves that statistic
untouched to four decimal places. A quarter turn inverts it, changing a class mean
by up to 0.372. In a rolling mill the direction of a scratch relative to the
rolling axis is information, and a quarter turn is not an augmentation of that
picture but a relabelling of it.

The images are greyscale stored in three identical channels. They are normalised
with the ImageNet per-channel constants anyway, which pushes three identical
numbers 0.353 apart. That offset is constant across every image, so no class can
be told from it, and the scale the constants apply is within 10 per cent of the
dataset's own. Normalising with measured statistics instead would break the match
with the pretrained weights for no measured gain.

## 4. Performance

Test folder, 360 images, the folder the dataset ships as `validation/`, scored
once.

| | Value |
|---|---|
| Accuracy | **1.0000** |
| Macro F1 | **1.0000** |
| Errors | **0 of 360** |
| Per class F1 | 1.0000 for all six |

**Read that against what the task costs before training, not against chance.**
This is the number this card exists to qualify:

| Classifier | Accuracy on the same 360 images |
|---|---|
| Chance, six balanced classes | 0.1667 |
| Logistic regression on two numbers per image (mean, standard deviation) | 0.4861 |
| **1-nearest-neighbour on un-finetuned ImageNet features** | **0.9750** |
| ResNet-18, frozen backbone, only the final layer trained | 0.8639 |
| ResNet-18, whole network fine-tuned | 1.0000 |

A classifier that does no learning at all, comparing test images to fitting images
in a feature space built for photographs of dogs and cars, is right 97.5 per cent
of the time. **NEU-DET six-class classification is close to saturated**, and a
perfect score on it is evidence about the benchmark first and about the model
second. Anyone reading 1.0000 as a claim about this model's quality is reading it
wrong, and limitation 1 says so at length.

The frozen-backbone ablation is on the same basis as the row above it: the same
fitting set, the same selection set, the same metric, the same twelve epochs. It
reaches 0.8639 accuracy and 0.8586 macro F1 with 49 errors, and it was still
improving at epoch 12, so 13.6 accuracy points is what adapting the convolutions
buys and not a converged ceiling for that arm.

### The label ceiling was never reached

23 of the 360 test images carry a second defect class. With zero errors on the
whole folder, the model named the folder's class on all 23, and the folder's class
is always one of the classes genuinely in the frame. So the 6.8 per cent ceiling
from section 2 is a limit on what this shape of model *could* score, not one this
run ran into.

### Does it reproduce

Refitting the fine-tuned arm from the same seed in the same session moved 1 of 7
reported values, the epoch-1 training loss in its fourth decimal, and changed 0 of
360 test predictions. The band edge did not move.

**The GPU non-determinism casting found is present here too; what differs is
whether it reaches a decision.** Across the four full executions of this notebook
run while it was being written, eight fine-tuned fits produced 0 errors seven
times and 1 error once, so the 1.0000 above is the common outcome rather than a
guaranteed one, and 0.9972 is within what this code does. That observation comes
from development runs rather than from a controlled experiment, and it is recorded
because it is what was seen.

Casting's operating point moves between 0.0436 and 0.2203 across four runs of one
seed, taking its missed defects from 0 to 2. This module's band edge does not move
at all, and the reason is structural rather than lucky: casting *searches* for its
threshold on a cost curve with no well-determined minimum, so tiny numerical noise
selects a different empty gap. This module declares its band edge, so there is
nothing for the noise to amplify. That is an argument for the open casting item,
not a claim that this module is better engineered.

## 5. Priority mapping (charter section 7.1)

**Every classified surface produces an event**, the way CMAPSS publishes one per
test engine, and unlike casting and Scania which publish only what they flag.
There is no negative case here to suppress: the dataset has no good-surface class,
so there is no "this one is fine" to leave unpublished.

**Priority is driven by confidence, not by defect class.** Ranking crazing against
inclusion against pitted surface by severity would need metallurgical judgement
this project does not have, and inventing a ranking would be worse than not having
one. The defect type rides in `risk_type` and in the evidence object, where a
consumer can use it without this module having pretended to grade it.

| Priority | Band | Test count | What the operator does |
|---|---|---|---|
| P2 | confidence below 0.90 | 3 | The model cannot name the defect. A person classifies it, within the hour |
| P3 | confidence 0.90 and above | 357 | The defect type is logged against the coil; queued, reviewed daily, no push alert |

**No P1**, for the same reason casting emits none and one more: the charter's P1 is
an imminent failure or safety-relevant risk on a fifteen-minute clock, no single
classified surface is that, and this module has no severity ranking that could
identify one if it were.

**No P4.** Every image in this dataset is a defect, so there is no
informational-only case to record.

### The band edge is declared, not calibrated, and that is a weakness

The intended rule was measurable: take the lowest confidence at which the accepted
predictions on the selection set are right at least 99 per cent of the time.
**The rule degenerated.** The model classified all 216 selection images correctly,
so there is no mistake anywhere in that set to push the threshold up, every
threshold meets the target, and the rule returns the bottom of the grid, 0.0000.
A threshold of 0 puts every image in the confident band and leaves the P2 band
permanently empty. That is not a calibration, it is the absence of one.

**0.90 is therefore an Arkon assumption**, recorded as such, exactly the way
casting's cost ratios are recorded as an assumption because that dataset ships no
cost metric. It is chosen to sit below the mass of the confidence distribution
(95.8 per cent of selection confidences are above 0.99) and above its tail, so it
selects the few predictions the model is visibly hesitant about. On the test folder
it puts 3 images in front of a person and 357 into the log, and none of the 3 would
have been classified wrongly. **It is not a claim that a 0.90-confidence prediction
is right 90 per cent of the time.** Calibrating it needs a selection set this model
makes mistakes on, which this benchmark does not provide.

**Where the module hesitates is not random, on the little evidence there is.** All
three P2 events are `inclusion` surfaces, and their runner-up classes are
`scratches` twice and `pitted_surface` once. Those are among the classes NEU-DET
most often puts in the same frame as an inclusion: scratches with inclusion is the
commonest mixed pair in the dataset at 49 images. So the model is uncertain where
the dataset's own labelling is ambiguous, which is the behaviour one would want.
Three events is far too small a sample to call this a property of the module, and
it is recorded as an observation rather than a finding.

## 6. Limitations

1. **The benchmark is close to saturated, and the headline number is mostly about
   that.** 1-nearest-neighbour on features never trained on steel reaches 0.9750
   on the same folder. 1,800 images at a fixed magnification, fixed lighting and a
   curated 300-per-class balance is a far kinder problem than a rolling mill.
   Nothing here says how the module behaves on a strip photographed in motion,
   under changing illumination, at a scale the dataset does not contain. The right
   reading of 1.0000 is that the dataset is easy.
2. **The module cannot detect a defect, only name one.** There is no
   good-surface class. Shown clean steel it returns a defect type with high
   confidence and no way to say "nothing here". This is the single largest gap
   between what the module does and what an inspection station needs, and closing
   it needs data this dataset does not contain.
3. **No localisation, and the boxes to do it are sitting unused.** The dataset
   ships 4,189 Pascal VOC boxes and this module discards them, returning one label
   for the whole 200 x 200 frame. That is a deliberate scoping choice, recorded in
   the README roadmap where object detection belongs to the GC10 module, but it
   means an operator asking *where* gets nothing. It also wastes real information:
   five of the six classes occupy under a quarter of the frame, `inclusion` a
   median of 0.041 of it, so the classifier is deciding on evidence that occupies a
   small part of what it looks at.
4. **6.8 per cent of the labels are incomplete.** 123 images contain a second
   defect class the folder name discards, 23 of them in the test folder. This run
   scored perfectly against the folder label anyway, so the ceiling did not bite,
   but any future comparison on this dataset inherits it and a multi-label
   formulation would be the honest fix.
5. **No calibration.** The confidences pile up near 1: 95.8 per cent of the
   selection set is above 0.99. The 0.90 band edge is a confidence ordering, not a
   statement of odds, and section 5 records that it could not be calibrated at all
   on data this model classifies perfectly.
6. **Twelve epochs, one seed, no hyperparameter search.** The best epoch was the
   third, so the schedule is four times longer than the task needs and nothing was
   tuned. The frozen ablation had not converged at epoch 12, so its 0.8639 is a
   floor for that arm rather than its ceiling, and the 13.6-point gap between the
   arms is correspondingly an upper bound on what fine-tuning is worth.
7. **The seed does not pin the result exactly.** Refitting from the same seed
   changes the training loss in its fourth decimal, because the cuDNN convolution
   backward kernels accumulate in an order that `torch.backends.cudnn.deterministic`,
   left at its default of `False`, does not fix. Here it moved 0 of 360 predictions
   and did not move the band edge, and section 4 records the one development run in
   eight that produced 1 error instead of 0.
8. **Two modules now share the `visual_inspection` domain.** Casting and this one
   publish into the same business domain, so an incident query filtered by
   `business_domain=visual_inspection` returns both, and the roster assigns both to
   the same two QC Engineers although the README places them in different
   departments, Foundry and Rolling Mill. Filtering by `source_module` still
   separates them. Nothing is broken; the domain has simply stopped being a
   one-to-one proxy for a module, and anything that assumed otherwise is now wrong.

## 7. Reproduction

Everything below runs from the repository root with the project venv active.

```bash
jupyter nbconvert --execute --to notebook --inplace notebooks/03_cv/02_neu_steel_defects/01_neu_eda.ipynb
jupyter nbconvert --execute --to notebook --inplace notebooks/03_cv/02_neu_steel_defects/02_neu_preprocessing.ipynb
jupyter nbconvert --execute --to notebook --inplace notebooks/03_cv/02_neu_steel_defects/03_neu_modeling.ipynb
python events/make_events_neu.py
```

Notebook 03 writes all three artifacts and logs the run to MLflow. It takes about
five minutes on an RTX 3070: three fits of twelve epochs each, two fine-tuned and
one frozen.

**Expect the fourth decimal of the training loss to differ**, and expect the test
error count to be 0 or 1 rather than exactly 0. Section 4 has the measurement. The
reported accuracy, macro F1, confusion matrix and band edge in this card come from
the run stored in `models/checkpoints/neu/neu_cv_meta.json`, and the notebook
compares any new run against a second fit of its own rather than against this file.
