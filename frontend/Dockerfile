# Homelab Dashboard — Frontend Dockerfile
# Multi-stage build: Node 20 → build static assets → serve via Caddy

FROM node:20-slim AS build

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci \
    --no-audit \
    --no-fund \
    --prefer-offline \
    --fetch-retries=5 \
    --fetch-retry-mintimeout=20000 \
    --fetch-retry-maxtimeout=120000

# Copy source and build
COPY . .
RUN npm run build

# Production: serve static files with Caddy
FROM caddy:2-alpine

COPY --from=build /app/dist /srv
COPY <<EOF /etc/caddy/Caddyfile
:3000 {
    root * /srv
    file_server
    try_files {path} /index.html
    encode gzip
}
EOF

EXPOSE 3000
