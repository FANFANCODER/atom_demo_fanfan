import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { apiJson, api } from '../api'

export default function Project() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [user, setUser] = useState(null)
  const scrollRef = useRef(null)
  const abortRef = useRef(null)

  useEffect(() => {
    apiJson('/api/auth/me').then(setUser).catch(() => {})
    load()
  }, [id])

  async function load() {
    try {
      const p = await apiJson(`/api/projects/${id}`)
      setProject(p)
      const msgs = await apiJson(`/api/projects/${id}/messages`)
      setMessages(msgs)
    } catch (e) {}
  }

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages])

  async function send(e) {
    e?.preventDefault()
    const content = input.trim()
    if (!content || sending) return
    setInput('')
    setSending(true)
    const userMsg = { id: Date.now(), role: 'user', content }
    setMessages(m => [...m, userMsg])

    try {
      const res = await api(`/api/projects/${id}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content }),
      })
      abortRef.current = res
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let assistantText = ''
      let lastStatus = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop()
        for (const block of lines) {
          const evtMatch = block.match(/^event:\s*(\S+)/m)
          const dataMatch = block.match(/^data:\s*(.*)$/m)
          if (!evtMatch || !dataMatch) continue
          const evt = evtMatch[1]
          const data = dataMatch[1]
          if (evt === 'status') {
            lastStatus = data
            setMessages(m => {
              const copy = [...m]
              const last = copy[copy.length - 1]
              if (last && last.role === 'tool' && last._status) {
                copy[copy.length - 1] = { ...last, content: data }
              } else {
                copy.push({ id: 's' + Date.now(), role: 'tool', content: data, _status: true })
              }
              return copy
            })
          } else if (evt === 'assistant') {
            assistantText = data
            setMessages(m => [...m.filter(x => !x._status), { id: 'a' + Date.now(), role: 'assistant', content: data }])
          } else if (evt === 'deployment') {
            const dep = JSON.parse(data)
            setProject(p => p ? { ...p, public_url: dep.url, status: dep.status } : p)
          }
        }
      }
      // refresh to get persisted messages
      const msgs = await apiJson(`/api/projects/${id}/messages`)
      setMessages(msgs)
    } catch (e) {
      if (e.name !== 'AbortError') {
        setMessages(m => [...m, { id: 'e' + Date.now(), role: 'assistant', content: '出错了：' + (e.message || '未知错误') }])
      }
    } finally {
      setSending(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  async function deleteProject() {
    if (!confirm('确定删除该项目？此操作不可撤销。')) return
    await api(`/api/projects/${id}`, { method: 'DELETE' })
    navigate('/dashboard')
  }

  const rawUrl = project?.public_url
  const previewUrl = rawUrl
    ? (rawUrl.startsWith('http') ? rawUrl : `${window.location.origin}${rawUrl}`)
    : null

  return (
    <div className="container" style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <nav className="nav">
        <div className="brand" style={{ cursor: 'pointer' }} onClick={() => navigate('/dashboard')}>Atom<span>.</span></div>
        <div className="nav-right">
          <button className="btn ghost" style={{ padding: '6px 12px', fontSize: 13 }} onClick={deleteProject}>删除项目</button>
          {user && <span style={{ fontSize: 13, color: 'var(--muted)' }}>{user.email}</span>}
        </div>
      </nav>

      <div className="project-layout" style={{ flex: 1, height: 'auto' }}>
        {/* Chat panel */}
        <div className="card chat-panel">
          <div className="chat-messages" ref={scrollRef}>
            {messages.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 40 }}>
                描述你想要的网站，例如：「做个个人主页，我叫 Alice」
              </div>
            )}
            {messages.map(m => (
              <div key={m.id} className={`msg ${m.role}`}>{m.content}</div>
            ))}
          </div>
          <form className="chat-input" onSubmit={send}>
            <textarea
              className="input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="描述你的网站需求… (Enter 发送)"
              disabled={sending}
            />
            <button className="btn" disabled={sending || !input.trim()} style={{ alignSelf: 'flex-end' }}>
              {sending ? <div className="spinner" /> : '发送'}
            </button>
          </form>
        </div>

        {/* Preview panel */}
        <div className="card preview-panel">
          <div className="preview-toolbar">
            <span className="badge">预览</span>
            {previewUrl ? (
              <a className="url" href={previewUrl} target="_blank" rel="noreferrer">{previewUrl}</a>
            ) : (
              <span style={{ color: 'var(--muted)', fontSize: 12 }}>尚未发布</span>
            )}
            {previewUrl && (
              <a href={previewUrl} target="_blank" rel="noreferrer" className="btn ghost" style={{ padding: '4px 10px', fontSize: 12 }}>新窗口打开</a>
            )}
          </div>
          {previewUrl ? (
            <div className="preview-frame">
              <iframe src={previewUrl} title="preview" sandbox="allow-scripts allow-same-origin" />
            </div>
          ) : (
            <div className="preview-empty">
              <div style={{ fontSize: 40, opacity: 0.3 }}>🖥️</div>
              <div>发送消息后，生成的网站将在此预览</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
