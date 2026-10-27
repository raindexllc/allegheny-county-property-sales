# Reference data and policy

These small CSVs make the project's assumptions reviewable. They were derived from the unchanged October 27, 2026 WPRDC snapshot recorded in `results/manifest.json`.

- `resources.csv` is the minimum expected inventory: the consolidated resource and annual 2012–2026 resources. New annual resources are discovered automatically. Removal or renaming of a baseline resource blocks a fresh download until reviewed.
- `municipalities.csv` records all 175 observed source code/name pairs. Forty-nine ward codes roll up to Pittsburgh, Clairton, Duquesne and McKeesport; the other 126 codes pass through unchanged. The city identifiers 100/200/300/400 are **project-assigned**, not asserted official county identifiers. The mapping basis is the explicit ward name in the source, not postal city. Changes require review.
- `sale_codes.csv` records 47 **observed** code/description pairs, not a complete official code dictionary. `standard_valid=true` applies only to code 0 / VALID SALE. Group labels are analytical choices; OTHER descriptions retain their ambiguity. PV is excluded from this narrow standard-valid definition.

Record identity uses parcel + sale date + deed book + deed page + instrument type. No source family is considered authoritative. Disputed price or sale classification excludes the identity from both price medians. Disagreement about municipality blocks the model because the aggregation group is ambiguous. Descriptive-only differences remain inspectable. Missing deed-key components and the same parcel/deed/instrument appearing on different dates also exclude records from price analysis; these remain candidate identities, not automatically merged events.
