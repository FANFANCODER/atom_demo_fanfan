import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams, Link } from 'react-router-dom'
import { apiJson, api } from '../api'

export default function Project() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [project, setProject] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [user, setUser] = useState(null)
  const [llmThinking, setLlmThinking] = useState('')
  const scrollRef = useRef(null)
  const abortRef = useRef(null)
  const initialSentRef = useRef(false)

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
      const initialMsg = searchParams.get('msg')
      if (initialMsg && !msgs.length && !initialSentRef.current) {
        initialSentRef.current = true
        setInput(initialMsg)
        setTimeout(() => sendWithContent(initialMsg), 300)
      }
    } catch (e) {}
  }

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages])

  // 存在"生成中"的占位消息（assistant 且 content 为空）时轮询恢复：
  // 页面刷新 / SSE 断开后，后台生成完成后自动补全对话与预览。
  const hasPendingAssistant = messages.some(m => m.role === 'assistant' && !m.content)
  useEffect(() => {
    if (!hasPendingAssistant) return
    let tries = 0
    const timer = setInterval(async () => {
      tries += 1
      try {
        const msgs = await apiJson(`/api/projects/${id}/messages`)
        setMessages(msgs)
        if (!msgs.some(m => m.role === 'assistant' && !m.content)) {
          const p = await apiJson(`/api/projects/${id}`).catch(() => null)
          if (p) setProject(p)
        }
      } catch (e) {}
      if (tries >= 45) clearInterval(timer) // ~3 分钟后停止轮询
    }, 4000)
    return () => clearInterval(timer)
  }, [hasPendingAssistant, id])

  async function send(e) {
    e?.preventDefault()
    const content = input.trim()
    if (!content || sending) return
    setInput('')
    await sendWithContent(content)
  }

  async function sendWithContent(content) {
    if (!content || sending) return
    setSending(true)
    setLlmThinking('')
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
            setMessages(m => [...m.filter(x => !x._status), { id: 'a' + Date.now(), role: 'assistant', content: data }])
          } else if (evt === 'llm_reasoning') {
            setLlmThinking(t => t + data)
          } else if (evt === 'llm_error') {
            setMessages(m => [...m, { id: 'le' + Date.now(), role: 'tool', content: '⚠️ ' + data, _llmerror: true }])
          } else if (evt === 'deployment') {
            const dep = JSON.parse(data)
            setProject(p => p ? { ...p, public_url: dep.url, status: dep.status } : p)
          } else if (evt === 'error') {
            setMessages(m => [...m.filter(x => !x._status), { id: 'e' + Date.now(), role: 'assistant', content: '生成失败：' + data }])
          }
        }
      }
      const msgs = await apiJson(`/api/projects/${id}/messages`)
      setMessages(msgs)
      setLlmThinking('')
    } catch (e) {
      if (e.name !== 'AbortError') {
        // SSE 断开：生成仍在后台执行（占位消息已入库），重拉消息接管显示
        try {
          const msgs = await apiJson(`/api/projects/${id}/messages`)
          setMessages(msgs)
        } catch (e2) {
          setMessages(m => [...m, { id: 'e' + Date.now(), role: 'assistant', content: '出错了：' + (e.message || '未知错误') }])
        }
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
          <Link to="/dashboard" className="btn ghost sm">← 工作台</Link>
          <button className="btn ghost sm" onClick={deleteProject}>删除项目</button>
          {user && <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{user.email}</span>}
        </div>
      </nav>

      <div className="project-layout" style={{ flex: 1, height: 'auto' }}>
        <div className="card chat-panel">
          <div className="chat-messages" ref={scrollRef}>
            {messages.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>
                描述你想要的网站，例如：「做个个人主页，我叫 Alice」
              </div>
            )}
            {messages.map(m => (
              <div key={m.id} className={`msg ${m.role}`}>
                {m.role === 'assistant' && !m.content
                  ? '⏳ 网站正在生成中… 可以离开或刷新页面，稍后回来查看结果。'
                  : m.content}
              </div>
            ))}
          </div>

          {llmThinking && (
            <div className="llm-stream" style={{
              margin: '0 12px 8px', padding: '10px 12px',
              background: 'rgba(79,70,229,0.06)', border: '1px solid rgba(79,70,229,0.15)',
              borderRadius: 12, fontSize: 12.5, maxHeight: 220, overflowY: 'auto',
            }}>
              <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 4 }}>
                🧠 模型思考过程
              </div>
              <pre style={{
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
                color: 'var(--text-muted)', fontFamily: 'inherit',
              }}>{llmThinking}</pre>
            </div>
          )}

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

        <div className="card preview-panel">
          <div className="preview-toolbar">
            <span className="badge">预览</span>
            {previewUrl ? (
              <a className="url" href={previewUrl} target="_blank" rel="noreferrer">{previewUrl}</a>
            ) : (
              <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>尚未发布</span>
            )}
            {previewUrl && (
              <a href={previewUrl} target="_blank" rel="noreferrer" className="btn ghost sm">新窗口打开</a>
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
