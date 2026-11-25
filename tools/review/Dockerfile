# Film Lab review web app (tools/review/README.md). Standard-library Python only: no pip, no npm, no CDN.
# Build context: tools/review/ (docker compose -f tools/review/docker-compose.yml up -d --build).
# web/vendor/three/ must be filled first: python tools/review/vendor_three.py --from <three package dir>.
FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# A fixed non-root user; /data is the named volume that holds the SQLite database (owned by that user).
RUN addgroup -S -g 10001 review \
 && adduser -S -D -H -u 10001 -G review review \
 && mkdir -p /data /media /app \
 && chown review:review /data

WORKDIR /app
COPY --chown=root:root server.py /app/server.py
COPY --chown=root:root web /app/web

USER review
EXPOSE 8790 8791
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import json,urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8790/api/health', timeout=3); sys.exit(0 if json.load(r).get('ok') else 1)"]

CMD ["python", "/app/server.py", "--db", "/data/review.db", "--media", "/media", "--web", "/app/web", "--quiet"]
