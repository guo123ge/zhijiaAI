# 智价 AI 激活码生成与 404 修复指南

---

## 一、404 错误修复（已完成）

### 问题原因

激活码输入后提示 `404 Not Found`，根源在 **nginx 反向代理配置错误**：

| 配置项 | 错误值 | 正确值 | 说明 |
|--------|--------|--------|------|
| `proxy_pass` 端口 | `8001` | `8000` | 后端 uvicorn 监听 8000，nginx 却转发到 8001 |
| `proxy_pass` 路径 | `/` | `/api/` | 剥离 `/api/aicost/` 后丢了 `/api/` 前缀，后端路由 `POST /api/auth/trial/activate` 匹配不上 |

### 修复内容

**文件**：`aicost/deploy/nginx.aicost-ip.conf`

```nginx
# 修改前（第 15 行）
    proxy_pass http://127.0.0.1:8001/;

# 修改后
    proxy_pass http://127.0.0.1:8000/api/;
```

**请求路径流转（修复后）**：
```
浏览器: POST /api/aicost/auth/trial/activate
   ↓ nginx location /api/aicost/ 匹配，proxy_pass 带 /api/
nginx:   POST http://127.0.0.1:8000/api/auth/trial/activate
   ↓ FastAPI router prefix="/api" + route "/auth/trial/activate"
FastAPI: 200 OK ✅
```

### 服务器生效

在 `124.221.103.75` 上更新配置后执行：
```bash
nginx -t && nginx -s reload
```

---

## 二、激活码生成步骤

### 前置条件

1. 后端服务需在运行状态
2. 数据库 `valuation.db` 中包含 `activation_codes` 表（启动后端时自动建表）
3. Python 虚拟环境已创建（`aicost/backend/venv`）

### 操作步骤

#### 1. 打开新终端

在 Windsurf / VS Code 中打开新的终端窗口。

#### 2. 切换到后端目录并激活虚拟环境

```powershell
Set-Location "d:\赛博土木AI课程\清单组价全过程代码\aicost\backend"
.\venv\Scripts\Activate.ps1
```

成功后会看到终端提示符前面出现 `(venv)` 标记。

#### 3. 执行生成命令

```powershell
# 生成 7 天激活码 × 1 个
python scripts/generate_activation_codes.py --days 7 --count 1 --note "2026年6月发放"

# 生成 14 天激活码 × 1 个
python scripts/generate_activation_codes.py --days 14 --count 1 --note "VIP用户"
```

#### 4. 获取激活码

脚本输出即为激活码，格式如 `AICOST-7D-XXXX-XXXX-XXXX`，直接复制给用户即可。

**示例输出**：
```
AICOST-7D-6B84-F549-1D74
```

---

## 三、参数说明

| 参数 | 必填 | 可选值 | 说明 |
|------|------|--------|------|
| `--days` | ✅ 必填 | `7` 或 `14` | 试用天数 |
| `--count` | 选填 | 任意整数，默认 `1` | 生成数量 |
| `--note` | 选填 | 任意文字 | 备注，方便后期管理 |

---

## 四、批量生成示例

```powershell
# 7天 × 10个
python scripts/generate_activation_codes.py --days 7 --count 10 --note "7天试用-6月批次"

# 14天 × 5个
python scripts/generate_activation_codes.py --days 14 --count 5 --note "14天VIP-6月批次"
```

---

## 五、验证激活码是否可用

### 直接调用后端 API

```powershell
# 使用 Python（需安装 requests）
python -c "import requests; r=requests.post('http://127.0.0.1:8000/api/auth/trial/activate', json={'code':'AICOST-7D-XXXX-XXXX-XXXX','requested_days':7}); print(r.status_code, r.json())"
```

成功返回 `200` 并包含 `access_token`、`trial` 信息。

### 通过前端激活

访问 http://localhost:5174/aicost/ 或 http://124.221.103.75/aicost/，在首页输入激活码并选择对应天数即可。

---

## 六、注意事项

- 每个激活码 **一次性使用**，激活后立即标记为已用，不可重复
- 用户激活时需选择与生成时一致的试用天数（7 或 14），否则会提示错误
- 生成的激活码会自动写入 `valuation.db` 数据库，数据持久保存
- 激活码格式：`AICOST-{days}D-{8位随机码}`
  - 例如 `AICOST-7D-6B84-F549-1D74` 表示 7 天试用

---

## 七、本地开发环境

| 服务 | 地址 | 说明 |
|------|------|------|
| 后端 API | http://127.0.0.1:8000 | FastAPI / uvicorn |
| 前端预览 | http://localhost:5174/aicost/ | Vite dev server |
| API 文档 | http://127.0.0.1:8000/docs | Swagger UI |

### 启动命令

```powershell
# 终端 1：启动后端
Set-Location "d:\赛博土木AI课程\清单组价全过程代码\aicost\backend"
.\venv\Scripts\Activate.ps1
python start_server.py

# 终端 2：启动前端
Set-Location "d:\赛博土木AI课程\清单组价全过程代码\aicost\frontend"
npm run dev
```

### Vite 代理配置

开发环境前端请求 `/api/aicost/*` 会自动代理到 `http://127.0.0.1:8000/api/*`，无需 nginx。

配置文件：`aicost/frontend/vite.config.ts`

```typescript
server: {
  proxy: {
    '/api/aicost': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api\/aicost/, '/api'),
    },
  },
},
```

---

## 八、相关文件索引

| 文件 | 用途 |
|------|------|
| `aicost/deploy/nginx.aicost-ip.conf` | Nginx 反向代理配置（已修复） |
| `aicost/deploy/pm2.aicost.config.cjs` | 生产环境 PM2 进程管理配置 |
| `aicost/backend/start_server.py` | 本地开发后端启动脚本 |
| `aicost/backend/scripts/generate_activation_codes.py` | 激活码生成脚本 |
| `aicost/backend/app/services/activation_service.py` | 激活码验证逻辑 |
| `aicost/backend/app/api/routes/auth.py` | 认证 API 路由 |
| `aicost/backend/app/main.py` | FastAPI 应用入口与路由注册 |
| `aicost/frontend/src/api.ts` | 前端 API 封装（API_BASE） |
| `aicost/frontend/src/auth.ts` | 前端认证状态管理 |
| `aicost/frontend/vite.config.ts` | Vite 配置（含 API 代理） |
| `aicost/智价AI激活码生产程序.md` | 激活码程序使用说明 |