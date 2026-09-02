# Model Card: GC10 Steel Sheet Defect Detection

**Module:** Arkon computer vision, defect localisation
**Department (fictional):** Stamping
**Version:** `gc10_fasterrcnn_v1`
**Built:** 2026-09-02, as a notebook trio with no training script behind it
**Notebooks:** `notebooks/03_cv/04_gc10_steel_defects/`
**Metrics file:** `models/checkpoints/gc10/gc10_cv_meta.json` - every number in this
card is read from it by a generator, so the card and the run cannot drift apart.

---

## 1. Intended use

This module locates defects on photographs of steel sheet and names each one. It is
the sixth Arkon model module, the fourth in the `visual_inspection` domain, and the
only one that answers **where**.

That is the whole reason it exists. `docs/Model_Card_NEU_Surface.md` limitation 3
records that NEU discards 4,189 Pascal VOC boxes and returns one label for a whole
frame, so an operator asking where a defect is gets nothing, and it names this
module as where localisation belongs. Repeating NEU with ten classes instead of six
would have added a fifth model and answered no new question.

**What it is for.** A coil arrives at a stamping press. The module returns a list of
located defects with a class and a confidence for each, and the Steering Cell turns
that into one incident per sheet with a priority the operator can act on.

**What it is not for.** It cannot say a sheet is sound. Section 6 limitation 1 is
the whole of that: this module has never seen steel anyone certified clean.

---

## 2. Data

**GC10-DET**, 2,312 image files of hot-rolled steel sheet at 2048 x 1000,
single-channel, with Pascal VOC boxes in a folder the dataset spells `lable`.
Ten defect classes: punching hole, welding line, crescent gap, water spot, oil spot, silk spot, inclusion, rolled pit, crease, waist folding.

### The folders are not a labelling, and the boxes are

Notebook 01 measured this rather than assuming it. **476 of the 2,292 annotated
sheets, one in five, carry a defect class their folder never names**, and 88
annotation files contradict their own `<folder>` field. Twelve sheets are filed in
two class folders each, which is the visible tip of the same thing. So the class of
a sheet comes from its boxes, and the folder number is used for nothing after
notebook 01.

This is also what settles NEU limitation 4, which records that 6.8 per cent of NEU
images carry a second defect class its single-label formulation must discard. A
detector holds as many classes as the sheet has.

### Three label repairs, each counted

1. **Class 10 is spelled two ways.** The annotations carry `10_yaozhed` on 131 boxes
   and `10_yaozhe` on 12; the shipped class key spells it the second way, which is
   the minority spelling in the files. Both map to class 10.
2. **One box is tagged `d`**, which matches no class in the key. It is dropped, 1
   box in 3,564; the sheet it sits on keeps its other box and stays in the dataset.
3. **Eight sheets carry no box at all** - six with no annotation file and two with
   an annotation holding zero objects. All eight are dropped rather than used as
   background, because that would assert they are clean and nobody recorded that.

The shipped key declares 3,570 boxes and the annotations hold 3,564. **Nine of the
ten classes agree with the key to the box**; the entire six-box shortfall is class
10. That nine-of-ten agreement is what makes the tenth informative rather than
ambiguous: a counting method that was wrong would be wrong everywhere.

### The split is over coils, and the check that forced it

Casting shipped with 64 byte-identical images across its train and test folders and
nobody had checked, so a content check is standard in every Arkon CV module. Run
here it found something that check cannot express.

**Nothing in GC10 is duplicated, and a sheet-level split still leaks.** The distance
from a sheet to its nearest neighbour runs smoothly from 0.38 to 34 grey levels with
no gap, so there is no set of duplicates to remove and every threshold is a choice
rather than a boundary. Clustering makes it worse: closeness is not transitive, and
at 8 grey levels one connected component holds more than half the dataset.

