# syntax=docker/dockerfile:1
# Static site for okf-notebooks.kazakov.dev. Build context: this directory (site/).

FROM ghcr.io/gohugoio/hugo:v0.167.0 AS build
ARG BASE_URL=https://okf-notebooks.kazakov.dev/
COPY --chown=hugo:hugo . /project
RUN hugo build --gc --minify --panicOnWarning --baseURL "${BASE_URL}" --destination /project/public

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /project/public /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
