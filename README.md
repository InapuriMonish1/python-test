# InsureLite

Minimal Flask backend for an insurance ops exercise. In-memory data, no DB.

## Structure
```
insurelite-app/
├── app.py              # Flask app, all routes
├── requirements.txt
├── tests/
│   └── test_app.py     # pytest suite
└── .gitignore
```

## Running locally (no container, just to sanity-check code before you containerize it)
```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Runs on `http://localhost:5000`. In production/containers it's served via
`gunicorn` instead (you'll wire that into your own Dockerfile — needs
`--workers 2 --threads 4` minimum, see note below).

## Running tests
```bash
pytest tests/ -v
```

## Endpoints
| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check — use this as your container/k8s probe path |
| GET | `/api/policies` | List all policies |
| GET | `/api/policies/<id>` | Get one policy |
| POST | `/api/policies` | Create a policy |
| POST | `/api/risk/score` | Internal: calculate a risk score |
| GET | `/api/policies/<id>/premium` | Premium quote — internally calls `/api/risk/score` over HTTP |
| GET | `/api/claims/<id>/status` | Get claim status |
| POST | `/api/claims` | File a new claim |

## One thing to know before you write the Dockerfile

`/api/policies/<id>/premium` makes an HTTP call to `/api/risk/score` on the
**same running instance** (via the `requests` library, using
`INTERNAL_BASE_URL`, default `http://localhost:5000`). This is intentional —
it demonstrates an internal service-to-service call pattern.

Consequence: if you run this behind a **single-threaded** server (or
`flask run` without threading), that call will hang, because the one worker
handling the incoming `/premium` request is also the only worker available to
answer the internal `/risk/score` call it's waiting on. When you containerize
this, run it with something that has concurrency — e.g. `gunicorn` with
`--workers 2 --threads 4` or more, not the Flask dev server, not a
single-worker setup.

If your AKS deployment later runs multiple replicas behind a Service, you
don't need to change `INTERNAL_BASE_URL` — each pod calls back into itself,
not across pods. If you ever split risk-scoring into its own separate
service, `INTERNAL_BASE_URL` is the env var you'd point at that service
instead.
