# Online Demo Deployment

The competition demo is designed for Streamlit Community Cloud and defaults to deterministic replay mode. It does not require an API key, database, external service, or writable persistent storage.

- Live demo: <https://youjie-goai-2026.streamlit.app/>
- Public repository: <https://github.com/RexKing6/youjie-agent>
- Deployment runtime: Python `3.12`, Streamlit Community Cloud.

## Repository contract

- Repository root: this project directory.
- Entrypoint: `app.py`.
- Python: `3.12`, matching the verified local environment.
- Dependencies: `requirements.txt` at the repository root.
- Default mode: `replay`; public reviewers do not need secrets.
- Public data: the checked-in Mendeley `.xlsb` and derived case files are required at runtime.

## Deploy on Streamlit Community Cloud

1. Push this project to a public GitHub repository.
2. Sign in at <https://share.streamlit.io> with the same GitHub account.
3. Create an app and select the repository, default branch, and `app.py`.
4. In Advanced settings select Python `3.12`.
5. Do not add secrets for the public competition demo.
6. Choose a stable custom subdomain if available, then deploy.
7. Open the public URL in a signed-out browser and run both the fixed-mail and random-drill paths.

Official references:

- <https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy>
- <https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies>

## Post-deploy acceptance

The public deployment was created on 2026-08-09. Its first build completed and the public-data evidence page loaded without a model secret.

- The home page loads without a secret or login prompt.
- The Mendeley public-data badge and synthetic-overlay boundary are visible.
- Fixed-mail analysis reaches a real LangGraph approval interrupt.
- Rejecting creates zero work orders.
- Approving revalidates scenario and plan hashes before producing only `draft_only` work orders.
- A seeded random drill produces a valid incident and can traverse the same guarded workflow.
- The public URL is added to the competition submission, README, demo video description, and final slide.

## Live-model boundary

Live OpenAI-compatible mode is optional and intentionally disabled in the public deployment. If it is enabled later, secrets must be configured only in the hosting platform, never committed to the repository. The live model still cannot calculate feasibility, approve plans, or create executable work orders.
