# syntax=docker/dockerfile:1
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
# vite.config.ts writes to ../src/okf_notebooks/webui_dist, i.e. /src/okf_notebooks/webui_dist
RUN npm run build

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY --from=web /src/okf_notebooks/webui_dist ./src/okf_notebooks/webui_dist
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
RUN mkdir /data /config && chown 10001:10001 /data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV HOME=/tmp OKF_NOTEBOOKS_CONFIG=/config/config.yaml
USER 10001
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s CMD ["okf-notebooks", "healthcheck"]
ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
CMD ["serve"]
