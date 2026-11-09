# MRK-101: frontend image for the Ubuntu production host (built by frontend/compose.yaml, see docs/operations.md).
# NEXT_PUBLIC_API_URL is baked into the browser bundle at build time - changing it needs a rebuild.
FROM node:24-bookworm-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
# fail the build instead of shipping a bundle without an API origin
RUN test -n "$NEXT_PUBLIC_API_URL" || { echo "NEXT_PUBLIC_API_URL is empty (frontend/.env.production.local)"; exit 1; }

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start", "--", "-H", "0.0.0.0"]
