# 构建目录来自 frontend.Dockerfile 的同等 Linux 构建；不复制 Windows 原生依赖。
FROM node:24-alpine
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
ENV NODE_OPTIONS=--max-old-space-size=192
WORKDIR /app
COPY --chown=node:node frontend/.next/standalone ./
USER node
EXPOSE 3000
CMD ["node", "server.js"]
