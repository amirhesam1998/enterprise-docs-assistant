# OCR evaluation tiers

- `committed_sanitized`: legally safe, small fixtures intended for CI. No real
  fixture or CER/WER baseline is included yet.
- `local_private`: ignored local material derived from private documents. Keep
  source files, expected text, and page-specific labels inside that directory.

The ignored local manifest registers available diagnostic pages without copying
their PDF or inventing transcriptions. Until owner-approved ground truth exists,
CER/WER are unavailable and only classification, route, gate, duration, and
compact candidate metrics may be reported.

`manifest.example.json` documents the shared shape. Load it with
`eda.evaluation_schema.EvaluationManifest` after replacing example entries with
approved fixtures.