**The file name carries the unit that works.** Every stem is
`img_<a>_<source>_<frame>`, and the middle field is the coil. **93 per cent of sheet
pairs closer than 2 grey levels share a source, against 1.1 per cent of random
pairs**: a fifty-fold enrichment. These are consecutive frames of one coil.

So the split unit is the coil. What that bought, measured on the thing it was meant
to fix: at 2 grey levels **53 pairs cross the split, against 777 under the same
proportions dealt over sheets**. The residue is real and is not rounded away - some
sheets from different coils genuinely look alike, and nothing here can tell those
from a coil photographed twice under two ids.

| Split | Sheets | Boxes | Coils |
|---|---|---|---|
| fit | 1619 | 2508 | 289 |
| selection | 334 | 511 | 95 |
| test | 339 | 544 | 83 |

The proportions are 70 / 15 / 15, allocated rarest class first and largest coil
first. The rare classes decide that: class 9 appears on 53 sheets in the whole
dataset, so a random draw could put 3 in the test set or 13.

### The defects are small

Median box area is 0.0348 of the 2048 x 1000 frame and the 5th percentile is 0.0013.
The shortest box side has a median of 128 pixels and a 5th percentile of 41. **35 per
cent of sheets carry more than one defect and one carries eleven**, which is the
measurement behind the event shape in section 5.

---

## 3. Method

`fasterrcnn_resnet50_fpn_v2` from `torchvision` with COCO weights and a fresh
eleven-way box head: ten defect classes plus the background class the architecture
requires. Input 800 / 1600, batch 2, SGD at 0.005 with a
linear warmup over 500 iterations and a ten-fold drop at epoch 8,
mixed precision, 10 epochs, seed 42.

**Augmentation is the two flips and nothing else.** The NEU module also rotates up
to ten degrees; that cannot be copied here, because an axis-aligned box cannot
follow a rotation. Rotating the image and keeping the box puts the defect outside
its box; recomputing the enclosing box grows it over background nobody marked.
Either way the label stops being the label. The flips are exact and were verified on
pixel content, not by eye.

**The single channel is repeated three times** because every pretrained detector
expects three, so two thirds of the input carries nothing the first convolution has
not already seen. It is repeated on the GPU after the transfer: notebook 02 measured
the obvious alternative at three times the CPU cost and twelve times the bytes.

### The input scale was measured, and it changed the plan

The first intention was native 2048 x 1000, on the argument that the defects are
small and nothing should be thrown away. Timed on an RTX 3070 under sustained load,
**one training step of two sheets costs 0.92 s at 1000 / 2048 and 0.32 s at 800 /
1600**: 2.9 times the time for 1.6 times the pixels. Three arms of ten epochs is six
hours at the first number and two at the second.

**And 800 is not only the cheap choice, it is the scale the weights were fitted at.**
`fasterrcnn_resnet50_fpn_v2` ships with `min_size=800`, so running at 1000 puts the
input above the pretraining distribution as well as above the compute budget. The
cost is real and unmeasured: the 5th-percentile defect is 41 pixels on its shortest
side and becomes 32 after the scale, and measuring what that costs means training
both, which was not affordable.

### The metric is this repository's own

Neither `torchmetrics` nor `pycocotools` is in this environment. Adding a dependency
to compute one number would need flagging under this project's conventions, and a
metric imported is a metric nobody here can audit, so VOC 2010 all-point average
precision is implemented in notebook 03 section 4 in about forty lines.

**It is validated before it is used**, against six cases whose answers are known in
advance, two of them computed by hand: predictions equal to the ground truth return
exactly 1.0, nothing predicted returns 0.0, a class absent from the truth returns
`nan` rather than a zero that would report a failure that never had a chance to
happen, a duplicate box on a matched target counts as a false positive, a box at IoU
0.333 does not count, and a four-detection case returns (1 + 1 + 3/4) / 3 to machine
precision. The notebook stops if any of the six fails, because nothing after it
would be valid.

