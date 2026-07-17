.PHONY: help install migrate migrate-dev makemigration run test lint

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies
	pip install -r requirements.txt
	playwright install chromium

migrate: ## Run all pending migrations (upgrade head)
	alembic upgrade head

migrate-dev: ## Run migrations using dev DATABASE_URL
	DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dynamic_bridge" alembic upgrade head

makemigration: ## Generate a new migration (autogenerate from models)
	alembic revision --autogenerate -m "$(msg)"

run: ## Start the dev server
	uvicorn app.main:app --reload --port 8001

test: ## Run all tests
	python -m pytest tests/ -v

lint: ## Run type checking
	python -m mypy app/ --ignore-missing-imports
