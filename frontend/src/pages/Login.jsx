import { useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { apiJson } from '../api'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const [params] = useSearchParams()

  async function submit(e) {
    e.preventDefault()
    setError(''); setLoading(true)
    try {
      await apiJson('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password, remember }),
      })
      const redirect = params.get('redirect') || '/dashboard'
      navigate(redirect, { replace: true })
    } catch (err) {
      setError(err.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-wrap">
      <div className="card auth-card">
        <div className="brand-row">
          <div className="brand-logo">A</div>
          <span style={{ fontWeight: 800, fontSize: 22, letterSpacing: '-0.03em' }}>Atom</span>
        </div>
        <h1>欢迎回来</h1>
        <p className="sub">对话式建站，用一句话生成你的网站</p>
        {error && <div className="error">{error}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label className="label">邮箱</label>
            <input className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required />
          </div>
          <div className="field">
            <label className="label">密码</label>
            <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="至少 8 位" required />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
            <input id="rm" type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
            <label htmlFor="rm" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>记住我（30 天）</label>
          </div>
          <button className="btn" disabled={loading}>{loading ? '登录中…' : '登录'}</button>
        </form>
        <div className="switch">没有账号？<Link to="/register">注册</Link></div>
      </div>
    </div>
  )
}
