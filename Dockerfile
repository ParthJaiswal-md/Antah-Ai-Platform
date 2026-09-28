# AntahAI web app (System 3 + Learning Pathways) - production image.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ANTAHAI_DB=/data/antahai.db PORT=8080
WORKDIR /srv
COPY ["System-3 Complete_Linker/requirements-web.txt", "/tmp/requirements-web.txt"]
RUN pip install --no-cache-dir -r /tmp/requirements-web.txt
# Only what the web app needs: System 3 code + the Round-1 datasets it reads.
COPY ["System-3 Complete_Linker/", "/srv/System-3 Complete_Linker/"]
COPY ["System-1 Recommandation_Engine/datasets/", "/srv/System-1 Recommandation_Engine/datasets/"]
RUN mkdir -p /data && rm -f "/srv/System-3 Complete_Linker/antahai.db"
WORKDIR "/srv/System-3 Complete_Linker"
EXPOSE 8080
# One worker: SQLite on a single persistent disk. Threads handle concurrency.
CMD gunicorn wsgi:app --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 60 --access-logfile -
