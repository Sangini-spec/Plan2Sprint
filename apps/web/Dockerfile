# ============================================================================
# Plan2Sprint Next.js Frontend — Dockerfile
# Multi-stage build: deps → build → runtime (standalone output)
# ============================================================================

# ── Stage 1: Install dependencies ──
FROM node:20-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# ── Stage 2: Build ──
FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time env vars
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG API_URL=http://localhost:8000

ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY
ENV API_URL=$API_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ── Stage 3: Production runtime ──
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy standalone output (Next.js output: 'standalone')
# outputFileTracingRoot causes nested path — copy the inner app dir
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone/app ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
