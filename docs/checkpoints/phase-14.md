# Phase 14 — CI/CD

## Delivered

- GitHub Actions pipeline for every pull request and push to `main`.
- Python 3.12 dependency caching, lint, formatting and non-external test gate.
- Independent production container build gate.
- Dashboard assets explicitly included in the Python distribution.

Any failing command fails its job and prevents a green pipeline.
