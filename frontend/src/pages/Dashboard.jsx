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
    loadProjects()
  }, [])

  async function loadProjects() {
    setLoading(true)
    try {
      const data = await apiJson('/api/projects')
      setProjects(data)
    } catch (e) {} finally { setLoading(false) }
  }

  async function newProject() {
    setCreating(true)
    try {
      const p = await apiJson('/api/projects', {
        method: 'POST',
        body: JSON.stringify({ name: '新项目' }),
      })
      navigate(`/p/${p.id}`)
    } finally { setCreating(false) }
  }

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' })
    navigate('/login', { replace: true })
  }

  return (
    <div className="container">
      <nav className="nav">
        <div className="brand">Atom<span>.</span></div>
        <div className="nav-right">
          {user && <span style={{ fontSize: 13, color: 'var(--muted)' }}>{user.email}</span>}
          <Link to="/settings" className="btn ghost" style={{ padding: '6px 12px', fontSize: 13 }}>设置</Link>
          <button className="btn ghost" style={{ padding: '6px 12px', fontSize: 13 }} onClick={logout}>登出</button>
        </div>
      </nav>

      <div className="dash-header">
        <h2>我的项目</h2>
        <button className="btn" onClick={newProject} disabled={creating}>
          {creating ? '创建中…' : '+ 新建项目'}
        </button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}><div className="spinner" /></div>
      ) : projects.length === 0 ? (
        <div className="card empty-state">
          <h3>告知 atoms 团队你的需求</h3>
          <p>用一句话描述你想要的网站，AI 会为你生成并发布到公网。</p>
          <button className="btn" onClick={newProject} disabled={creating}>
            {creating ? '创建中…' : '开始创建'}
          </button>
        </div>
      ) : (
        <div className="project-grid">
          {projects.map(p => (
            <div key={p.id} className="card project-card" onClick={() => navigate(`/p/${p.id}`)}>
              <div className="pname">{p.name || '未命名项目'}</div>
              <div className="pmeta">
                <span className={`pstatus ${p.status === 'BUILDING' ? 'building' : ''}`}>{p.status}</span>
                {p.public_url && <span>已发布</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
