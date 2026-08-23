FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir '.[migrations]'

# Migrations ship in the image so the release step runs the exact code being deployed.
COPY alembic.ini ./
COPY alembic ./alembic
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh && useradd --create-home --uid 10001 hypersale
USER hypersale

EXPOSE 8000
ENV PROCESS_ROLE=api
ENTRYPOINT ["./entrypoint.sh"]
