FROM node:22-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . ./

ARG LEXORA_API_URL=http://api:8011
ENV LEXORA_API_URL=$LEXORA_API_URL

RUN mkdir -p public \
    && npm run build

FROM node:22-alpine AS runner

WORKDIR /app

RUN addgroup -S -g 1001 lexora \
    && adduser -S -D -H -u 1001 -G lexora lexora

ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    PORT=3000

COPY --chown=lexora:lexora --from=builder /app/.next/standalone ./
COPY --chown=lexora:lexora --from=builder /app/.next/static ./.next/static
COPY --chown=lexora:lexora --from=builder /app/public ./public

USER lexora

EXPOSE 3000

CMD ["node", "server.js"]
