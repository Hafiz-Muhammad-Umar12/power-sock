# Dynamic Agentic Bridge

Observe legacy web UIs (no REST API available), map their DOM/state into structured elements, and expose those elements as dynamic MCP (Model Context Protocol) tools that AI agents can call safely — with human-approval gates for sensitive actions.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│   Backend    │────▶│  PostgreSQL  │
│  (Next.js)   │     │  (FastAPI)   │     │  (NeonDB)    │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                   ┌────────┴────────┐
                   │                 │
              ┌────▼────┐     ┌──────▼──────┐
              │Playwright│     │ Anthropic   │
              │(Browser) │     │ (Claude API)│
              └─────────┘     └─────────────┘
```

## Prerequisites

- Python 3.12+
- Node.js 18+ (LTS recommended)
- PostgreSQL database (e.g. via [NeonDB](https://neon.tech) or local)
- Anthropic API key

## Local Setup

### 1. Clone & install backend

```bash
cd dynamic-agentic-bridge/backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Install Playwright browsers

```bash
playwright install chromium
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your real values:
#   DATABASE_URL — your PostgreSQL connection string
#   ANTHROPIC_API_KEY — your Anthropic API key
#   CREDENTIAL_ENCRYPTION_KEY — generate with:
#     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4. Run the backend

```bash
uvicorn app.main:app --reload --port 8000
```

Health check: [http://localhost:8000/api/health](http://localhost:8000/api/health)

### 5. Install & run the frontend

```bash
cd ../frontend
npm install
cp .env.local.example .env.local
# Edit .env.local if needed
npm run dev
```

Dashboard: [http://localhost:3000](http://localhost:3000)

## Docker (Backend)

```bash
cd backend
docker build -t dynamic-bridge .
docker run -p 8000:8000 --env-file .env dynamic-bridge
```

## Project Structure

```
dynamic-agentic-bridge/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + CORS + lifespan
│   │   ├── config.py            # pydantic-settings config
│   │   ├── database.py          # Async SQLAlchemy engine
│   │   ├── models/
│   │   │   └── schemas.py       # Pydantic v2 request/response models
│   │   ├── core/
│   │   │   ├── observer.py      # Playwright UI observation
│   │   │   ├── mapper.py        # Claude Vision element mapping
│   │   │   └── mcp_generator.py # MCP tool definition generator
│   │   └── api/
│   │       ├── endpoints.py     # REST routes
│   │       └── websocket.py     # Real-time execution streaming
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── dashboard/           # Dashboard pages
│   │   ├── components/          # Shared React components
│   │   └── lib/api.ts          # Typed API client
│   ├── package.json
│   └── tailwind.config.js
└── README.md
```

## Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ | Project scaffolding & configuration |
| 2 | 🔲 | Database schema & Alembic migrations |
| 3 | 🔲 | Observer & mapper core (Playwright + Claude Vision) |
| 4 | 🔲 | API layer & WebSocket real-time logs |
| 5 | 🔲 | Frontend dashboard |
| 6 | 🔲 | Hardening, tests & deployment |

## License

Private — not yet licensed for public use.
