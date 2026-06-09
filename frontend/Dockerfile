# 第一阶段：构建应用
FROM node:20-alpine AS builder

WORKDIR /app

# 复制 package files
COPY package*.json ./

# 安装依赖
RUN npm ci

# 复制源代码
COPY . .

# 构建应用
RUN npm run build

# 第二阶段：运行应用
FROM nginx:alpine

# 复制构建结果到 nginx
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置（处理 SPA 路由）
RUN cat > /etc/nginx/conf.d/default.conf <<EOF
server {
    listen 80;
    server_name _;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend:8000/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
