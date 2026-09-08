# Initial Service-Level Objectives

These are P0 baselines and may be tightened only through a dated ADR.

| Area | Baseline | Measurement |
|---|---:|---|
| Contract validation | 100% rejection of malformed required fields | Schema and model tests |
| Local startup | <= 2 seconds with no model or memory provider | P5 startup benchmark |
| At-least-once delivery | No silent loss in the local test broker | P7 fault-injection tests |
| Audit correlation | 100% of accepted work has task/work/policy references | P6/P8 evidence tests |
| Recovery | No unbounded retry or queue growth | P3/P7 bounded retry tests |

