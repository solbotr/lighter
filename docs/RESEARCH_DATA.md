# Research Data Controls

Research data is immutable, timestamped, provenance-aware, and point-in-time queryable.

## Dataset controls

- Raw-event preservation
- Normalized-event preservation
- Source provenance
- Ingestion timestamp
- Publication timestamp
- First-seen timestamp
- Revision history
- Deletion/retraction history
- Point-in-time asset mapping
- Point-in-time market metadata
- Point-in-time source availability
- Feature lineage
- Label lineage
- Dataset versioning
- Dataset checksums
- Split manifests
- Leakage checks
- Duplicate checks
- Missing-data report
- Outlier report
- Coverage report

## Research rule

No feature may use information that was unavailable at the decision timestamp. Evaluation code must make future-data access difficult by construction, not merely by convention.
