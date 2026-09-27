import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type {
  AdminStats, AdminUser, LegalDocument, NotificationItem, SystemHealth,
} from '../lib/types'

type Tab = 'overview' | 'documents' | 'feedback' | 'users' | 'notifications' | 'system'

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'overview', label: 'نظرة عامة', icon: '📊' },
  { id: 'documents', label: 'الوثائق القانونية', icon: '📚' },
  { id: 'feedback', label: 'تقييمات المستخدمين', icon: '⭐' },
  { id: 'users', label: 'المستخدمون', icon: '👥' },
  { id: 'notifications', label: 'الإشعارات', icon: '📢' },
  { id: 'system', label: 'حالة النظام', icon: '🖥' },
]

export default function AdminPage() {
  const { user } = useAuth()
  const [tab, setTab] = useState<Tab>('overview')

  return (
    <div className="flex min-h-screen bg-slate-100" dir="rtl">
      <aside className="hidden w-60 shrink-0 flex-col bg-slate-900 p-4 text-slate-100 md:flex">
        <div className="mb-6 flex items-center gap-2">
          <span className="text-2xl">🛡</span>
          <div>
            <div className="font-extrabold">لوحة المسؤول</div>
            <div className="text-[11px] text-slate-400">الميزان — إدارة النظام</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm transition ${
                tab === t.id ? 'bg-teal-600 font-bold text-white' : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              <span>{t.icon}</span> {t.label}
            </button>
          ))}
        </nav>
        <Link to="/" className="rounded-lg bg-slate-800 py-2 text-center text-xs font-semibold text-teal-300 hover:bg-slate-700">
          ← العودة للمحادثة
        </Link>
      </aside>

      <main className="min-w-0 flex-1 p-4 md:p-8">
        <div className="mb-4 flex gap-2 overflow-x-auto md:hidden">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs font-semibold ${
                tab === t.id ? 'bg-teal-600 text-white' : 'bg-white text-slate-600'
              }`}
            >
              {t.icon} {t.label}
            </button>
          ))}
        </div>

        {tab === 'overview' && <OverviewTab />}
        {tab === 'documents' && <DocumentsTab />}
        {tab === 'feedback' && <FeedbackTab />}
        {tab === 'users' && <UsersTab currentUser={user?.id ?? 0} />}
        {tab === 'notifications' && <NotificationsTab />}
        {tab === 'system' && <SystemTab />}
      </main>
    </div>
  )
}

// ─── Overview ─────────────────────────────────────────────────────────────────
function OverviewTab() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<AdminStats>('/api/admin/stats').then(setStats).catch((e) => setError(e.message))
  }, [])

  if (error) return <Alert>{error}</Alert>
  if (!stats) return <Loading />
  const sat = stats.feedback.satisfaction

  const cards = [
    { label: 'المستخدمون', value: stats.users, sub: `${stats.active_users} نشط`, icon: '👥' },
    { label: 'المحادثات', value: stats.conversations, sub: '', icon: '💬' },
    { label: 'الرسائل', value: stats.messages, sub: `${stats.messages_24h} خلال 24 ساعة`, icon: '✉️' },
    { label: 'الوثائق المفهرسة', value: stats.documents, sub: `${stats.indexed_chunks} مقطعاً`, icon: '📚' },
    { label: 'تقييمات إيجابية', value: stats.feedback.like, sub: `سلبيات: ${stats.feedback.dislike}`, icon: '👍' },
    {
      label: 'نسبة الرضا',
      value: sat != null ? `${sat}%` : '—',
      sub: `متوسط الثقة: ${(stats.avg_confidence * 100).toFixed(0)}%`,
      icon: '⭐',
    },
  ]

  return (
    <div className="fade-up">
      <h2 className="mb-1 text-xl font-extrabold text-slate-800">نظرة عامة</h2>
      <p className="mb-6 text-sm text-slate-500">ملخص حي لحالة المنصة ونشاط المستخدمين.</p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-500">{c.label}</span>
              <span className="text-xl">{c.icon}</span>
            </div>
            <div className="text-3xl font-extrabold text-slate-900">{c.value}</div>
            {c.sub && <div className="mt-1 text-xs text-slate-400">{c.sub}</div>}
          </div>
        ))}
      </div>
      <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-5 text-sm">
        <span className="font-semibold text-slate-700">حالة محرك الذكاء الاصطناعي: </span>
        <StatusPill ok={stats.ai_status === 'ready'} text={aiStatusLabel(stats.ai_status)} />
      </div>
    </div>
  )
}

function aiStatusLabel(s: string) {
  if (s === 'ready') return 'جاهز'
  if (s === 'failed') return 'خطأ في التحميل'
  return 'قيد التحميل'
}

// ─── Documents ────────────────────────────────────────────────────────────────
function DocumentsTab() {
  const [docs, setDocs] = useState<LegalDocument[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [showForm, setShowForm] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [meta, setMeta] = useState({ doc_id: '', title: '', doc_type: 'law', year: '', specialization: '' })

  const load = useCallback(async () => {
    try {
      setDocs(await api<LegalDocument[]>('/api/admin/documents'))
    } catch (e) {
      setMessage(`❌ ${e instanceof Error ? e.message : 'تعذر تحميل الوثائق.'}`)
    }
  }, [])
  useEffect(() => { load() }, [load])

  // Auto-refresh while any document is still being indexed in the background,
  // so the admin sees processing → indexed without manual reloads.
  useEffect(() => {
    if (!docs || !docs.some((d) => d.status === 'processing')) return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [docs, load])

  const upload = async (e: React.FormEvent) => {
    e.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) { setMessage('اختر ملفاً أولاً.'); return }
    setBusy(true); setMessage('')
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('doc_id', meta.doc_id)
      form.append('title', meta.title)
      form.append('doc_type', meta.doc_type)
      form.append('year', meta.year || '0')
      form.append('specialization', meta.specialization)
      await api('/api/admin/documents/upload', { method: 'POST', body: form })
      setMessage(`✅ تم رفع «${meta.title}» — جارٍ الفهرسة في الخلفية. ستتحول الحالة إلى «مفهرسة» تلقائياً.`)
      setShowForm(false)
      setMeta({ doc_id: '', title: '', doc_type: 'law', year: '', specialization: '' })
      if (fileRef.current) fileRef.current.value = ''
      await load()
    } catch (err) {
      setMessage(`❌ ${err instanceof Error ? err.message : 'فشل الرفع'}`)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (doc: LegalDocument) => {
    if (!confirm(`هل تريد حذف «${doc.title}» نهائياً من الفهرس؟`)) return
    setBusy(true)
    try {
      await api(`/api/admin/documents/${doc.doc_id}`, { method: 'DELETE' })
      setMessage(`✅ تم حذف الوثيقة وإعادة تحميل الفهرس.`)
      load()
    } catch (err) {
      setMessage(`❌ ${err instanceof Error ? err.message : 'فشل الحذف'}`)
    } finally { setBusy(false) }
  }

  const reindex = async (doc: LegalDocument) => {
    if (doc.status === 'processing') {
      setMessage('⏳ الوثيقة قيد المعالجة حالياً — انتظر اكتمال الفهرسة قبل إعادة الفهرسة.')
      return
    }
    setBusy(true)
    setMessage(`⏳ جارٍ إعادة فهرسة «${doc.title}»…`)
    try {
      const res = await api<{ ok: boolean; chunks: number }>(
        `/api/admin/documents/${doc.doc_id}/reindex`, { method: 'POST' },
      )
      setMessage(`✅ تمت إعادة فهرسة «${doc.title}» (${res.chunks} مقطعاً) وأصبحت حيّة في البحث.`)
      await load()
    } catch (err) {
      setMessage(`❌ ${err instanceof Error ? err.message : 'فشلت إعادة الفهرسة'}`)
    } finally { setBusy(false) }
  }

  return (
    <div className="fade-up">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-extrabold text-slate-800">الوثائق القانونية</h2>
          <p className="text-sm text-slate-500">إدارة قاعدة المعرفة: إضافة، حذف، إعادة فهرسة.</p>
        </div>
        <button
          onClick={() => setShowForm((s) => !s)}
          className="rounded-xl bg-teal-700 px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-800"
        >
          ＋ إضافة وثيقة
        </button>
      </div>

      {message && <Alert>{message}</Alert>}

      {showForm && (
        <form onSubmit={upload} className="mb-6 space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="ملف الوثيقة (PDF بنص أو JSON chunks)">
              <input ref={fileRef} type="file" accept=".pdf,.json" required className="w-full text-sm" />
            </Field>
            <Field label="المعرّف (بالإنجليزية، فريد)">
              <input value={meta.doc_id} onChange={(e) => setMeta({ ...meta, doc_id: e.target.value })}
                required dir="ltr" placeholder="LAW_15_1980" className={inputCls} />
            </Field>
            <Field label="العنوان">
              <input value={meta.title} onChange={(e) => setMeta({ ...meta, title: e.target.value })}
                required placeholder="قانون التقاعد رقم 15 لسنة 1980" className={inputCls} />
            </Field>
            <Field label="النوع">
              <select value={meta.doc_type} onChange={(e) => setMeta({ ...meta, doc_type: e.target.value })} className={inputCls}>
                <option value="law">قانون</option>
                <option value="regulation">لائحة</option>
                <option value="decision">قرار</option>
                <option value="guide">دليل</option>
              </select>
            </Field>
            <Field label="السنة">
              <input value={meta.year} onChange={(e) => setMeta({ ...meta, year: e.target.value })}
                type="number" min="0" max="2100" placeholder="1980" className={inputCls} />
            </Field>
            <Field label="التخصص">
              <input value={meta.specialization} onChange={(e) => setMeta({ ...meta, specialization: e.target.value })}
                dir="ltr" placeholder="pension" className={inputCls} />
            </Field>
          </div>
          <button disabled={busy} className="rounded-xl bg-teal-700 px-5 py-2.5 text-sm font-bold text-white hover:bg-teal-800 disabled:opacity-50">
            {busy ? 'جارٍ الرفع…' : 'رفع وفهرسة'}
          </button>
        </form>
      )}

      {!docs ? <Loading /> : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3 text-right">العنوان</th>
                <th className="px-4 py-3 text-right">المعرّف</th>
                <th className="px-4 py-3">السنة</th>
                <th className="px-4 py-3">المقاطع</th>
                <th className="px-4 py-3">الحالة</th>
                <th className="px-4 py-3">إجراءات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {docs.map((d) => (
                <tr key={d.doc_id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-slate-800">{d.title}</div>
                    {d.error_message && <div className="text-xs text-red-500">{d.error_message}</div>}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500" dir="ltr">{d.doc_id}</td>
                  <td className="px-4 py-3 text-center">{d.year || '—'}</td>
                  <td className="px-4 py-3 text-center">{d.chunk_count}</td>
                  <td className="px-4 py-3 text-center">
                    <StatusPill ok={d.status === 'indexed'}
                      text={d.status === 'indexed' ? 'مفهرسة' : d.status === 'processing' ? 'قيد المعالجة' : 'خطأ'} />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <button disabled={busy} onClick={() => reindex(d)}
                      className="mx-1 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-200 disabled:opacity-50">
                      ⟳ إعادة فهرسة
                    </button>
                    {!d.is_builtin && (
                      <button disabled={busy} onClick={() => remove(d)}
                        className="mx-1 rounded-lg bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-100 disabled:opacity-50">
                        🗑 حذف
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Feedback ─────────────────────────────────────────────────────────────────
interface FeedbackItem {
  id: number
  value: 'like' | 'dislike'
  created_at: string
  message_content: string
  confidence: number
  provider: string
  conversation_title: string
}

type FeedbackResponse = {
  items: FeedbackItem[]
  summary: { like: number; dislike: number; total: number }
}

function FeedbackTab() {
  const [data, setData] = useState<FeedbackResponse | null>(null)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    setRefreshing(true)
    setError('')
    try {
      setData(await api<FeedbackResponse>('/api/admin/feedback'))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذر تحميل التقييمات.')
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (error) return <Alert>{`❌ ${error}`}</Alert>
  if (!data) return <Loading />
  const sat = data.summary.total ? Math.round((data.summary.like / data.summary.total) * 100) : null

  return (
    <div className="fade-up">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="mb-1 text-xl font-extrabold text-slate-800">تقييمات المستخدمين</h2>
          <p className="text-sm text-slate-500">تحليل رضا المستخدمين عن إجابات النظام.</p>
        </div>
        <button
          onClick={load}
          disabled={refreshing}
          className="rounded-xl bg-slate-100 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-200 disabled:opacity-50"
        >
          {refreshing ? 'جارٍ التحديث…' : '⟳ تحديث'}
        </button>
      </div>

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 text-center">
          <div className="text-3xl font-extrabold text-teal-700">{data.summary.like}</div>
          <div className="mt-1 text-xs text-slate-500">👍 مفيدة</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 text-center">
          <div className="text-3xl font-extrabold text-red-500">{data.summary.dislike}</div>
          <div className="mt-1 text-xs text-slate-500">👎 غير مفيدة</div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 text-center">
          <div className="text-3xl font-extrabold text-slate-900">{sat != null ? `${sat}%` : '—'}</div>
          <div className="mt-1 text-xs text-slate-500">نسبة الرضا</div>
        </div>
      </div>

      {data.items.length === 0 ? (
        <Empty>لا توجد تقييمات بعد. ستظهر هنا فور تقييم المستخدمين للإجابات.</Empty>
      ) : (
        <div className="space-y-3">
          {data.items.map((f) => (
            <div key={f.id} className="rounded-2xl border border-slate-200 bg-white p-4 text-sm">
              <div className="mb-2 flex items-center gap-2 text-xs text-slate-400">
                <span>{f.value === 'like' ? '👍' : '👎'}</span>
                <span>{new Date(f.created_at).toLocaleString('ar')}</span>
                <span>• محادثة: {f.conversation_title}</span>
                {f.confidence > 0 && <span>• ثقة {(f.confidence * 100).toFixed(0)}%</span>}
              </div>
              <p className="whitespace-pre-wrap leading-6 text-slate-700">{f.message_content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Users ────────────────────────────────────────────────────────────────────
function UsersTab({ currentUser }: { currentUser: number }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null)

  const load = useCallback(() => {
    api<AdminUser[]>('/api/admin/users').then(setUsers).catch(() => undefined)
  }, [])
  useEffect(load, [load])

  const toggleActive = async (u: AdminUser) => {
    await api(`/api/admin/users/${u.id}`, {
      method: 'PATCH', body: JSON.stringify({ is_active: !u.is_active }),
    })
    load()
  }

  const toggleRole = async (u: AdminUser) => {
    await api(`/api/admin/users/${u.id}`, {
      method: 'PATCH', body: JSON.stringify({ role: u.role === 'admin' ? 'user' : 'admin' }),
    })
    load()
  }

  if (!users) return <Loading />
  return (
    <div className="fade-up">
      <h2 className="mb-1 text-xl font-extrabold text-slate-800">المستخدمون</h2>
      <p className="mb-6 text-sm text-slate-500">إدارة الحسابات والصلاحيات.</p>
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-4 py-3 text-right">المستخدم</th>
              <th className="px-4 py-3">الدور</th>
              <th className="px-4 py-3">المحادثات</th>
              <th className="px-4 py-3">آخر دخول</th>
              <th className="px-4 py-3">الحالة</th>
              <th className="px-4 py-3">إجراءات</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.map((u) => (
              <tr key={u.id} className="hover:bg-slate-50">
                <td className="px-4 py-3">
                  <div className="font-semibold text-slate-800">{u.username}</div>
                  <div className="text-xs text-slate-400" dir="ltr">{u.email}</div>
                </td>
                <td className="px-4 py-3 text-center">
                  <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${
                    u.role === 'admin' ? 'bg-teal-100 text-teal-700' : 'bg-slate-100 text-slate-600'
                  }`}>
                    {u.role === 'admin' ? 'مسؤول' : 'مستخدم'}
                  </span>
                </td>
                <td className="px-4 py-3 text-center">{u.conversation_count}</td>
                <td className="px-4 py-3 text-center text-xs text-slate-500">
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleString('ar') : '—'}
                </td>
                <td className="px-4 py-3 text-center">
                  <StatusPill ok={u.is_active} text={u.is_active ? 'نشط' : 'معطّل'} />
                </td>
                <td className="px-4 py-3 text-center">
                  {u.id !== currentUser && (
                    <>
                      <button onClick={() => toggleRole(u)}
                        className="mx-1 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-200">
                        {u.role === 'admin' ? 'تنزيل الصلاحية' : 'ترقية لمسؤول'}
                      </button>
                      <button onClick={() => toggleActive(u)}
                        className={`mx-1 rounded-lg px-3 py-1.5 text-xs font-semibold ${
                          u.is_active ? 'bg-red-50 text-red-600 hover:bg-red-100' : 'bg-teal-50 text-teal-700 hover:bg-teal-100'
                        }`}>
                        {u.is_active ? 'تعطيل' : 'تنشيط'}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Notifications ────────────────────────────────────────────────────────────
function NotificationsTab() {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [sent, setSent] = useState<{ id: number; title: string; body: string; created_at: string }[]>([])

  const load = useCallback(() => {
    api<typeof sent>('/api/admin/notifications').then(setSent).catch(() => undefined)
  }, [])
  useEffect(load, [load])

  const send = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setMessage('')
    try {
      await api('/api/admin/notifications', {
        method: 'POST', body: JSON.stringify({ title, body }),
      })
      setMessage('✅ تم إرسال الإشعار لجميع المستخدمين.')
      setTitle(''); setBody('')
      load()
    } catch (err) {
      setMessage(`❌ ${err instanceof Error ? err.message : 'فشل الإرسال'}`)
    } finally { setBusy(false) }
  }

  return (
    <div className="fade-up">
      <h2 className="mb-1 text-xl font-extrabold text-slate-800">إشعارات المستخدمين</h2>
      <p className="mb-6 text-sm text-slate-500">بث إشعارات عامة تظهر لجميع مستخدمي المنصة.</p>

      <form onSubmit={send} className="mb-6 space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <Field label="عنوان الإشعار">
          <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} className={inputCls} />
        </Field>
        <Field label="نص الإشعار">
          <textarea value={body} onChange={(e) => setBody(e.target.value)} required rows={4} maxLength={4000} className={inputCls} />
        </Field>
        <button disabled={busy} className="rounded-xl bg-teal-700 px-5 py-2.5 text-sm font-bold text-white hover:bg-teal-800 disabled:opacity-50">
          {busy ? 'جارٍ الإرسال…' : '📢 إرسال الإشعار'}
        </button>
      </form>
      {message && <Alert>{message}</Alert>}

      <div className="space-y-3">
        {sent.map((n) => (
          <div key={n.id} className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="font-bold text-slate-800">{n.title}</div>
            <p className="mt-1 text-sm text-slate-600">{n.body}</p>
            <div className="mt-2 text-xs text-slate-400">{new Date(n.created_at).toLocaleString('ar')}</div>
          </div>
        ))}
        {sent.length === 0 && <Empty>لم يتم إرسال إشعارات بعد.</Empty>}
      </div>
    </div>
  )
}

