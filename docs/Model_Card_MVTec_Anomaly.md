# Model Card: MVTec Component Anomaly Detection

Module 05 of the Arkon platform, and the first one that does not classify
anything. Four detectors, one per component category, each fitted on sound parts
alone and each reporting how far a new part sits from them. Third module to
publish in the `visual_inspection` domain, after casting and NEU.

- **Version:** v1, built 2026-09-01
- **Artifacts:** four memory banks in `models/checkpoints/mvtec/`, one `.npy` per
  category (`mvtec_patchcore_v1_grid_bank.npy`, `mvtec_patchcore_v1_metal_nut_bank.npy`, `mvtec_patchcore_v1_screw_bank.npy`, `mvtec_patchcore_v1_transistor_bank.npy`),
  predictions in `data/05_mvtec/processed/test_mvtec_predictions.npz`,
  metrics in `models/checkpoints/mvtec/mvtec_cv_meta.json`
- **Building code:** `notebooks/03_cv/03_mvtec_anomaly/03_mvtec_modeling.ipynb`.
  There is no separate training script: the notebook is the code, and every cell
  in it carries the output of the run that produced these numbers.
- **Event adapter:** `events/make_events_mvtec.py`
- **MLflow:** experiment `arkon-cv-mvtec`, runs `mvtec_patchcore_v1_<category>`

---

## 1. Intended use

Decide whether a photographed component looks like the sound ones the module
holds, and if it does not, say where on the part the difference is, so the
Quality Steering Cell can route it to a QC Engineer.

**This module cannot say what is wrong, only that something is.** It has never
seen a defect. It holds feature vectors taken from sound parts and reports a
distance, so it has no vocabulary for bent, scratched or contaminated and no
basis for calling one worse than another. Where NEU answers *which defect is
this* on a surface already known to be defective, and casting answers *is this
part defective* for one product on one line, this module answers *is this part
unlike the ones I know*. The three are complementary and none of them is a
substitute for another.

**Four models, not one.** grid, metal_nut, screw and transistor were photographed
at two resolutions in two colour modes with mean frame intensities from 59 to
184. They are four imaging setups, so they get four memory banks, four
thresholds and four reported results. A single averaged number appears nowhere in
this card without its range beside it.

**Not intended for:** any real release, scrap or downgrade decision, and not for
any judgement about how serious a flagged part is. Per the project charter, a
risk score is not a production stop decision.

## 2. Data

MVTec AD, MVTec Software GmbH, four of its fifteen categories. Research use
only. Each category ships a `train/` folder of sound parts, a `test/` folder
mixing sound and defective parts, and a pixel mask for every defective test
image.

| category | bank | calibration | test | of which defective | resolution |
|---|---|---|---|---|---|
| grid | 185 | 79 | 78 | 57 | 1024 grey |
| metal_nut | 154 | 66 | 115 | 93 | 700 colour |
| screw | 224 | 96 | 160 | 119 | 1024 grey |
| transistor | 149 | 64 | 100 | 40 | 1024 colour |

The dataset ships train/ with sound parts only and test/ with both. The train folder is cut 70%/30% at seed 42 into a memory bank and a calibration set of sound parts the bank does not hold; the shipped test/ folder is scored once.

### Nothing crosses the split, and the check is on content

Casting shipped 64 byte-identical images in both its train and test folders and
nobody had checked, which flattered its false-alarm rate. Notebook 01 hashes
every image here on file bytes and on decoded pixels: **0 of 453 test
images appears in any training folder**, no sound image is duplicated inside a
training folder, and no image is shared between categories. 147 file *names* are
shared between the two folders, which is why the check is done on content: a
name-based check would have reported 147 leaks that do not exist.

### The defects are small, and two of them are not

Measured from the shipped masks rather than estimated. The median defect covers
0.29 per cent of the frame in `screw` and 0.60 per cent in `grid`, about 55 by 55
and 79 by 79 pixels of a 1024-pixel frame. Two defect types are the opposite:
`metal_nut/flip` covers 0.48 of the frame and `transistor/misplaced` 0.40,
because both are an intact part in the wrong orientation rather than a surface
fault. **Within one category the defect scale spans two orders of magnitude**,
and one threshold has to rank both ends of it.

## 3. Method

PatchCore-lite. A frozen ImageNet ResNet-18, `layer2` and `layer3` read through
forward hooks, each smoothed with a 3 by 3 average, `layer3` resampled onto
`layer2`'s grid and the two concatenated: 1600 vectors of
384 dimensions per image at input 320. A greedy coreset reduces the sound
parts to a memory bank, and a new part scores the largest distance from any of
its cells to the nearest bank vector.

