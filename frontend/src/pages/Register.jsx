import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { apiJson } from '../api'

export default function Register() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function submit(e) {
    e.preventDefault()
    setError('')
    if (password !== confirm) { setError('两次输入的密码不一致'); return }
    if (password.length < 8) { setError('密码至少 8 位'); return }
    setLoading(true)
    try {
      await apiJson('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(err.message || '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-wrap">
      <div className="card auth-card">
        <h1 className="gradient-text">创建账号</h1>
        <p className="sub">注册后即可开始用对话搭建网站</p>
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
          <div className="field">
            <label className="label">确认密码</label>
            <input className="input" type="password" value={confirm} onChange={e => setConfirm(e.target.value)} required />
          </div>
          <button className="btn" disabled={loading}>{loading ? '注册中…' : '注册并登录'}</button>
        </form>
        <div className="switch">已有账号？<Link to="/login">登录</Link></div>
      </div>
    </div>
  )
}