// ─── System ───────────────────────────────────────────────────────────────────
function SystemTab() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [audit, setAudit] = useState<{ id: number; action: string; detail: string; created_at: string }[]>([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api<SystemHealth>('/api/admin/health').then(setHealth).catch(() => undefined)
    api<typeof audit>('/api/admin/audit-log').then(setAudit).catch(() => undefined)
  }, [])
  useEffect(() => {
    load()
    const t = setInterval(() => api<SystemHealth>('/api/admin/health').then(setHealth).catch(() => undefined), 15000)
    return () => clearInterval(t)
  }, [load])

  const downloadBackup = async () => {
    setBusy(true)
    try {
      const blob = await fetch('/api/admin/backup', {
        headers: { Authorization: `Bearer ${localStorage.getItem('mizan_access')}` },
      }).then((r) => (r.ok ? r.blob() : Promise.reject(new Error('فشل النسخ'))))
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `mizan_backup_${new Date().toISOString().slice(0, 10)}.db`
      a.click()
      URL.revokeObjectURL(url)
    } catch { /* ignore */ }
    setBusy(false)
  }

  if (!health) return <Loading />

  const comps = [
    { name: 'قاعدة البيانات', ok: health.components.database.ok, sub: `${health.components.database.latency_ms} ms` },
    { name: 'محرك الذكاء الاصطناعي', ok: health.components.ai_layer.status === 'ready', sub: health.components.ai_layer.status },
    { name: 'الفهرس المتجهي', ok: health.components.vector_index.indexed_chunks > 0, sub: `${health.components.vector_index.indexed_chunks} مقطعاً` },
    { name: 'Groq API', ok: health.components.groq_api.ok === true, sub: health.components.groq_api.model },
  ]

  return (
    <div className="fade-up">
      <h2 className="mb-1 text-xl font-extrabold text-slate-800">حالة النظام</h2>
      <p className="mb-6 text-sm text-slate-500">
        مراقبة حية (تتحدث كل 15 ثانية) — وقت التشغيل: {Math.round(health.uptime_seconds / 60)} دقيقة
      </p>

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {comps.map((c) => (
          <div key={c.name} className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-700">{c.name}</span>
              <StatusPill ok={c.ok} text={c.ok ? 'يعمل' : 'مشكلة'} />
            </div>
            <div className="mt-2 text-xs text-slate-400" dir="ltr">{c.sub}</div>
          </div>
        ))}
      </div>

      <button
        onClick={downloadBackup} disabled={busy}
        className="mb-6 rounded-xl bg-slate-800 px-5 py-2.5 text-sm font-bold text-white hover:bg-slate-700 disabled:opacity-50"
      >
        💾 {busy ? 'جارٍ التحضير…' : 'تنزيل نسخة احتياطية من قاعدة البيانات'}
      </button>

      <h3 className="mb-3 font-bold text-slate-800">سجل التدقيق (آخر العمليات الإدارية)</h3>
      <div className="rounded-2xl border border-slate-200 bg-white p-4 text-xs">
        {audit.length === 0 ? <Empty>لا توجد عمليات مسجلة بعد.</Empty> : (
          <div className="space-y-2" dir="rtl">
            {audit.map((a) => (
              <div key={a.id} className="flex items-center gap-2 border-b border-slate-50 pb-2">
                <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-600" dir="ltr">{a.action}</span>
                <span className="text-slate-600">{a.detail}</span>
                <span className="ms-auto text-slate-400">{new Date(a.created_at).toLocaleString('ar')}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Shared bits ──────────────────────────────────────────────────────────────
const inputCls = 'w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-sm font-semibold text-slate-700">{label}</label>
      {children}
    </div>
  )
}

function StatusPill({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold ${
      ok ? 'bg-teal-100 text-teal-700' : 'bg-amber-100 text-amber-700'
    }`}>
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? 'bg-teal-500' : 'bg-amber-500'}`} />
      {text}
    </span>
  )
}

function Loading() {
  return (
    <div className="flex items-center justify-center gap-2 py-20 text-teal-600">
      <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-white py-14 text-center text-sm text-slate-400">
      {children}
    </div>
  )
}

function Alert({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm">
      {children}
    </div>
  )
}

// Re-export for potential reuse
export type { NotificationItem }