**Nothing is trained.** There is no loss, no epoch, no learning rate and no
gradient anywhere in this module. What it stores is 56,960 feature vectors
selected from 1,139,200, 87.4 MB for four categories, and the whole
of the fitting is a nearest-neighbour selection.

### The design was measured against the alternatives, including the one that shipped

The notebook folder contained a skeleton implementing `layer4` averaged over the
whole frame. Notebook 02 predicted from the masks alone that this would fail:
averaging the frame gives the median `screw` defect one part in 347 of the
deciding vector, and that at `layer4` and input 224, which is what the skeleton
reads, the most covered cell of a `screw` defect is typically only 12 per cent
defect even before the average. Notebook 03 tested the
prediction on the same frozen features and the same folders.

| reduction | mean image AUROC | grid | metal_nut | screw | transistor |
|---|---|---|---|---|---|
| layer2+3 patches | **0.9817** | 0.9749 | 1.0000 | 0.9650 | 0.9871 |
| layer4 patches | 0.8131 | 0.6759 | 0.9306 | 0.7362 | 0.9096 |
| layer4 averaged | 0.7810 | 0.5873 | 0.8631 | 0.7723 | 0.9012 |
| pixel mean and sd | 0.5112 | 0.6608 | 0.5836 | 0.1898 | 0.6104 |

The two-number floor reaches 0.1898 in
screw, which is *below* chance rather than near it. A score that ranks defects consistently lower than sound parts is not noise: brightness and contrast carry a real signal there, pointing the wrong way.
Nothing depends on it, and it is reported because what a two-number summary
reaches says more about the dataset than the shipped number does on its own.

### The size of the memory bank was chosen without a single defect

The obvious criterion, which budget gives the best AUROC, would be read off the
test folder, and the test folder holds the only labelled defects this dataset
has. What a too-small bank does is measurable without any defect: it stops
covering the normal variation, so sound parts start looking anomalous. The rule
is the smallest budget at which the median score of the held-out sound parts is within 2% of what the complete bank gives them.

| category | budget chosen | vectors kept | of | hit the cap |
|---|---|---|---|---|
| grid | 5% | 14,800 | 296,000 | yes |
| metal_nut | 5% | 12,320 | 246,400 | yes |
| screw | 5% | 17,920 | 358,400 | yes |
| transistor | 5% | 11,920 | 238,400 | yes |

**The rule saturated rather than chose.** All four categories reached the
largest budget in the sweep without ever meeting the 2.0 per cent tolerance, so what
shipped is the cap and not a point the criterion selected. This is the same shape
of failure as the NEU confidence band, which could not be calibrated because the
selection set held no mistake: a rule that returns its own boundary has not
answered the question, and saying so is the only honest use of it. What the rule
did do is keep the decision away from the test folder, and the section below is
what that cost.

Measured after the fact on screw, the category with the smallest defects:

| memory bank | vectors | image AUROC |
|---|---|---|
| every patch | 358,400 | 0.9783 |
| coreset 0.5% | 1,792 | 0.9678 |
| coreset 1% | 3,584 | 0.9818 |
| coreset 2% | 7,168 | 0.9688 |
| coreset 5% | 17,920 | 0.9650 |
| random 5% | 17,920 | 0.8407 |

The shipped budget reaches 0.9650 against 0.9783 for the complete bank,
so the reduction costs +0.0133 AUROC, and a random sample of the same
size reaches 0.8407, so the greedy selection is worth +0.1243 over
drawing the same number of vectors at random. **That last number is the only one
in the table that is larger than the measurement error.** The coreset budgets
span 0.0168 AUROC between best and worst and they do not
even order monotonically, against a standard error of 0.016 to 0.025 that
notebook 01 measured for a single category on these test folders. **So the sweep
cannot distinguish its own budgets**, the sound-parts criterion had nothing to
track, and the right reading is that the budget does not matter much above about
one per cent while the *kind* of reduction does.

## 4. Performance

Measured on the folder the dataset ships as test/, scored once.

| category | image AUROC | pixel AUROC | defects found | recall | false alarms | false-alarm rate |
|---|---|---|---|---|---|---|
| grid | 0.9749 | 0.9841 | 54 of 57 | 94.7% | 3 of 21 | 14.3% |
| metal_nut | 1.0000 | 0.9842 | 93 of 93 | 100.0% | 5 of 22 | 22.7% |
| screw | 0.9650 | 0.9948 | 103 of 119 | 86.6% | 4 of 41 | 9.8% |
| transistor | 0.9871 | 0.9322 | 39 of 40 | 97.5% | 8 of 60 | 13.3% |

