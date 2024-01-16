FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

# Code stays root-owned, so the app user can run it but not change it.
COPY manage.py ./
COPY fitness_tracker ./fitness_tracker
COPY accounts ./accounts

USER app
EXPOSE 8000
CMD ["gunicorn", "fitness_tracker.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", \
     "--worker-tmp-dir", "/dev/shm", "--no-control-socket", "--access-logfile", "-"]
