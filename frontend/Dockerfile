# --- CompliWise Frontend (React/TS/Vite) ---

# Stage 1: build the static assets
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# Baked in at build time — must be the address staff browsers will actually
# use to reach the backend (e.g. the school server's LAN IP or hostname),
# NOT localhost, since Vite env vars are resolved at build time, not runtime.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# Stage 2: serve with Nginx
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]