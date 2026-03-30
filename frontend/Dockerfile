# Build stage
ARG NODE_IMAGE=node:20-alpine
ARG NGINX_IMAGE=nginx:alpine

FROM ${NODE_IMAGE} AS build

WORKDIR /app

COPY frontend/package.json ./
RUN npm install

COPY frontend/ .
RUN npm run build

# Production stage
FROM ${NGINX_IMAGE}

COPY --from=build /app/build /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