---

## 4. Performance

Scored once on 339 sheets from 83 coils that neither the
fitting nor the threshold selection has seen.

| Measure | Test | Selection |
|---|---|---|
| mAP at IoU 0.5 | **0.5878** | 0.5978 |
| mAP at IoU 0.75 | 0.2223 | 0.2620 |

The best epoch is 9 of 10, so the last 1 epochs bought nothing on the selection split and the schedule is longer than the task needs.

### The per-class spread is not explained by the counts

| Class | Defect | AP at IoU 0.5 | Boxes in the test split |
|---|---|---|---|
| 1 | punching hole | 0.9799 | 61 |
| 2 | welding line | 0.8373 | 87 |
| 3 | crescent gap | 0.9963 | 49 |
| 4 | water spot | 0.6307 | 41 |
| 5 | oil spot | 0.5815 | 54 |
| 6 | silk spot | 0.2935 | 167 |
| 7 | inclusion | 0.4674 | 39 |
| 8 | rolled pit | 0.3080 | 14 |
| 9 | crease | 0.1736 | 11 |
| 10 | waist folding | 0.6100 | 21 |

**The obvious explanation is wrong, and the table refutes it.** Before the run it
looked as though the spread would mostly be a matter of how many boxes stand behind
each class. It is not: **silk spot has the most boxes of any class, 167, and
scores 0.2935**, near the bottom. The counts do matter at the thin end -
Crease (n=11), rolled pit (n=14) are scored on fewer than twenty boxes each and an AP on that many moves
by whole tenths when one detection changes - but they do not order the table.

**What does order it is how well-defined the defect's own boundary is.** The classes
at the top are sharp geometric features: crescent gap at 0.9963 and punching hole
just below it, where a box has one obvious right answer. The classes at the bottom are
diffuse: silk spot is a low-contrast texture spread over a median tenth of the frame
with a 1.11-decade spread in size, so where its box ends is a judgement, and an IoU of
0.5 against one annotator's judgement is a hard target. That is a property of the
annotation as much as of the model, and it is not something more epochs would fix.

### What the module claims, and what it lets past

At the detection threshold of 0.65, on the test split:

- **332 of 544 annotated boxes located**, so 212 were missed.
- **218 boxes claimed that are not there.**
- Precision 0.6036, recall 0.6103.
- **308 of 339 sheets publish an event** and 31 stay
  silent because nothing on them scored above the threshold.

### What adapting the features is worth

The frozen-backbone ablation fits only the region proposal network and the detection
heads, leaving every backbone convolution at its COCO values. It reaches
**0.5175 mAP@0.5 against 0.5878 fine-tuned, a gap of +0.0704**.
Casting and NEU ran the same ablation, so the three computer vision modules answer
one question on one basis.

### Does it reproduce

**No, and it reaches the operating point.** 5 of 6 recorded values moved. The detection threshold the rule returns went 0.65 to 0.55 and the number of sheets publishing an event went 308 to 311, so a refit at the same seed changes who is asked to look at a coil.

**And the headline moved with it, in the direction that matters for how it should be read.** Test mAP@0.5 went 0.5878 to 0.6235, +0.0357, so **the shipped model is the worse of two draws** and 0.5878 is one sample rather than a property of the design. For scale, that swing is 51 per cent of the +0.0704 the frozen ablation measures as the whole worth of fine-tuning the backbone. Anything comparing this module against another on a difference smaller than that is comparing draws.

**This is the casting result again, on a different architecture.** `docs/Model_Card_Casting_CV.md` limitation 6 records four runs from one seed spanning an operating point from 0.0436 to 0.2203, and locates the cause in the cuDNN convolution backward pass rather than in the code, because its frozen arm was bit-identical every time. Nothing here contradicts that, and this module inherits the consequence: a threshold read off a curve that a refit moves is a threshold with a draw in it. The MVTec module escaped this by having no backward pass at all.

