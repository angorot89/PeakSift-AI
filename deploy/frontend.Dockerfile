# syntax=docker/dockerfile:1.7
# PeakSift frontend: Next.js built as a self-contained server, built from frontend/.
#
#   docker build -f deploy/frontend.Dockerfile --build-arg NEXT_PUBLIC_API_URL=/api \
#     -t peaksift-frontend frontend
#
# NEXT_PUBLIC_API_URL is compiled into the browser bundle: "/api" when the reverse proxy
# serves the API under the same origin (deploy/nginx), or the API's https:// origin.

FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_API_URL=/api
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
# The image's unprivileged "node" user owns nothing but runs the server.
COPY --from=build /src/.next/standalone ./
COPY --from=build /src/.next/static ./.next/static
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
