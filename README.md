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

## 环境变量

| 变量 | 默认 | 说明 |
|-|-|-|
| `ATOM_DB_PATH` | `backend/atom.db` | SQLite 数据库路径 |
| `ATOM_STORAGE_ROOT` | `backend/storage` | 快照与站点存储目录 |
| `ATOM_COOKIE_SECURE` | `1` | Cookie Secure 标志（HTTPS 部署用 1） |
| `ATOM_PUBLIC_URL` | `http://localhost:8000` | 已发布站点的公开 URL 前缀 |
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
