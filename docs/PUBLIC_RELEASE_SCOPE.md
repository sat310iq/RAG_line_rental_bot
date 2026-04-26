# Public Release Scope (PoC Minimal)

This document freezes the intended public scope for the GitHub release of `rental_rag_poc`.

## Include

- `src/`
- `scripts/`
- `tests/`
- `docs/`
- `eval/datasets/line_rag_eval_router_abcd_v1.csv`
- `env.example`
- `env.gcp.example`
- `deploy/.env.gcp.example`
- `requirements.txt`
- `README.md`

## Exclude

- `.env`
- `.env.gcp`
- `deploy/.env.gcp`
- `data/vector_store/`
- `eval/runs/`
- `logs/`
- `data/eval/*.json`

## Notes

- Evaluation data published in `eval/datasets/line_rag_eval_router_abcd_v1.csv` must remain synthetic or anonymized.
- If secret patterns are detected in files or Git history, publication must be blocked until remediated.
- Environment values are template-driven: commit `*.example` files only; keep generated `.env*` local.
