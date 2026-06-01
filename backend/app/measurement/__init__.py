"""Measurement layer — deterministic stats/ML primitives that produce *reproducible numbers*.

Per ANALYST_ROADMAP.md §4a: anything that must be a stable, reproducible number lives here
(quant profiles, peer-closeness weights, normalization stats, cycle-state), as opposed to the
LLM reasoning layer (knowledge / language / explanation). Today this is an in-process package
behind clean function interfaces; the architecture decision is to split it into an independent
`measurement-svc` at the seam once dependency weight / retrain cadence justifies it. Keep the
interfaces narrow so that promotion is a transport change, not a rewrite.
"""
