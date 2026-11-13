# SIMOLA web image: static SPA + /api reverse proxy, unprivileged nginx (PRD NFR-SEC-005).
FROM node:24.22.2-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# npm can skip an optional native package without failing (npm/cli#4828), and Docker would then cache the incomplete
# install. Loading rolldown's Alpine binding in the same step makes such an install fail here, uncached.
RUN npm ci --no-audit --no-fund && node -e "require('@rolldown/binding-linux-x64-musl')"
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine3.24
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