Mean image AUROC 0.9817, mean pixel AUROC 0.9738.

**Read the four rows, not the mean.** They span 0.0350 AUROC, from
0.9650 in screw to 1.0000 in metal_nut, and notebook 01
measured a standard error of 0.016 to 0.025 on each because the sound group in
these test folders is 21 to 60 images. The mean hides both facts.

### Localisation costs nothing extra and is generous by construction

The per-cell scores are computed on the way to the image score, so the anomaly
map is free. It is resampled to 320 by 320, smoothed, and scored against
the shipped masks as the metrics file records it: computed at 320 by 320 over every pixel of every test image, sound ones included, so it is not comparable with published MVTec figures at native resolution.

And pixel AUROC flatters: defect pixels are
0.250% to 11.719% of the
total, so a map that is roughly right everywhere scores well. The share is
printed beside the metric for that reason.

### Does it reproduce

**Exactly, apart from the thresholds.** The whole pipeline was run twice from the same seed in the same
session: features, coreset, threshold, scores. The memory banks came back
bit-identical in every category, the largest difference on any test score was
0.000e+00, and 0 of 453 decisions changed.

**The thresholds are the one thing that moves, and only just.** They shift by
8.0e-06 to 3.4e-05 between the two runs, against thresholds of
1.7111 to 2.0822. Each one is a quantile of the calibration
scores, which the second pass recomputes and which the comparison above does not
cover, so the movement locates a difference the test scores do not show. Nothing
downstream of it changes: not a decision, not a band edge, not a published event.

The reason is structural rather than lucky. Casting's fine-tuned arm never
returned the same numbers twice while its frozen arm was bit-identical every
time, which located the non-determinism in the convolution backward pass. **This
module has no backward pass.** Casting's operating point spans 0.0436 to 0.2203
across four runs of one seed; these four thresholds move in their fifth decimal.

### What the calibration holdout costs

Thirty per cent of the sound training parts are held out so the threshold has a
source. Building the bank from every sound part instead:

| category | bank from 70% | bank from 100% | cost |
|---|---|---|---|
| grid | 0.9749 | 0.9791 | -0.0042 |
| metal_nut | 1.0000 | 0.9976 | +0.0024 |
| screw | 0.9650 | 0.9785 | -0.0135 |
| transistor | 0.9871 | 0.9937 | -0.0066 |

The larger bank cannot be shipped: with no held-out sound parts there is no
honest threshold. This is the price of having one, as a number rather than an
argument.

## 5. Priority mapping (charter section 7.1)

The lowest score that flags no more than 5% of the calibration parts, which are sound parts the memory bank does not hold. A second edge comes from the same
distribution at no extra cost: the highest score any sound calibration part
reached.

| category | calibration parts | median sound score | threshold | ceiling | realised false alarm |
|---|---|---|---|---|---|
| grid | 79 | 1.5998 | 1.7574 | 1.7824 | 3.8% |
| metal_nut | 66 | 1.8766 | 2.0246 | 2.0390 | 4.5% |
| screw | 96 | 1.5205 | 1.7111 | 1.8896 | 4.2% |
| transistor | 64 | 1.8069 | 2.0822 | 2.2878 | 4.7% |

    score above the ceiling    no sound calibration part reached this, P2
    score above the threshold  inside the range sound parts reach, P3
    below the threshold        suppressed, no event

| category | events | P2 | P3 | suppressed | defects not flagged | sound parts published |
|---|---|---|---|---|---|---|
| grid | 57 | 55 | 2 | 21 | 3 | 3 |
| metal_nut | 98 | 97 | 1 | 17 | 0 | 5 |
| screw | 107 | 73 | 34 | 53 | 16 | 4 |
| transistor | 47 | 37 | 10 | 53 | 1 | 8 |

309 events from 453 test images, 262 P2 and 47 P3, 144
parts suppressed as sound. 20 defective parts are never published, which is
the recall gap of section 4 seen from the other side, and 20 sound
parts reach an operator as a false alarm.

**The priority says how unusual, never how dangerous.** Ranking a scratch against
a bent lead against a flipped nut by severity would need engineering judgement
about these parts that this project does not have, and an invented ranking would
be worse than none. **There is no P1 band** for the same reason: P1 in the
charter means safety-relevant, and a detector fitted only to sound parts has no
basis for that call.

**The scalar the contract carries** is `score / (score + threshold)`.
It is bounded, monotone in the score, never saturates, and puts the threshold at
exactly 0.5 for every category whatever its raw distances look like. The raw
distance rides in `evidence.prediction` so ranking above the band is not lost.

