import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { apiJson, api } from '../api'

export default function Settings() {
  const [user, setUser] = useState(null)
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const navigate = useNavigate()

  useEffect(() => { apiJson('/api/auth/me').then(setUser).catch(() => {}) }, [])

  async function changePw(e) {
    e.preventDefault()
    setMsg(''); setErr('')
    if (newPw.length < 8) { setErr('新密码至少 8 位'); return }
    try {
      await apiJson('/api/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      })
      setMsg('密码已修改，其他设备已下线。')
      setOldPw(''); setNewPw('')
    } catch (e) { setErr(e.message) }
  }

  async function logoutAll() {
    // logout current session; other sessions already revoked on pw change
    await api('/api/auth/logout', { method: 'POST' })
    navigate('/login', { replace: true })
  }

  async function deleteAccount() {
    if (!confirm('确定删除账号？所有项目和数据将被永久删除。')) return
    try {
      await api('/api/auth/me', { method: 'DELETE' })
    } catch {}
    await api('/api/auth/logout', { method: 'POST' })
    navigate('/login', { replace: true })
  }

  return (
    <div className="container">
      <nav className="nav">
        <div className="brand" style={{ cursor: 'pointer' }} onClick={() => navigate('/dashboard')}>Atom<span>.</span></div>
        <div className="nav-right">
          <Link to="/dashboard" className="btn ghost" style={{ padding: '6px 12px', fontSize: 13 }}>返回工作台</Link>
        </div>
      </nav>

      <h2 style={{ margin: '24px 0 16px' }}>设置</h2>

      <div className="card settings-section">
        <h3>账号信息</h3>
        {user && <p style={{ color: 'var(--muted)' }}>邮箱：{user.email} · 套餐：{user.plan}</p>}
      </div>

      <div className="card settings-section">
        <h3>修改密码</h3>
        {msg && <div style={{ color: 'var(--success)', marginBottom: 12, fontSize: 13 }}>{msg}</div>}
        {err && <div className="error">{err}</div>}
        <form onSubmit={changePw}>
          <div className="field">
            <label className="label">当前密码</label>
            <input className="input" type="password" value={oldPw} onChange={e => setOldPw(e.target.value)} required />
          </div>
          <div className="field">
            <label className="label">新密码（至少 8 位）</label>
            <input className="input" type="password" value={newPw} onChange={e => setNewPw(e.target.value)} required />
          </div>
          <button className="btn">修改密码</button>
        </form>
      </div>

      <div className="card settings-section">
        <h3>会话</h3>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 12 }}>
          修改密码会自动下线其他设备。也可以手动登出当前设备。
        </p>
        <button className="btn secondary" onClick={logoutAll}>登出当前设备</button>
      </div>

      <div className="card settings-section">
        <h3 style={{ color: 'var(--danger)' }}>危险操作</h3>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 12 }}>
          删除账号将永久清除你的所有项目、对话和数据。
        </p>
        <button className="btn danger" onClick={deleteAccount}>删除账号</button>
      </div>
    </div>
  )
}
