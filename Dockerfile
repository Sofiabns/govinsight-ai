FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && python -m venv "$VIRTUAL_ENV"

COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install -r requirements.txt

USER app

EXPOSE 8000

CMD ["uvicorn", "govinsight.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
