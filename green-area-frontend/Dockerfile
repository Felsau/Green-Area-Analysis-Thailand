# ---- deps: cache npm install แยกจาก source เพื่อไม่ต้อง reinstall ทุกครั้งที่โค้ดเปลี่ยน ----
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- dev: ใช้กับ docker-compose local dev (vite dev server + hot reload) ----
FROM deps AS dev
WORKDIR /app
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---- build: compile production bundle ----
FROM deps AS build
WORKDIR /app
COPY . .
# Vite env เป็น build-time — ต้องส่งเข้ามาตอน build image เช่น
# docker build --build-arg VITE_API_URL=https://api.example.com
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- production: serve static bundle ด้วย nginx ----
FROM nginx:alpine AS production
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
