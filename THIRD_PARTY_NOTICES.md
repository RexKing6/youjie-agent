# Third-party notices

## Mendeley Data

This repository includes and derives a competition case from:

> Optimisation model for multi-item multi-echelon supply chains with nested multi-level products

- DOI: <https://doi.org/10.17632/pr3sdy5vp3.1>
- Dataset page: <https://data.mendeley.com/datasets/pr3sdy5vp3/1>
- License: CC BY 4.0
- Included source file SHA-256: `1ea0bcdea3225d308be913c9ca0f377585e1863847c78d6e8eec10b6de82889e`

The public workbook is industry-grounded randomized data based on an automotive production network; it is not represented as raw operational data from a named company. Customer names, priorities, incident messages, emergency sourcing, prices, budgets, and approvals are synthetic overlays and are labeled as such in the case provenance.

## Open-source runtime dependencies

有界 uses third-party Python packages including LangGraph, OR-Tools, Pydantic, Streamlit, Altair, and pyxlsb. Each package remains governed by its own license. Dependency versions used by the public demo are recorded in `requirements.txt`.

## OpenMES local test runtime

The optional independent MES demonstration runs the unmodified upstream project:

- Project: [Mes-Open/OpenMes](https://github.com/Mes-Open/OpenMes)
- Pinned commit: `f0ccdd1c7a57804212ed337d340aebfeebacc372`
- License: GNU Affero General Public License v3.0 (AGPL-3.0)
- Use in this repository: external, local test runtime reached through its documented HTTP API. The upstream source is not copied into the submission ZIP.

有界's Apache-2.0 adapter code is a separate client integration. It does not relicense, embed, or modify OpenMES. Anyone operating or modifying OpenMES remains responsible for the upstream AGPL-3.0 terms.
