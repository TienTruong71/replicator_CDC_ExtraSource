FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc tzdata && \
    mkdir -p /etc/apt/keyrings && \
    curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /etc/apt/keyrings/microsoft.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17; \
    fi && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY replicator/pyproject.toml replicator/poetry.lock ./replicator/
RUN pip install poetry && \
    cd replicator && poetry install --no-root --only main

COPY setup.py auto_setup.py ./
COPY replicator/src ./replicator/src
COPY docker ./docker
RUN sed -i 's/\r$//' docker/entrypoint.sh

ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
CMD ["run"]
