FROM node:24-alpine AS build
RUN npm install -g pnpm@11.25.0
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
COPY contracts/generated/api.d.ts /app/contracts/generated/api.d.ts
# 页面请求由反向代理转给 Go；此值只用于内部 SSR 取数和开发 rewrite。
ARG API_ORIGIN=http://api:8080
ARG SITE_URL=http://localhost:3000
ENV API_ORIGIN=$API_ORIGIN
ENV SITE_URL=$SITE_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:24-alpine
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
WORKDIR /app
COPY --from=build --chown=node:node /app/frontend/.next/standalone ./
COPY --from=build --chown=node:node /app/frontend/.next/static ./.next/static
COPY --from=build --chown=node:node /app/frontend/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
