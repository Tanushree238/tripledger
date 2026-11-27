ARG REGISTRY=
FROM ${REGISTRY}node:22-alpine
WORKDIR /app
COPY package*.json ./
ARG NPM_CONFIG_REGISTRY
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm","run","dev","--","--host","0.0.0.0"]
