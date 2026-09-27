import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { apiJson, api } from '../api'

export default function Dashboard() {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [user, setUser] = useState(null)
  const [input, setInput] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    apiJson('/api/auth/me').then(setUser).catch(() => {})
    apiJson('/api/projects').then(p => { setProjects(p); setLoading(false) }).catch(() => setLoading(false))
  }, [])

  async function startChat(e) {
    e?.preventDefault()
    const content = input.trim()
    if (!content || creating) return
    setCreating(true)
    try {
      const p = await apiJson('/api/projects', { method: 'POST', body: JSON.stringify({ name: content.slice(0, 30) || '新项目' }) })
      navigate(`/project/${p.id}?msg=${encodeURIComponent(content)}`)
    } catch (e) {
      alert('创建失败：' + e.message)
    } finally {
      setCreating(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      startChat()
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

      {/* Hero chat input — natural project creation */}
      <div className="dash-hero">
        <h1 className="hero-title">用一句话，搭建你的网站</h1>
        <p className="hero-sub">描述你想要的网站，Atom 会自动创建项目并为你生成。</p>
        <form className="dash-chat-form" onSubmit={startChat}>
          <textarea
            className="input dash-chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="例如：做个个人主页，我叫 Alice，喜欢摄影和旅行…"
            disabled={creating}
            rows={2}
          />
          <button className="btn dash-chat-btn" disabled={creating || !input.trim()}>
            {creating ? <><div className="spinner" /> 创建中…</> : '生成 →'}
          </button>
        </form>
      </div>

      <div className="dash-header">
        <h2>我的项目</h2>
      </div>

      {loading ? (
        <p style={{ color: 'var(--text-muted)' }}>加载中…</p>
      ) : projects.length === 0 ? (
        <div className="card empty-state">
          <h3>还没有项目</h3>
          <p>在上方输入框描述你的网站需求，即可开始创建</p>
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
