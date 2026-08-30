# Online Demo Deployment

The competition demo supports both live and deterministic replay modes. When model credentials are present, the local UI defaults to Live; without credentials it automatically exposes Replay and still requires no database, external service, or writable persistent storage.

- Live demo: <https://youjie-goai-2026.streamlit.app/>
- Public repository: <https://github.com/RexKing6/youjie-agent>
- Deployment runtime: Python `3.12`, Streamlit Community Cloud.

## Repository contract

- Repository root: this project directory.
- Entrypoint: `app.py`.
- Python: `3.12`, matching the verified local environment.
- Dependencies: `requirements.txt` at the repository root.
- Default mode: `live` when credentials exist, otherwise `replay`; public reviewers do not need secrets.
- Public data: the checked-in Mendeley `.xlsb` and derived case files are required at runtime.

## Deploy on Streamlit Community Cloud

1. Push this project to a public GitHub repository.
2. Sign in at <https://share.streamlit.io> with the same GitHub account.
3. Create an app and select the repository, default branch, and `app.py`.
4. In Advanced settings select Python `3.12`.
5. To enable Live, add endpoint/model/key only in Streamlit Secrets; otherwise leave secrets empty and publish Replay.
6. Choose a stable custom subdomain if available, then deploy.
7. Open the public URL in a signed-out browser and run both the fixed-mail and random-drill paths.

Official references:

- <https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy>
- <https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies>

## Current public acceptance status

The deployment was created on 2026-08-09. The original smoke test showed that the app could load without a model secret, but that observation is historical and is not proof that the current public URL remains reachable.

On 2026-08-25 an external cookie-free HTTP probe received `303` with a redirect to `https://share.streamlit.io/-/auth/app?...`, while the Streamlit Sharing panel displayed `This app is public and searchable`. The contradiction is an active **P0 failure** until an external HTTP probe and a signed-out browser both pass.

Run the fail-closed probe after every deployment or sharing change:

```bash
python scripts/check_public_demo.py \
  https://youjie-goai-2026.streamlit.app/ \
  --output artifacts/public_demo_probe.json
```

Do not claim the online Demo is accepted while this command exits non-zero. After it passes, re-run the fixed-mail approval path, rejection path, seeded drill, and three fresh-session repeatability checks defined in `docs/semifinal_adversarial_acceptance.md`.

## Live-model boundary

Local semifinal validation uses `qwen3.8-max`; its 3×30 report is in `artifacts/live_agent_eval_report.json`. Public Live remains optional. Secrets must be configured only in the hosting platform, never committed or packaged. The live model still cannot calculate feasibility, approve plans, or create executable work orders.

## Local ERPNext validation runtime

The semifinal engineering evidence also supports a real local ERPNext test instance. This is separate from Streamlit hosting and is not required for replay mode.

- Official upstream: `frappe/frappe_docker`, pinned locally at commit `ba450260c52eb1b186fe7ba0bec8b61299bb9037`.
- Verified application versions: ERPNext `16.33.0`, Frappe `16.31.0`.
- Local binding: `127.0.0.1:8088`; never expose the test instance publicly.
- Synthetic company: `Youjie Demo Manufacturing`; no enterprise or personal data.
- API boundary: read allowlist plus draft-only Material Request / Work Order creation. No submit, cancel, delete, arbitrary RPC or device control.

Start the official Docker stack, finish the synthetic fixture setup, and store credentials outside this repository as a mode-0600 JSON file. Then run:

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_erpnext_real.py \
  --credential-file /absolute/path/to/erpnext_credentials.json \
  --ledger /absolute/path/to/erpnext_validation.sqlite3
```

To expose the real test-instance option in the local judge API without changing `.env` or Streamlit Secrets:

```bash
DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE=/absolute/path/to/erpnext_credentials.json \
  .venv/bin/python -m delivery_guard.demo_api --port 8765
```

`artifacts/erpnext_real_validation.json` is safe to submit and contains only redacted host metadata, document IDs, status, revision and evidence hashes. The credential file, Docker volumes and SQLite runtime ledger must never be packaged.

## Local OpenMES validation runtime

The independent real MES proof uses the official [Mes-Open/OpenMes](https://github.com/Mes-Open/OpenMes) repository pinned to commit `f0ccdd1c7a57804212ed337d340aebfeebacc372` (AGPL-3.0). It is bound to `127.0.0.1:8090` and must not be publicly exposed.

The tested runtime uses OpenMES' own PostgreSQL, queue and web UI only as upstream product dependencies. 有界 never reads its database directly. The adapter allowlist contains only:

- `POST /api/v1/erp/work-orders/import`;
- `GET /api/v1/erp/production/completions`;
- `GET /api/v1/erp/quality/issues`;
- `GET /api/health`.

Bootstrap the clearly synthetic line/product/process master data:

```bash
OPENMES_ADMIN_USERNAME='<local-test-admin>' \
OPENMES_ADMIN_PASSWORD='<local-test-password>' \
PYTHONPATH=src .venv/bin/python scripts/bootstrap_openmes_test.py \
  --base-url http://127.0.0.1:8090
```

After explicit permission to create a local test credential, issue a least-privilege key to an ignored chmod-600 file:

```bash
OPENMES_ADMIN_USERNAME='<local-test-admin>' \
OPENMES_ADMIN_PASSWORD='<local-test-password>' \
PYTHONPATH=src .venv/bin/python scripts/issue_openmes_api_key.py \
  --base-url http://127.0.0.1:8090 \
  --output /absolute/private/path/openmes_credentials.json
```

Expose both real-system options to the localhost judge API without editing `.env`:

```bash
DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE=/absolute/private/path/erpnext_credentials.json \
DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE=/absolute/private/path/openmes_credentials.json \
  .venv/bin/python -m delivery_guard.demo_api --port 8765
```

OpenMES records remain test records. Changing a work-order status in its UI proves application-level execution feedback, not physical equipment execution. Machine commands, line start/stop, OPC UA writes, Modbus writes and MQTT commands are not callable through the adapter.
