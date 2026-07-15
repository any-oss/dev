FROM node:18-alpine AS dev-base
WORKDIR /workspace
RUN apk add --no-cache git openssh-client docker-cli dumb-init && \
    npm install -g npm@latest
RUN addgroup -g 1000 node && \
    adduser -u 1000 -G node -s /bin/sh -D node && \
    chown -R node:node /workspace
USER node
COPY --chown=node:node package*.json ./
RUN npm ci --include=dev
FROM dev-base AS development
ENV NODE_ENV=development
COPY --chown=node:node . .
EXPOSE 3000
ENTRYPOINT ["dumb-init", "--"]
CMD ["npm", "start"]
FROM dev-base AS production
ENV NODE_ENV=production
RUN npm ci --omit=dev && npm cache clean --force
COPY --chown=node:node . .
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/health', (r) => process.exit(r.statusCode === 200 ? 0 : 1))" || exit 1
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "src/index.js"]
