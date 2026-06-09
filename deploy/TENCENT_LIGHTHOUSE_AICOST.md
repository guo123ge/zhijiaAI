# aicost 腾讯云轻量服务器部署说明

适用环境：
- 公网 IP：124.221.103.75
- 系统：OpenCloudOS 9
- 当前主站：Nginx + PM2 + Next.js
- 域名：guo123guo.cn / www.guo123guo.cn，未备案前不作为正式业务入口

## 0. 不挤占其他项目

服务器上已有项目正在运行，aicost 必须旁路并入：
- 不占用现有 Next.js 端口 `3000`、`3001`
- 不占用已有后端端口 `8000`
- aicost 后端默认使用 `127.0.0.1:8001`
- aicost 前端只挂载到 `/aicost/`
- aicost API 只挂载到 `/api/aicost/`
- Nginx 只给 IP server block 增加 location，不接管 `/`

如果 `8001` 被其他非 aicost 服务占用，安装脚本会拒绝部署。可用 `BACKEND_PORT=8011` 明确指定其他空闲端口，并同步修改 Nginx 代理端口。

## 1. 本地构建

前端生产 API 默认走相对路径 `/api/aicost`，Vite base 已配置为 `/aicost/`。

```bash
cd frontend
npm ci
npm run build
```

后端部署到服务器后使用 SQLite。

## 2. 上传发布包

推荐上传 `release/aicost-release.zip` 到服务器：

```bash
scp release/aicost-release.zip root@124.221.103.75:/tmp/aicost-release.zip
```

服务器解压：

```bash
rm -rf /tmp/aicost-release
mkdir -p /tmp/aicost-release
unzip -o /tmp/aicost-release.zip -d /tmp/aicost-release
cd /tmp/aicost-release
```

## 3. 安装 aicost 后端和前端

生产环境必须设置强随机 `JWT_SECRET_KEY`：

```bash
export JWT_SECRET_KEY="$(openssl rand -hex 32)"
export PUBLIC_ORIGIN="http://124.221.103.75"
export BACKEND_PORT="8001"
bash deploy/install_aicost_server.sh
```

安装后 PM2 应出现 `aicost-api`，监听 `127.0.0.1:8001`。

## 4. Nginx 接入

把 `deploy/nginx.aicost-ip.conf` 中的 location 片段加入当前 IP 访问的 server block。

不要替换现有 `location /`，不要影响现有 Next.js 服务。

重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 5. 验证

```bash
curl http://127.0.0.1:8001/healthz
curl http://124.221.103.75/api/aicost/healthz
```

浏览器访问：

```text
http://124.221.103.75/aicost/
```

未激活访问业务 API 应返回 `401`，例如：

```bash
curl -i http://124.221.103.75/api/aicost/api/projects
```

## 6. SQLite 备份

```bash
chmod +x /opt/aicost/deploy/backup_sqlite.sh
/opt/aicost/deploy/backup_sqlite.sh
```

每日备份 crontab：

```cron
15 3 * * * /opt/aicost/deploy/backup_sqlite.sh >> /opt/aicost/backups/backup.log 2>&1
```

## 7. 备案完成后

备案完成后再启用域名正式入口：
- 部署 SSL 证书
- 80 跳转 443
- `CORS_ALLOW_ORIGINS` 改为 `https://www.guo123guo.cn,https://guo123guo.cn`
- 内测入口切换为 `https://www.guo123guo.cn/aicost/`