### This is the casting lesson applied, not restated

Casting chose its threshold by searching a cost curve computed on scored data.
The curve was nearly flat, the scores moved between runs of identical code, and
the chosen point moved with them by a factor of five. Two sessions established
that no rule reading those scores can be stable while the curve underneath moves.
**So this module does not search.** It states a budget and reads a quantile of a
fixed set of sound parts, and there is no optimum for run-to-run noise to
relocate.

## 6. Limitations

1. **The benchmark ships no anomalous validation data, so the design was tuned on
   the folder the module is scored on.** MVTec AD provides sound parts for
   fitting and mixed parts for reporting, and nothing in between. Any reasoning
   about how big a defect is, or which layer resolves it, comes from the only
   labelled defects the dataset has. The threshold and the memory-bank budget are
   **the two decisions this module kept clean**, both made on sound parts alone,
   and they are the two that decide what an operator sees. Everything else,
   including the choice of `layer2` with `layer3` and the input size, is a choice
   informed by the test folder. This inflates the reported AUROC by an unknown
   amount and it is a property of the benchmark rather than of this module.
2. **The module cannot say what is wrong.** It reports a distance and a region.
   It has no defect vocabulary, cannot separate a scratch from contamination, and
   cannot rank severity. An operator receives *this part is unlike the sound
   ones, look here*, and everything after that is a person.
3. **20 defective parts of 309 are never published.** Recall at
   the shipped threshold runs 86.6% to
   100.0%, so the worst category misses
   13% of its defects. The threshold is set by a false-alarm budget on sound
   parts and nothing in this module argues that this is the right trade for a
   real line; a plant would set the budget from the cost of a missed defect,
   which this dataset does not carry.
4. **The false-alarm budget does not transfer as promised.** 5.0 per cent
   was set on the calibration parts and the realised rate there is
   3.8% to 4.7%,
   but on the test folders it is 9.8% to
   22.7%. That gap is how far a
   quantile of 64 to 96
   sound parts carries to a folder it never saw, and it is the honest limit of
   the rule.
5. **The calibration sets are too small for a tighter budget.** A 1 per cent
   budget on 64 parts is the single
   highest observation, which is an extreme value rather than a percentile. 5 per
   cent is what the sample size supports, not what an inspection line would want.
6. **These test folders are not a production line.** They are 40 to 81 per cent
   defective by curation, so no false-alarm rate or precision read off them
   transfers to a plant, and the module has never seen the class balance it would
   meet in service.
7. **Three modules now share the `visual_inspection` domain.** Casting, NEU and
   this one publish into the same business domain across three different
   departments, so an incident query filtered by
   `business_domain=visual_inspection` returns all three. Filtering by
   `source_module` still separates them. Nothing is broken; the domain has simply
   stopped being any kind of proxy for a module.
8. **The memory-bank rule did not choose, it saturated.** All four categories reached
   the largest budget in the sweep without meeting the tolerance, so the shipped
   size is the cap. Section 3 shows the sweep is inside the measurement error
   anyway, so nothing is likely to be lost by it, but a rule that returns its own
   boundary is not a rule that has been tested. Widening the sweep is the
   experiment that would test it.
9. **Four categories of fifteen.** The dataset ships fifteen and this module uses
   four. Nothing here says how the method behaves on the eleven it has not seen,
   and the four it does use disagree by 0.0350 AUROC among themselves.

## 7. Reproduction

Everything below runs from the repository root with the project venv active.

```bash
jupyter nbconvert --execute --to notebook --inplace notebooks/03_cv/03_mvtec_anomaly/01_mvtec_eda.ipynb
jupyter nbconvert --execute --to notebook --inplace notebooks/03_cv/03_mvtec_anomaly/02_mvtec_preprocessing.ipynb
jupyter nbconvert --execute --to notebook --inplace notebooks/03_cv/03_mvtec_anomaly/03_mvtec_modeling.ipynb
python events/make_events_mvtec.py
```

Notebook 03 writes all three kinds of artifact and logs five runs to MLflow. It
is the long one: it extracts features for every image several times over, builds
each memory bank twice, and runs the whole pipeline a second time to answer
section 4.

**Expect the numbers to be identical**, unlike casting and NEU. Section 4 records
the measurement rather than the assumption. The reported figures in this card
come from the run stored in `models/checkpoints/mvtec/mvtec_cv_meta.json`, and
notebook 03 compares any new run against a second pass of its own rather than
against that file.
