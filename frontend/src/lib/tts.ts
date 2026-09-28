/**
 * tts.ts — Answer speech playback for the web client.
 *
 * Mirrors app.py semantics:
 *   - every assistant answer gets a 🔊 button (server Edge-TTS, same voice
 *     ar-SA-HamedNeural and same markdown cleaning as Streamlit),
 *   - if the query itself came from the microphone the answer auto-plays.
 *
 * A browser speechSynthesis fallback covers the case where the server TTS
 * endpoint is unreachable or the browser blocks autoplay.
 */

import { tokens } from './api'

let activeAudio: HTMLAudioElement | null = null

export function stopActiveSpeech() {
  try {
    activeAudio?.pause()
  } catch { /* ignore */ }
  activeAudio = null
  try {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
  } catch { /* ignore */ }
}

export function registerActiveAudio(el: HTMLAudioElement) {
  if (activeAudio && activeAudio !== el) {
    try { activeAudio.pause() } catch { /* ignore */ }
  }
  activeAudio = el
  try {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
  } catch { /* ignore */ }
}

/** Lightweight markdown/emoji strip for the browser fallback voice. */
export function cleanForBrowserSpeech(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_`#>]+/g, ' ')
    .replace(/-\n/g, ' ')
    .replace(/\n+/g, '. ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 4000)
}

async function refreshAccessToken(): Promise<boolean> {
  try {
    const r = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokens.refresh }),
    })
    if (!r.ok) return false
    const data = await r.json()
    tokens.set(data.access_token, data.refresh_token)
    return true
  } catch {
    return false
  }
}

/** POST /api/voice/speak → object URL of the MP3. Throws Error (Arabic). */
export async function fetchAnswerSpeechUrl(text: string): Promise<string> {
  const body = JSON.stringify({ text: text.slice(0, 4000) })
  const attempt = () =>
    fetch('/api/voice/speak', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(tokens.access ? { Authorization: `Bearer ${tokens.access}` } : {}),
      },
      body,
    })

  let res = await attempt()
  if (res.status === 401 && tokens.refresh && (await refreshAccessToken())) {
    res = await attempt()
  }
  if (!res.ok) {
    let message = `خطأ ${res.status}`
    try {
      const j = await res.json()
      message = j?.error?.message || message
    } catch { /* binary error — keep generic */ }
    throw new Error(message)
  }
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/** Browser-native fallback (no network). Calls onEnd when utterance ends. */
export function speakWithBrowser(text: string, onEnd?: () => void): void {
  if (!('speechSynthesis' in window)) {
    throw new Error('المتصفح لا يدعم النطق التلقائي.')
  }
  stopActiveSpeech()
  const clean = cleanForBrowserSpeech(text)
  if (!clean) throw new Error('لا يوجد نص صالح للنطق.')
  const utter = new SpeechSynthesisUtterance(clean)
  utter.lang = 'ar-SA'
  utter.rate = 1
  utter.pitch = 1
  if (onEnd) {
    utter.onend = onEnd
    utter.onerror = onEnd
  }
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(utter)
}
