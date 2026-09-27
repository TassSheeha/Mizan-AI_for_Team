import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { ApiError } from '../lib/api'

export default function LoginPage() {
  const { user, loading, login, register } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Already authenticated (e.g. refresh after reload) → straight to the app
  if (!loading && user) return <Navigate to="/" replace />

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'login') {
        await login(email, password)
        navigate('/', { replace: true })
      } else {
        await register(email, username, password)
        navigate('/', { replace: true })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'تعذر الاتصال بالخادم. تأكد من تشغيل الخدمة.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-bl from-slate-100 via-teal-50 to-slate-100 p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-teal-700 text-3xl shadow-lg shadow-teal-700/20">
            ⚖️
          </div>
          <h1 className="text-2xl font-extrabold text-slate-900">الميزان</h1>
          <p className="mt-1 text-sm text-slate-500">المستشار القانوني الليبي الذكي</p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xl shadow-slate-200/60">
          <div className="mb-6 grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 text-sm font-semibold">
            <button
              type="button"
              onClick={() => { setMode('login'); setError('') }}
              className={`rounded-lg py-2 transition ${mode === 'login' ? 'bg-white text-teal-700 shadow' : 'text-slate-500'}`}
            >
              تسجيل الدخول
            </button>
            <button
              type="button"
              onClick={() => { setMode('register'); setError('') }}
              className={`rounded-lg py-2 transition ${mode === 'register' ? 'bg-white text-teal-700 shadow' : 'text-slate-500'}`}
            >
              حساب جديد
            </button>
          </div>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-semibold text-slate-700">البريد الإلكتروني</label>
              <input
                type="email" required dir="ltr" value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
              />
            </div>
            {mode === 'register' && (
              <div>
                <label className="mb-1 block text-sm font-semibold text-slate-700">اسم المستخدم</label>
                <input
                  type="text" required minLength={3} value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="اسمك الظاهر"
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
                />
              </div>
            )}
            <div>
              <label className="mb-1 block text-sm font-semibold text-slate-700">كلمة المرور</label>
              <input
                type="password" required minLength={6} dir="ltr" value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
              />
              {mode === 'register' && (
                <p className="mt-1 text-xs text-slate-400">8 أحرف على الأقل</p>
              )}
            </div>

            {error && (
              <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 border border-red-200">
                {error}
              </div>
            )}

            <button
              type="submit" disabled={busy}
              className="w-full rounded-xl bg-teal-700 py-2.5 text-sm font-bold text-white transition hover:bg-teal-800 disabled:opacity-50"
            >
              {busy ? 'جارٍ المعالجة…' : mode === 'login' ? 'دخول' : 'إنشاء الحساب'}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          المعلومات المقدمة استرشادية مبنية على التشريعات الليبية المتاحة.
        </p>
      </div>
    </div>
  )
}
