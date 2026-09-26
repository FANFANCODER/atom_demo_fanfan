import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { apiJson } from './api'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Project from './pages/Project'
import Settings from './pages/Settings'

function PrivateRoute({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const loc = useLocation()

  useEffect(() => {
    let alive = true
    apiJson('/api/auth/me')
      .then((u) => alive && setUser(u))
      .catch(() => {
        const here = encodeURIComponent(loc.pathname + loc.search)
        location.href = `/login?redirect=${here}`
      })
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [loc.pathname])

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <div className="spinner" />
    </div>
  }
  if (!user) return null
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/dashboard" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
      <Route path="/p/:id" element={<PrivateRoute><Project /></PrivateRoute>} />
      <Route path="/settings" element={<PrivateRoute><Settings /></PrivateRoute>} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
