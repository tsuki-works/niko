# syntax=docker/dockerfile:1.7
# Multi-stage build for the niko dashboard (Next.js 16, App Router, RSC).
# Produces a self-contained server image via `output: "standalone"`.
#
# Build-time args (must be present at `next build` because Next.js inlines
# `NEXT_PUBLIC_*` into the client bundle):
#   - NEXT_PUBLIC_FIREBASE_API_KEY
#   - NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
#   - NEXT_PUBLIC_FIREBASE_PROJECT_ID
#   - NEXT_PUBLIC_FIREBASE_APP_ID
#
# Runtime env (passed by Cloud Run, not baked in):
#   - NIKO_API_BASE_URL — the FastAPI Cloud Run service URL
#   - PORT — Cloud Run sets this; Next.js standalone reads it

ARG NODE_VERSION=20-alpine

# ---------- deps ----------
FROM node:${NODE_VERSION} AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

# ---------- build ----------
FROM node:${NODE_VERSION} AS build
WORKDIR /app
RUN corepack enable

ARG NEXT_PUBLIC_FIREBASE_API_KEY
ARG NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
ARG NEXT_PUBLIC_FIREBASE_PROJECT_ID
ARG NEXT_PUBLIC_FIREBASE_APP_ID
ENV NEXT_PUBLIC_FIREBASE_API_KEY=${NEXT_PUBLIC_FIREBASE_API_KEY} \
    NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=${NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN} \
    NEXT_PUBLIC_FIREBASE_PROJECT_ID=${NEXT_PUBLIC_FIREBASE_PROJECT_ID} \
    NEXT_PUBLIC_FIREBASE_APP_ID=${NEXT_PUBLIC_FIREBASE_APP_ID} \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN pnpm run build

# ---------- runtime ----------
FROM node:${NODE_VERSION} AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0

RUN addgroup -S nextjs && adduser -S -G nextjs nextjs

COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nextjs /app/public ./public

USER nextjs
EXPOSE 8080

CMD ["node", "server.js"]
