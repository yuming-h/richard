dependencies:

poppler

```
uv run uvicorn app.main:app --reload

# migrations
uv run alembic revision --autogenerate -m ""
uv run alembic upgrade head
```

tmux attach -t richard-api-session
RICHARD_ENV="production" uv run uvicorn app.main:app --reload --workers 4

postgresql-devel
