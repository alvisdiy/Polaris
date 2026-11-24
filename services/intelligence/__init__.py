"""The intelligence layer: LLM assistance under deterministic control.

Everything in this package proposes; nothing here publishes. Values an
LLM extracts are admitted only with a verbatim evidence quote that a
deterministic verifier finds in the source document, are normalised
against the same controlled vocabularies the rest of the pipeline
uses, and are written through ``ReviewService.correct`` — the same
audited path a human edit takes. The publication gate and the human
reviewer remain the only judges.
"""