---

## 5. Priority mapping (charter section 7.1)

The best surviving box on the sheet decides:

    best box score >= 0.90   the located defect can be recorded, P3
    best box score <  0.90   the module found something and cannot name
                                        it confidently, a person looks, P2
    no box above 0.65    nothing is published at all

**There are two operating points here and every other Arkon module has one.** A
detector needs one threshold to decide what counts as a box at all, and this module
needs a second to decide how sure it is about the sheet, because the event it
publishes is about the sheet.

- **What counts as a box: 0.65**, calibrated on the selection split. The rule was
  declared before the curve was looked at: the lowest score at which precision over
  the selection split reaches 0.60. Precision rather than recall,
  because the cost of a wrong box lands on an operator who walks to a coil and finds
  nothing.
- **How sure about the sheet: 0.90**, declared, because the rule returned nothing on the selection split. The rule: the lowest
  best-box score at which the sheet's top detection is correct at IoU 0.5 at least
  90 per cent of the time. Above that edge the top detection is right
  76.0 per cent of the time on the test split.

**0.60 and 90 per cent are Arkon assumptions**, in the
same sense as casting's cost ratios. This dataset ships no statement of what a false
trip costs against a missed defect, and inventing one and calling it measured would
be worse than declaring it.

**Priority never comes from the defect class.** Ranking a crease against an oil spot
by severity needs metallurgical judgement this project does not have, which is the
NEU precedent stated in its own card.

**And never from the defect's size**, which is the less obvious half. Box area is
measurable, available and tempting, and it is a severity claim wearing a
measurement's clothes: a large water spot is cosmetic and a small crease may not be,
and nothing in this module can tell the difference. This is the MVTec lesson, whose
card says the priority may say how unusual and never how dangerous.

**No P1**, because no single sheet on an inspection line is a fifteen-minute safety
emergency, which casting, NEU and MVTec each record for the same reason. **No P4**,
because a sheet with nothing found is not published at all.

### The event carries a list, and the contract did not have to change

Every adapter before this one publishes one measurement per record. A detector
publishes n boxes on one sheet, and 35 per cent of these sheets carry more than one.

**One event per sheet, with the boxes inside `evidence.detections`.** One event per
box would give up to eleven events carrying one sheet identity and usually one
priority, and the Steering Cell deduplicates on exactly that pair for 24 hours, so
ten of the eleven would be suppressed as duplicates of a defect they are not. That
is the MVTec identity defect arriving by a different route. A sheet is also the unit
an operator disposes of.

**This was expected to need a section 6 change and did not.** `evidence` is declared
with `additionalProperties: true` and the validator checks only that the four
required keys are present, so a list fits where the contract stands. The one closed
enum that did change is `source_module`, which gained `gc10_detect` in both
`events/arkon_event_schema.json` and `events/validate_event.py`, exactly as
`neu_surface` and `mvtec_anomaly` did. Charter section 6 now says so, because it was
true before this module and nobody had written it down.

---

## 6. Limitations

1. **The module has never seen sound steel, so it cannot pass a sheet.** Every sheet
   it was fitted on, selected on and scored on contains at least one defect: GC10
   holds no clean sheet, and the eight with no annotation were dropped rather than
   assumed clean. So the 31 test sheets that publish nothing are the module
   **failing to find** a defect that is there, not the module saying the steel is
   good. Anything downstream that reads silence as a pass is wrong, and the adapter
   documentation says so in the same words.
2. **The rare classes are not really measured.** Crease (n=11), rolled pit (n=14) have fewer than
   twenty boxes each in the test split. Their AP is reported because hiding it would
   be worse, but it is a number with error bars wide enough to swallow the ordering.
   Closing this needs more data of those classes, not a better model.
