# OCR dataset quality audit

`planline.ocr_quality` produces a read-only report before you start a fine-tuning run. It checks the crop dataset and existing split plan; it does not alter labels, remove duplicates, or rebuild splits.

## Run

```powershell
py -3 -m planline.ocr_quality --dataset datasets/ocr/handwritten-dimensions
```

Save a report for comparing dataset revisions:

```powershell
py -3 -m planline.ocr_quality --dataset datasets/ocr/handwritten-dimensions --output datasets/ocr/handwritten-dimensions/quality-report.json
```

Use `--fail-on-warnings` in scripts when warnings should make the command return exit code 1. Invalid manifests or unreadable crop files return exit code 2.

## What it checks

- Manifest/image/checksum validity using the dataset validator.
- Number of verified samples, drawings, writers and text styles.
- Character frequency and label-length distribution, useful for checking the model's character coverage.
- Duplicate crop images and identical images assigned conflicting labels.
- Blank labels, leading/trailing whitespace, unusually short or long strings, and non-ASCII letters that may not be represented by the recogniser's character dictionary.
- Presence and coverage of a train/validation/test split plan.
- Leakage of a drawing source or writer ID across multiple splits.

## Interpreting the report

Warnings are deliberately conservative. A small dataset is useful for exercising the annotation and training workflow, but it is not evidence of generalisation. A warning about few writers means the test split cannot establish performance on unseen handwriting authors. A warning about few sources means it cannot establish generalisation to unseen drawings.

`ready_for_training` is a gate for obvious dataset hygiene only. It is not a claim that the dataset is large, representative, balanced, or sufficient for a reliable model. Review the labels and sample images manually before training. Benchmark only on the held-out test split after model selection is complete.

The report is local by default. Keep the `datasets/` directory out of Git when it contains scans or plan-derived crops.