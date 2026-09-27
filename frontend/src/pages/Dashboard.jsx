import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { apiJson, api } from '../api'

export default function Dashboard() {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [user, setUser] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    apiJson('/api/auth/me').then(setUser).catch(() => {})
    apiJson('/api/projects').then(p => { setProjects(p); setLoading(false) }).catch(() => setLoading(false))
  }, [])

  async function createProject() {
    setCreating(true)
    try {
      const p = await apiJson('/api/projects', { method: 'POST' })
      navigate(`/project/${p.id}`)
    } catch (e) {
      alert('创建失败：' + e.message)
    } finally {
      setCreating(false)
    }
  }

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' })
    navigate('/login', { replace: true })
  }

  return (
    <div className="container">
      <nav className="nav">
        <div className="brand" onClick={() => navigate('/dashboard')} style={{ cursor: 'pointer' }}>
          Atom<span className="dot">.</span>
        </div>
        <div className="nav-right">
          {user && <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{user.email}</span>}
          <Link to="/settings" className="btn ghost sm">设置</Link>
          <button className="btn sm" onClick={logout}>退出</button>
        </div>
      </nav>

      <div className="dash-header">
        <h2>我的项目</h2>
        <button className="btn" onClick={createProject} disabled={creating}>
          {creating ? '创建中…' : '+ 新建项目'}
        </button>
      </div>

      {loading ? (
        <p style={{ color: 'var(--text-muted)' }}>加载中…</p>
      ) : projects.length === 0 ? (
        <div className="card empty-state">
          <h3>还没有项目</h3>
          <p>用一句话开始搭建你的第一个网站</p>
          <button className="btn lg" onClick={createProject} disabled={creating}>
            {creating ? '创建中…' : '创建第一个项目'}
          </button>
        </div>
      ) : (
        <div className="project-grid">
          {projects.map(p => (
            <div key={p.id} className="card project-card" onClick={() => navigate(`/project/${p.id}`)}>
              <div className="pname">{p.name || '未命名项目'}</div>
              <div className="pmeta">
                <span className={'pstatus' + (p.status === 'building' ? ' building' : '')}>
                  {p.status === 'building' ? '构建中' : p.status || '已就绪'}
                </span>
                <span>{new Date(p.updated_at).toLocaleDateString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
