FROM node:24-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# INF-03 can COPY --from=build /app/dist into the shared HTTPS proxy.
FROM nginx:1.28-alpine AS preview
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
