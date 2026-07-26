# Frontend image: build the Vite bundle, then serve it from nginx.
#
# nginx also proxies /api/* to the api service, which keeps the browser origin
# and the backend origin identical — the same thing the Vite dev proxy does.
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