3. **The input is downscaled by 0.78 and nothing measures what that costs.** Section
   3 records why: 2.9 times the training time for 1.6 times the pixels, on a budget
   that had to cover three arms. The 5th-percentile defect goes from 41 to 32 pixels
   on its shortest side. That is a real risk to the smallest defects and it is
   untested.
4. **The split still leaks a little, and by an amount that cannot be driven to
   zero.** 53 sheet pairs closer than 2 grey levels straddle the split. Splitting by
   coil cut that from 777, but similarity here is a continuum with no gap in it, so
   there is no threshold at which the leak becomes none and any claim to have removed
   it would be false.
5. **The two operating points are declared targets, not measured costs.** 0.60
   precision and 90 per cent top-detection accuracy are choices. The
   dataset carries no cost metric of the kind Scania ships, so nothing here can say
   they are the right ones.
6. **Four modules now share the `visual_inspection` domain.** An incident query
   filtered by `business_domain=visual_inspection` returns casting, NEU, MVTec and
   this one, across four departments, and the roster assigns all four to the same two
   QC Engineers. Filtering by `source_module` still separates them. The NEU card first
   recorded this at two modules and the MVTec card at three; nothing is broken, but
   the field has not been a proxy for a module for some time.
7. **One seed, one schedule, no hyperparameter search.** The learning rate, the drop
   epoch and the warmup are the `torchvision` reference values, unexamined here.
   Worse, the seed does not pin the result: see limitation 9, which governs how
   every number above should be read.
8. **A box is not a segmentation.** The module returns rectangles because that is
   what the dataset annotates. MVTec localises to the pixel without boxes and without
   training, and the honest contrast is in both directions: supervised boxes buy a
   named class and a count of instances, at the cost of 3,564 hand-drawn boxes and a
   defect catalogue known in advance, while MVTec buys "something here is unusual"
   with no labels at all and cannot say what.
9. **The module does not reproduce, and the divergence reaches the operating point.**
   Refitting from the same seed on the same machine moved 5 of
   6 recorded values. Test mAP@0.5 went 0.5878 to
   0.6235 and the detection threshold the rule returns went
   0.65 to 0.55. **So every number in section 4 is one
   draw**, the shipped one is the worse of the two that were run, and the
   two operating points in section 5 carry a draw as well as a rule. This is the casting instability on a different
   architecture and it is the single most important caveat on this card.

---

## 7. Reproduction

```bash
# 1. The dataset must be in place at data/06_gc10/raw/
python verify_setup.py

# 2. The notebooks, in order. 01 and 02 take minutes; 03 takes about
#    61 minutes on an RTX 3070 for the fine-tuned arm alone, and runs
#    three arms.
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/03_cv/04_gc10_steel_defects/01_gc10_eda.ipynb
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/03_cv/04_gc10_steel_defects/02_gc10_preprocessing.ipynb
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/03_cv/04_gc10_steel_defects/03_gc10_modeling.ipynb

# 3. The events the Steering Cell consumes
python events/make_events_gc10.py
python events/validate_event.py events/out/gc10_events.jsonl

# 4. The README figure, from the metrics file alone
python tools/make_result_plots.py
```

`nbconvert` exits 0 whether or not a cell raised. Check the executed notebook's
`execution_count` fields and its outputs, never the exit code.

**Artifacts.** `models/checkpoints/gc10/gc10_fasterrcnn_v1.pt` (weights, not tracked
in git), `models/checkpoints/gc10/gc10_cv_meta.json` (tracked, and the source of
every number here), `data/06_gc10/processed/gc10_split.json` (the split, written by
notebook 02) and `data/06_gc10/processed/test_gc10_predictions.json` (the prediction
table the event adapter reads).

The prediction table is JSON rather than the `.npz` the other CV modules use. A
detector returns a different number of boxes per sheet, so a rectangular array would
need an object dtype and the adapter would have to load it with `allow_pickle=True`;
every other Arkon adapter loads with `allow_pickle=False` on purpose.
