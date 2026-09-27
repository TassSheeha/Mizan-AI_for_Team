import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { api, streamChat } from '../lib/api'
import { blobToWav16k } from '../lib/audio'
import {
  fetchAnswerSpeechUrl,
  registerActiveAudio,
  speakWithBrowser,
  stopActiveSpeech,
} from '../lib/tts'
import { useAuth } from '../lib/auth'
import type { ChatMessage, ConversationSummary, NotificationItem } from '../lib/types'

const SUGGESTIONS = [
  '📊 شن شروط ضريبة الدخل والخصومات؟',
  '🏢 كيف يتم تأسيس الشركات في القانون التجاري؟',
  '💼 شن حقي لو انفصلوني تعسفياً؟',
]

export default function ChatPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [unreadNotifications, setUnreadNotifications] = useState(0)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [showNotifications, setShowNotifications] = useState(false)
  const [notifLoading, setNotifLoading] = useState(false)
  const [toast, setToast] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [aiReady, setAiReady] = useState<boolean | null>(null)
  // 🔊 Auto-play the answer only when the sent query was written via the
  // microphone (mirrors app.py: render_audio_icon(autoplay=is_audio_input)).
  // No header toggle: mic → text appears in the box for editing → user sends
  // → answer auto-plays. Typed queries never auto-play.
  const [autoSpeakId, setAutoSpeakId] = useState<number | string | null>(null)
  const pendingVoiceRef = useRef(false)
  const micArmedRef = useRef(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const timerRef = useRef<number | null>(null)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [recordSeconds, setRecordSeconds] = useState(0)

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api<ConversationSummary[]>('/api/conversations'))
    } catch { /* transient */ }
  }, [])

  const loadNotifications = useCallback(async (silent = true) => {
    if (!silent) setNotifLoading(true)
    try {
      const rows = await api<NotificationItem[]>('/api/notifications')
      setNotifications(rows)
      setUnreadNotifications(rows.filter((r) => !r.is_read).length)
    } catch { /* transient — keep last known list */ }
    finally {
      if (!silent) setNotifLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConversations()
    loadNotifications()
    const t = setInterval(() => loadNotifications(), 30000)
    return () => clearInterval(t)
  }, [loadConversations, loadNotifications])

  // Auto-dismiss toast (same UX rhythm as Streamlit captions)
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(t)
  }, [toast])

  // AI-layer readiness probe (backend may still be loading the index)
  useEffect(() => {
    let alive = true
    const probe = async () => {
      try {
        const h = await api<{ status: string }>('/api/health')
        if (alive) setAiReady(h.status === 'ok')
      } catch { if (alive) setAiReady(false) }
    }
    probe()
    const t = setInterval(probe, 5000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const openConversation = useCallback(async (id: string) => {
    setSidebarOpen(false)
    setError('')
    stopActiveSpeech()
    setAutoSpeakId(null)
    pendingVoiceRef.current = false
    micArmedRef.current = false
    try {
      const data = await api<{ id: string; messages: ChatMessage[] }>(`/api/conversations/${id}`)
      setActiveId(data.id)
      setMessages(data.messages)
    } catch (e) {
      setError('تعذر فتح المحادثة.')
    }
  }, [])

  const newChat = () => {
    stopActiveSpeech()
    setAutoSpeakId(null)
    pendingVoiceRef.current = false
    micArmedRef.current = false
    setActiveId(null)
    setMessages([])
    setError('')
    setSidebarOpen(false)
  }

  const deleteConversation = async (id: string) => {
    await api(`/api/conversations/${id}`, { method: 'DELETE' })
    if (activeId === id) newChat()
    loadConversations()
  }

  const submitRename = async (id: string) => {
    const title = renameValue.trim()
    setRenamingId(null)
    if (!title) return
    await api(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) })
    loadConversations()
  }

  const send = async (text?: string) => {
    const query = (text ?? input).trim()
    if (!query || streaming) return
    // A new answer interrupts any currently playing speech (chat UX).
    // Auto-play only if this query was written via the microphone: the mic
    // arms the flag when transcription lands in the box, and sending
    // consumes it (user may edit the text first — still counts as mic use).
    stopActiveSpeech()
    setAutoSpeakId(null)
    pendingVoiceRef.current = micArmedRef.current
    micArmedRef.current = false
    setInput('')
    setError('')
    setStreaming(true)

    const userMsg: ChatMessage = { id: `tmp-u-${Date.now()}`, role: 'user', content: query }
    const pendingMsg: ChatMessage = { id: `tmp-a-${Date.now()}`, role: 'assistant', content: '', pending: true }
    setMessages((m) => [...m, userMsg, pendingMsg])

    const controller = new AbortController()
    abortRef.current = controller

    const patchPending = (patch: Partial<ChatMessage>) =>
      setMessages((m) => m.map((msg) => (msg.id === pendingMsg.id ? { ...msg, ...patch } : msg)))

    await streamChat(
      { conversation_id: activeId, query, top_k: 3, mode: 'hybrid' },
      {
        onMeta: (data) => {
          setActiveId(data.conversation_id)
        },
        onToken: (token) => {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingMsg.id ? { ...msg, content: msg.content + token } : msg,
            ),
          )
        },
        onDone: (data) => {
          const assistantId = (data.assistant_message_id as number) ?? pendingMsg.id
          const patch: Partial<ChatMessage> = {
            id: assistantId,
            pending: false,
            citations: (data.citations as ChatMessage['citations']) || [],
            confidence: data.confidence as number,
            retrieval_time: data.retrieval_time as number,
            generation_time: data.generation_time as number,
            provider: data.provider as string,
            answer_type: data.answer_type as string,
          }
          if (typeof data.content === 'string' && data.content) {
            patch.content = data.content
          }
          patchPending(patch)
          // Mirror app.py: autoplay the answer only when the query was spoken.
          if (pendingVoiceRef.current) {
            setAutoSpeakId(assistantId)
          }
          pendingVoiceRef.current = false
        },
        onError: (message) => {
          pendingVoiceRef.current = false
          setError(message)
          setMessages((m) => m.filter((msg) => msg.id !== pendingMsg.id))
        },
      },
      controller.signal,
    ).catch(() => {
      pendingVoiceRef.current = false
      setError('انقطع الاتصال أثناء البث.')
    })

    setStreaming(false)
    abortRef.current = null
    loadConversations()
  }

  const setFeedback = async (messageId: number | string, value: 'like' | 'dislike') => {
    if (typeof messageId !== 'number') {
      setToast({ kind: 'error', text: 'لا يمكن تقييم هذه الرسالة بعد — انتظر اكتمال حفظها.' })
      return
    }
    // Read the freshest state via functional update to avoid stale-closure toggles.
    let previous: ChatMessage['feedback'] = null
    let next: 'like' | 'dislike' | null = value
    setMessages((m) =>
      m.map((msg) => {
        if (msg.id !== messageId) return msg
        previous = msg.feedback ?? null
        next = previous === value ? null : value
        return { ...msg, feedback: next }
      }),
    )
    try {
      const res = await api<{ message_id: number; feedback: 'like' | 'dislike' | null }>(
        `/api/messages/${messageId}/feedback`,
        { method: 'POST', body: JSON.stringify({ value: next }) },
      )
      // Reconcile with the authoritative server value (covers like→dislike switches).
      setMessages((m) =>
        m.map((msg) => (msg.id === messageId ? { ...msg, feedback: res.feedback ?? null } : msg)),
      )
      if (res.feedback === 'like') {
        setToast({ kind: 'success', text: '✅ تم تسجيل تقييمك: إجابة مفيدة — شكراً لك!' })
      } else if (res.feedback === 'dislike') {
        setToast({ kind: 'success', text: '✅ تم تسجيل تقييمك: سنحسّن جودة هذه الإجابات — شكراً لك!' })
      } else {
        setToast({ kind: 'success', text: 'تم إلغاء تقييمك لهذه الإجابة.' })
      }
    } catch (err) {
      // Roll back the optimistic update so UI never diverges from the server.
      setMessages((m) =>
        m.map((msg) => (msg.id === messageId ? { ...msg, feedback: previous } : msg)),
      )
      setToast({
        kind: 'error',
        text: `❌ تعذر تسجيل التقييم: ${err instanceof Error ? err.message : 'حاول مجدداً.'}`,
      })
    }
  }

  const markNotificationRead = async (id: number) => {
    try {
      await api(`/api/notifications/${id}/read`, { method: 'POST' })
      setNotifications((rows) => rows.map((n) => (n.id === id ? { ...n, is_read: true } : n)))
      setUnreadNotifications((c) => Math.max(0, c - 1))
    } catch { /* transient */ }
  }

  const markAllNotificationsRead = async () => {
    try {
      await api('/api/notifications/read-all', { method: 'POST' })
      setNotifications((rows) => rows.map((n) => ({ ...n, is_read: true })))
      setUnreadNotifications(0)
    } catch { /* transient */ }
  }

  const stopStreaming = () => {
    abortRef.current?.abort()
    setStreaming(false)
  }

  // ─── Voice input (Tass02/whisper-small-libyan via /api/voice/transcribe) ────
  const finishRecording = useCallback(async () => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === 'inactive') return
    recorder.stop()
  }, [])

  const toggleRecording = useCallback(async () => {
    if (recording) { await finishRecording(); return }
    if (transcribing || streaming) return
    setError('')

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError('تعذر الوصول إلى الميكروفون. امنح الإذن للمتصفح ثم أعد المحاولة.')
      return
    }
    streamRef.current = stream
    audioChunksRef.current = []
    const recorder = new MediaRecorder(stream, {
      mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '',
    })
    mediaRecorderRef.current = recorder

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data)
    }
    recorder.onstop = async () => {
      // Cleanup UI state + release mic
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
      setRecording(false)
      setRecordSeconds(0)

      const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || 'audio/webm' })
      audioChunksRef.current = []
      if (blob.size < 2000) {
        setError('التسجيل قصير جداً. اضغط الميكروفون وتحدث لمدة 2-10 ثوانٍ.')
        return
      }

      setTranscribing(true)
      try {
        const wav = await blobToWav16k(blob)
        const form = new FormData()
        form.append('file', wav, 'voice.wav')
        const res = await api<{ text: string; message?: string }>('/api/voice/transcribe', {
          method: 'POST',
          body: form,
        })
        if (res.text) {
          // Show the transcribed speech in the box first (user may edit),
          // and arm auto-play: the next sent query counts as mic-written,
          // so its answer plays automatically (mirrors app.py autoplay).
          setInput(res.text)
          micArmedRef.current = true
          document.querySelector('textarea')?.focus()
        } else {
          setError(res.message || 'لم نتمكن من فهم التسجيل. حاول مجدداً.')
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'فشل التعرف على الصوت.')
      } finally {
        setTranscribing(false)
      }
    }

    recorder.start()
    setRecording(true)
    setRecordSeconds(0)
    timerRef.current = window.setInterval(
      () => setRecordSeconds((s) => {
        if (s >= 30) { void finishRecording() }
        return s + 1
      }),
      1000,
    )
  }, [recording, transcribing, streaming, finishRecording])

  // Release mic + any playing answer speech on unmount
  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    if (timerRef.current) clearInterval(timerRef.current)
    stopActiveSpeech()
  }, [])

  return (
    <div className="flex h-full bg-slate-50" dir="rtl">
      {/* ─── Sidebar ─── */}
      <aside
        className={`fixed inset-y-0 right-0 z-40 flex w-72 flex-col bg-slate-900 text-slate-100 transition-transform lg:static lg:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="flex items-center gap-2 px-4 py-4">
          <span className="text-2xl">⚖️</span>
          <div>
            <div className="font-extrabold leading-5">الميزان</div>
            <div className="text-[11px] text-slate-400">المستشار القانوني الليبي</div>
          </div>
        </div>

        <button
          onClick={newChat}
          className="mx-3 mb-3 flex items-center justify-center gap-2 rounded-xl bg-teal-600 py-2.5 text-sm font-bold text-white transition hover:bg-teal-500"
        >
          <span className="text-lg leading-none">＋</span> محادثة جديدة
        </button>

        <div className="nice-scroll flex-1 overflow-y-auto px-2">
          {conversations.length === 0 && (
            <p className="px-3 py-6 text-center text-xs text-slate-500">لا توجد محادثات بعد</p>
          )}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`group mb-1 flex items-center gap-1 rounded-lg px-2 transition ${
                activeId === c.id ? 'bg-slate-700/80' : 'hover:bg-slate-800'
              }`}
            >
              {renamingId === c.id ? (
                <input
                  autoFocus value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onBlur={() => submitRename(c.id)}
                  onKeyDown={(e) => e.key === 'Enter' && submitRename(c.id)}
                  className="my-1.5 w-full rounded bg-slate-800 px-2 py-1.5 text-sm outline-none ring-1 ring-teal-500"
                />
              ) : (
                <>
                  <button
                    onClick={() => openConversation(c.id)}
                    className="min-w-0 flex-1 py-2.5 text-right"
                  >
                    <div className="truncate text-sm">{c.title}</div>
                    <div className="truncate text-[11px] text-slate-500">
                      {c.message_count} رسالة
                    </div>
                  </button>
                  <button
                    title="إعادة تسمية"
                    onClick={() => { setRenamingId(c.id); setRenameValue(c.title) }}
                    className="hidden shrink-0 rounded p-1.5 text-slate-400 hover:text-white group-hover:block"
                  >
                    ✎
                  </button>
                  <button
                    title="حذف"
                    onClick={() => deleteConversation(c.id)}
                    className="hidden shrink-0 rounded p-1.5 text-slate-400 hover:text-red-400 group-hover:block"
                  >
                    🗑
                  </button>
                </>
              )}
            </div>
          ))}
        </div>

        <div className="border-t border-slate-700/60 p-3">
          {user?.role === 'admin' && (
            <Link
              to="/admin"
              className="mb-2 flex items-center justify-center rounded-lg bg-slate-800 py-2 text-xs font-semibold text-teal-300 transition hover:bg-slate-700"
            >
              🛡 لوحة تحكم المسؤول
            </Link>
          )}
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">{user?.username}</div>
              <div className="truncate text-[11px] text-slate-500">{user?.email}</div>
            </div>
            <button
              onClick={() => { logout(); navigate('/login') }}
              title="تسجيل الخروج"
              className="rounded-lg p-2 text-slate-400 transition hover:bg-slate-800 hover:text-red-400"
            >
              ⏻
            </button>
          </div>
        </div>
      </aside>

      {sidebarOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* ─── Main chat area ─── */}
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 lg:hidden"
          >
            ☰
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-bold text-slate-800">
              {conversations.find((c) => c.id === activeId)?.title || 'محادثة جديدة'}
            </h1>
          </div>
          <div className="relative">
            <button
              onClick={() => { setShowNotifications((s) => !s); loadNotifications() }}
              className="relative rounded-lg p-2 text-slate-500 transition hover:bg-slate-100"
              title="الإشعارات"
            >
              🔔
              {unreadNotifications > 0 && (
                <span className="absolute -top-0.5 -left-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
                  {unreadNotifications > 9 ? '9+' : unreadNotifications}
                </span>
              )}
            </button>
            {showNotifications && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowNotifications(false)} />
                <div className="absolute left-0 z-50 mt-2 w-80 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl" dir="rtl">
                  <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                    <span className="text-sm font-bold text-slate-800">📢 إشعارات المنصة</span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => loadNotifications(false)}
                        className="text-xs text-slate-400 hover:text-teal-600"
                        title="تحديث"
                      >
                        {notifLoading ? '…' : '⟳'}
                      </button>
                      {unreadNotifications > 0 && (
                        <button
                          onClick={markAllNotificationsRead}
                          className="text-xs font-semibold text-teal-700 hover:underline"
                        >
                          تعليم الكل كمقروء
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="nice-scroll max-h-96 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <p className="px-4 py-8 text-center text-xs text-slate-400">
                        لا توجد إشعارات بعد. عند إرسال المسؤول إشعاراً سيظهر هنا فوراً.
                      </p>
                    ) : (
                      notifications.map((n) => (
                        <button
                          key={n.id}
                          onClick={() => markNotificationRead(n.id)}
                          className={`block w-full border-b border-slate-50 px-4 py-3 text-right transition last:border-0 hover:bg-slate-50 ${
                            n.is_read ? 'opacity-70' : 'bg-teal-50/40'
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            {!n.is_read && <span className="h-2 w-2 shrink-0 rounded-full bg-teal-500" />}
                            <span className="flex-1 truncate text-sm font-bold text-slate-800">{n.title}</span>
                          </div>
                          <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-slate-600">{n.body}</p>
                          <div className="mt-1 text-[10px] text-slate-400">
                            {new Date(n.created_at).toLocaleString('ar')}
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </header>

        {aiReady === false && (
          <div className="bg-amber-50 px-4 py-2 text-center text-xs text-amber-700 border-b border-amber-200">
            ⏳ محرك الذكاء الاصطناعي قيد التحميل (فهرس 2,929 مادة قانونية)… ستتوفر الإجابات خلال لحظات.
          </div>
        )}

        {toast && (
          <div
            className={`border-b px-4 py-2 text-center text-xs font-semibold ${
              toast.kind === 'success'
                ? 'border-teal-200 bg-teal-50 text-teal-800'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            {toast.text}
          </div>
        )}

        <div ref={scrollRef} className="nice-scroll flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-4 py-6">
            {messages.length === 0 ? (
              <EmptyState onPick={(q) => send(q)} />
            ) : (
              <div className="space-y-6">
                {messages.map((m, idx) => (
                  <MessageBubble
                    key={m.id}
                    message={m}
                    isFirst={idx === 0}
                    onFeedback={setFeedback}
                    autoPlay={m.id === autoSpeakId}
                    onAutoPlayDone={() => setAutoSpeakId((cur) => (cur === m.id ? null : cur))}
                    onSpeakError={(msg) => setToast({ kind: 'error', text: msg })}
                  />
                ))}
              </div>
            )}
            {error && (
              <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}
          </div>
        </div>

        {/* Input */}
        <div className="border-t border-slate-200 bg-white px-4 py-3">
          {recording && (
            <div className="mx-auto mb-2 flex max-w-3xl items-center justify-center gap-2 rounded-xl border border-red-200 bg-red-50 py-2 text-sm font-semibold text-red-600">
              <span className="typing-dot" /> جارٍ التسجيل… {recordSeconds} ثانية — اضغط الميكروفون للإيقاف
            </div>
          )}
          {transcribing && (
            <div className="mx-auto mb-2 flex max-w-3xl items-center justify-center gap-2 rounded-xl border border-teal-200 bg-teal-50 py-2 text-sm font-semibold text-teal-700">
              <span className="typing-dot" /> يتم التعرف على الكلام (Whisper الليبي)…
            </div>
          )}
          <form
            onSubmit={(e) => { e.preventDefault(); send() }}
            className="mx-auto flex max-w-3xl items-end gap-2"
          >
            <button
              type="button"
              onClick={toggleRecording}
              disabled={streaming || transcribing}
              title={recording ? 'إيقاف التسجيل' : 'التحدث بالصوت (الميكروفون)'}
              className={`h-[46px] w-[46px] shrink-0 rounded-2xl text-lg transition disabled:opacity-40 ${
                recording
                  ? 'animate-pulse bg-red-500 text-white hover:bg-red-600'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {recording ? '⏹' : '🎤'}
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              rows={1}
              placeholder="اكتب سؤالك القانوني هنا… (بالفصحى أو باللهجة الليبية)"
              className="max-h-40 min-h-[46px] flex-1 resize-y rounded-2xl border border-slate-300 px-4 py-3 text-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
            />
            {streaming ? (
              <button
                type="button" onClick={stopStreaming}
                className="h-[46px] rounded-2xl bg-slate-200 px-5 text-sm font-bold text-slate-700 transition hover:bg-slate-300"
              >
                إيقاف
              </button>
            ) : (
              <button
                type="submit" disabled={!input.trim()}
                className="h-[46px] rounded-2xl bg-teal-700 px-5 text-sm font-bold text-white transition hover:bg-teal-800 disabled:opacity-40"
              >
                إرسال
              </button>
            )}
          </form>
          <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-slate-400">
            ⚖️ المعلومات المقدمة استرشادية مبنية على التشريعات الليبية المتاحة ولا تغني عن استشارة محامٍ.
          </p>
        </div>
      </main>
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────
function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="fade-up flex flex-col items-center py-14 text-center">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-teal-700/10 text-3xl">⚖️</div>
      <h2 className="text-xl font-extrabold text-slate-800">كيف أستطيع مساعدتك اليوم؟</h2>
      <p className="mt-2 max-w-md text-sm text-slate-500">
        اسأل عن أي موضوع قانوني في التشريعات الليبية — العمل، الشركات، الضرائب، المصارف، الأحوال المدنية وغيرها.
      </p>
      <div className="mt-8 grid w-full max-w-xl gap-3 sm:grid-cols-1">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-right text-sm text-slate-700 shadow-sm transition hover:border-teal-500 hover:shadow"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}

function MessageBubble({ message, isFirst, onFeedback, autoPlay, onAutoPlayDone, onSpeakError }: {
  message: ChatMessage
  isFirst: boolean
  onFeedback: (id: number | string, v: 'like' | 'dislike') => void
  autoPlay: boolean
  onAutoPlayDone: () => void
  onSpeakError: (msg: string) => void
}) {
  const [showCitations, setShowCitations] = useState(false)
  const isUser = message.role === 'user'
  const streamingEmpty = message.pending && !message.content
  // Mirror Streamlit semantics: every persisted assistant reply is rateable
  // except the static welcome message. Older rows may lack answer_type, so
  // gate on persistence (numeric id) rather than on answer_type alone.
  const isWelcome = isFirst && message.role === 'assistant' && message.answer_type === 'greeting'
  const rateable = !isUser && !message.pending && typeof message.id === 'number' && !isWelcome
  const speakable = !isUser && !message.pending && message.content.trim().length > 0

  if (isUser) {
    return (
      <div className="fade-up flex justify-start">
        <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-teal-700 px-4 py-3 text-sm leading-7 text-white whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="fade-up">
      <div className="flex items-start gap-2">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-teal-700/10 text-base">⚖️</div>
        <div className="min-w-0 flex-1">
          {streamingEmpty ? (
            <div className="flex items-center gap-1.5 py-3 text-teal-600">
              <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
            </div>
          ) : (
            <div className="prose prose-sm prose-slate max-w-none leading-8 text-slate-800 prose-p:my-2 prose-li:my-0.5 prose-strong:text-teal-900">
              <ReactMarkdown>{message.content}</ReactMarkdown>
              {message.pending && <span className="stream-caret text-teal-600" />}
            </div>
          )}

          {/* Metrics + actions row */}
          {(rateable || speakable) && (
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-400">
              {speakable && (
                <SpeakButton
                  text={message.content}
                  autoPlay={autoPlay}
                  onAutoPlayDone={onAutoPlayDone}
                  onError={onSpeakError}
                />
              )}
              {rateable && (
              <>
              <button
                onClick={() => onFeedback(message.id, 'like')}
                className={`rounded-lg px-2 py-1 text-base transition hover:bg-teal-50 hover:text-teal-600 ${
                  message.feedback === 'like' ? 'bg-teal-50 text-teal-600 ring-1 ring-teal-300' : ''
                }`}
                title="إجابة مفيدة"
              >
                👍
              </button>
              <button
                onClick={() => onFeedback(message.id, 'dislike')}
                className={`rounded-lg px-2 py-1 text-base transition hover:bg-red-50 hover:text-red-500 ${
                  message.feedback === 'dislike' ? 'bg-red-50 text-red-500 ring-1 ring-red-300' : ''
                }`}
                title="إجابة غير مفيدة"
              >
                👎
              </button>
              {typeof message.confidence === 'number' && message.confidence > 0 && (
                <span title="درجة ثقة الاسترجاع">
                  ثقة {(message.confidence * 100).toFixed(0)}%
                </span>
              )}
              {message.provider && <span className="uppercase">{message.provider}</span>}
              </>
              )}
            </div>
          )}
          {rateable && message.feedback === 'like' && (
            <div className="mt-1 text-[11px] font-semibold text-teal-700">
              ✅ تم تسجيل تقييمك: إجابة مفيدة — شكراً لك!
            </div>
          )}
          {rateable && message.feedback === 'dislike' && (
            <div className="mt-1 text-[11px] font-semibold text-slate-500">
              ✅ تم تسجيل تقييمك: سنحسّن جودة هذه الإجابات — شكراً لك!
            </div>
          )}

          {/* Citations */}
          {message.citations && message.citations.length > 0 && (
            <div className="mt-3">
              <button
                onClick={() => setShowCitations((s) => !s)}
                className="flex items-center gap-1 rounded-lg border border-teal-200 bg-teal-50 px-3 py-1.5 text-xs font-semibold text-teal-800 transition hover:bg-teal-100"
              >
                📚 السند القانوني ({message.citations.length} مواد)
                <span className={`transition ${showCitations ? 'rotate-180' : ''}`}>▾</span>
              </button>
              {showCitations && (
                <div className="mt-2 space-y-2">
                  {message.citations.map((c, i) => (
                    <div key={i} className="rounded-xl border-r-4 border-teal-600 bg-slate-50 p-3 text-xs leading-6 text-slate-700">
                      <div className="mb-1 font-bold text-slate-800">
                        📌 المادة ({c.article ?? '—'}) — {c.document}
                        {c.year ? ` (${c.year})` : ''}
                      </div>
                      <div className="mb-1 text-[11px] text-slate-500">
                        {c.section && <>| {c.section} </>}
                        {c.chapter && <>| {c.chapter} </>}
                        {c.page != null && <>| صفحة {c.page}</>}
                      </div>
                      <p className="whitespace-pre-wrap text-slate-600">{c.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Answer speech (🔊 per answer, mirrors app.py render_audio_icon) ─────────
function SpeakButton({ text, autoPlay, onAutoPlayDone, onError }: {
  text: string
  autoPlay: boolean
  onAutoPlayDone: () => void
  onError: (msg: string) => void
}) {
  const [state, setState] = useState<'idle' | 'loading' | 'playing' | 'error'>('idle')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const urlRef = useRef<string | null>(null)
  const textRef = useRef(text)
  const autoFiredRef = useRef(false)
  textRef.current = text

  const cleanup = useCallback(() => {
    const el = audioRef.current
    if (el) {
      try { el.pause() } catch { /* ignore */ }
      audioRef.current = null
    }
  }, [])

  useEffect(() => () => {
    cleanup()
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current)
      urlRef.current = null
    }
  }, [cleanup])

  const play = useCallback(async () => {
    const current = textRef.current.trim()
    if (!current) return
    // Toggle: clicking while playing pauses (same as app.py icon button).
    if (audioRef.current && !audioRef.current.paused) {
      try { audioRef.current.pause() } catch { /* ignore */ }
      setState('idle')
      return
    }
    setState('loading')
    try {
      if (!urlRef.current) {
        urlRef.current = await fetchAnswerSpeechUrl(current)
      }
      let el = audioRef.current
      if (!el) {
        el = new Audio(urlRef.current)
        audioRef.current = el
        el.onplay = () => {
          registerActiveAudio(el as HTMLAudioElement)
          setState('playing')
        }
        el.onpause = () => setState('idle')
        el.onended = () => setState('idle')
        el.onerror = () => {
          // Cached MP3 is unusable — drop it and fall back to browser voice.
          if (urlRef.current) {
            URL.revokeObjectURL(urlRef.current)
            urlRef.current = null
          }
          audioRef.current = null
          try {
            speakWithBrowser(current, () => setState('idle'))
            setState('playing')
          } catch {
            setState('error')
            onError('❌ تعذر تشغيل الصوت حالياً.')
          }
        }
      } else {
        el.src = urlRef.current
      }
      registerActiveAudio(el)
      await el.play()
    } catch (err) {
      // Server TTS failed (offline/quota) → browser fallback, like app.py's
      // unlockAudio path which never leaves the user without playback.
      try {
        speakWithBrowser(current, () => setState('idle'))
        setState('playing')
      } catch {
        setState('error')
        onError(`❌ تعذر توليد الصوت: ${err instanceof Error ? err.message : 'حاول مجدداً.'}`)
      }
    }
  }, [onError])

  // Autoplay once when this answer is the direct result of a mic query.
  // Browsers may block programmatic play(); in that case we surface the 🔊
  // button state and let one tap start playback (no silent failure).
  useEffect(() => {
    if (!autoPlay || autoFiredRef.current) return
    autoFiredRef.current = true
    onAutoPlayDone()
    void play().catch(() => {
      onError('🔊 اضغط زر السماعة للاستماع للإجابة.')
    })
  }, [autoPlay, play, onAutoPlayDone, onError])

  // If the answer text streams into its final form, drop stale audio cache.
  useEffect(() => {
    autoFiredRef.current = false
    return () => {
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
      cleanup()
    }
  }, [text, cleanup])

  return (
    <button
      onClick={play}
      className={`rounded-lg px-2 py-1 text-base transition ${
        state === 'playing'
          ? 'bg-teal-50 text-teal-600 ring-1 ring-teal-300'
          : 'hover:bg-slate-100 hover:text-teal-600'
      } disabled:opacity-50`}
      title={state === 'playing' ? 'إيقاف الاستماع' : 'الاستماع للإجابة'}
      disabled={state === 'loading'}
    >
      {state === 'loading' ? '⏳' : state === 'playing' ? '⏸' : '🔊'}
    </button>
  )
}
