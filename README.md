# Atom — 对话式建站 Agent (v0.4)

用一句话描述需求，AI 生成并发布一个公网可访问的网站。
**换设备、无痕窗口、清空 Cookie/localStorage 后，只要用邮箱密码重新登录，全部项目和对话都能找回。**

## 技术栈

- 前端：React + Vite（`frontend/`）
- 后端：Python + FastAPI（`backend/`）
- 数据库：SQLite（SQLAlchemy ORM，模型对齐 Postgres 结构）
- 密码：argon2id
- 会话：服务端 Session 表 + HttpOnly Cookie（**不使用 JWT**）

## 核心设计原则（对应 Spec 三条铁律）

1. **客户端状态丢了不能导致数据丢失** — 项目、对话、文件快照全部存在服务端，前端只存 UI 偏好。
2. **沙箱是易失的，快照是持久的** — 生成的网站以 FileSnapshot（tar.gz）持久化，可随时重建。
3. **不用 JWT** — Session 表 + 持久 Cookie，支持服务端撤销（改密踢下线、登出）。

## 本地启动

```bash
# 后端
cd backend
pip install -r requirements.txt
ATOM_COOKIE_SECURE=0 python3 main.py          # http://localhost:8000

# 前端（开发模式，代理到 8000）
cd frontend
npm install
npm run dev                                    # http://localhost:5173

# 生产构建（后端会自动 serve frontend/dist）
cd frontend && npm run build
cd ../backend && python3 main.py
```

## 部署到 Vercel（前端静态 + 后端 Serverless）

### 架构

- **前端**：React/Vite 构建为静态文件，由 Vercel CDN 全球分发
- **后端**：FastAPI 作为 Vercel Serverless Function（`api/index.py`，Python 运行时）
- **数据库**：Vercel Postgres（替代本地 SQLite）
- **文件存储**：Vercel Blob（替代本地文件系统）

### 前置准备

1. 在 Vercel 创建项目，导入本仓库
2. 创建 **Vercel Postgres** 数据库（Storage → Create Database → Postgres）
3. 创建 **Vercel Blob** 存储（Storage → Create Blob Store）

### 环境变量

在 Vercel 项目 Settings → Environment Variables 中配置：

| 变量 | 说明 | 示例 |
|-|-|-|
| `DATABASE_URL` | Vercel Postgres 连接串 | `postgresql://...` |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob 读写 Token | `vercel_blob_...` |
| `ATOM_COOKIE_SECURE` | Cookie Secure 标志，Vercel 为 HTTPS 设 `1` | `1` |
| `OPENAI_API_KEY` | （可选）LLM API Key，不配则用模板生成 | `sk-...` |

> Vercel Postgres 创建后会自动注入 `POSTGRES_URL` 等变量，代码也会读取 `POSTGRES_URL` 作为 `DATABASE_URL` 的备选。

### 部署

1. 推送代码到 GitHub
2. Vercel 自动检测到 `vercel.json` 并开始构建
3. 构建命令：`cd frontend && npm install && npm run build && cp -r dist ../public`
4. 部署完成后，访问 Vercel 分配的域名即可

### 路由规则（vercel.json）

```
/api/*    → Serverless 函数（FastAPI）
/sites/*  → Serverless 函数（发布的静态站点）
/*        → 静态前端（index.html，SPA 路由）
```

### 注意事项

- Serverless 函数最大执行时间 60s，模板生成器约 1s 完成，LLM 生成可能超时
- Postgres 表结构由 `init_db()` 自动创建（首次调用时）
- 生成的网站以 tar.gz 存入 Blob，访问时动态解压返回

## 环境变量

| 变量 | 默认 | 说明 |
|-|-|-|
| `DATABASE_URL` | 空 | Postgres 连接串（Vercel 部署必填，不配则用本地 SQLite） |
| `POSTGRES_URL` | 空 | Vercel Postgres 自动注入的连接串（DATABASE_URL 的备选） |
| `BLOB_READ_WRITE_TOKEN` | 空 | Vercel Blob Token（不配则用本地文件存储） |
| `ATOM_DB_PATH` | `backend/atom.db` | SQLite 数据库路径（仅本地开发） |
| `ATOM_STORAGE_ROOT` | `backend/storage` | 快照与站点存储目录（仅本地开发） |
| `ATOM_COOKIE_SECURE` | `1` | Cookie Secure 标志（HTTPS 部署用 1，本地 HTTP 用 0） |
| `ATOM_PUBLIC_URL` | 空 | 已发布站点的公开 URL 前缀，留空则用相对路径 |
| `OPENAI_API_KEY` | 空 | 配置后 AI 用 LLM 生成；否则用模板生成器 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM 模型 |

## 数据模型（Prisma schema 对齐）

`User` · `Session` · `Project` · `Message` · `FileSnapshot` · `Deployment` · `UsageQuota`

所有模型定义在 [backend/database.py](backend/database.py)。

## API

| 方法 | 路径 | 说明 |
|-|-|-|
| POST | `/api/auth/register` | 注册 + 建会话 |
| POST | `/api/auth/login` | 登录 + 建会话（支持 remember） |
| POST | `/api/auth/logout` | 撤销当前会话 |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/auth/change-password` | 改密 + 撤销其他会话 |
| GET | `/api/projects` | 项目列表（每次进工作台都拉） |
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects/:id` | 详情 |
| DELETE | `/api/projects/:id` | 删除（级联） |
| POST | `/api/projects/:id/messages` | 发消息（SSE，生成并发布网站） |
| GET | `/api/projects/:id/messages` | 历史消息（分页） |
| GET | `/api/projects/:id/files` | 文件树 |
| GET | `/api/projects/:id/snapshots` | 快照列表 |
| POST | `/api/projects/:id/redeploy` | 从最新快照重新发布 |
| GET | `/sites/:slug/*` | **已发布站点公开访问**（无需登录） |

所有 `/api/projects/*` 端点校验 `project.userId === req.user.id`，不符返回 404。

## "无痕恢复"手测步骤

1. 注册账号 → 新建项目 → 发一句话 → 拿到公网 URL。
2. 关闭浏览器 / 开无痕窗口 → 打开站点 → 跳登录。
3. 用同一邮箱密码登录 → **工作台列出全部项目**，含对话历史与已发布 URL。
4. 进入项目 → 对话历史、文件、预览 URL 全部就绪。
5. F5 硬刷新 → 一切仍在（业务状态在服务端，不在 localStorage）。

## 目录结构

```
backend/
  main.py            # FastAPI 入口（API + 静态站点 + SPA）
  database.py        # SQLAlchemy 模型
  auth.py            # 密码哈希、会话、AuthGuard
  auth_routes.py     # 注册/登录/登出/me/改密
  project_routes.py  # 项目 CRUD + 消息 SSE + 快照 + 部署
  agent.py           # AI 网站生成（LLM 或模板）
  storage.py         # 文件存储（快照 tar.gz + 静态站点）
frontend/
  src/
    pages/           # Login / Register / Dashboard / Project / Settings
    api.js           # API 客户端 + 401 跳转 /login
    App.jsx          # 路由 + PrivateRoute
```
