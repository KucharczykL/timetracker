# PG-10: Saved preset reconciliation

Production contained three obsolete presets; the sole user explicitly chose deletion. IDs 1–3 were deleted and the subsequent read-only query returned no `FilterPreset` rows. No migration is required.
