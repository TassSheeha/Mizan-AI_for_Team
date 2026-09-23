"""
assistant.py — Central RAG Orchestrator for Mizan AI.

Integrates:
  - Hybrid Retriever (ChromaDB Vector + Arabic BM25 + RRF Fusion)
  - Legal Answer Generator (LLM with strict grounding and citation)

Features:
  - Greeting / chitchat detection (bypasses RAG)
  - Follow-up query reformulation using conversation history
  - Multi-criteria relevance gate (dense score + BM25 + weighted confidence)
  - Streaming support
  - Metadata filtering (doc_id, doc_type, year, specialization)
  - Extensible to any legal source
"""

import os
import re

from mizan.retriever import LibyanLawRetriever
from mizan.generator import LegalAnswerGenerator
from mizan.bm25_search import tokenize_arabic

# ─── Relevance thresholds ─────────────────────────────────────────────────────
# Calibrated on measured behavior of this corpus with multilingual-e5-small:
#   legit legal questions:      top dense 0.842 - 0.899
#   off-topic legal-sounding:   top dense 0.766 - 0.841  (salaries, generic law)
#   non-legal questions:        top dense 0.760 - 0.785
# The dense score is therefore the single discriminating signal; BM25 agreement
# is too promiscuous on this corpus to serve as a rescue criterion (any
# multi-word Arabic query scores >= 5 on some chunk via shared stopwords).
DENSE_HIGH_THRESHOLD     = 0.83
DENSE_MEDIUM_THRESHOLD   = 0.75   # informational (metrics only)
DENSE_LEGAL_TERM_THRESHOLD = 0.83 # informational (kept for compatibility)
BM25_STRONG_THRESHOLD    = 5.0
CONFIDENCE_THRESHOLD     = 0.84   # informational (metrics only)

# ─── Greeting / Chitchat detection ────────────────────────────────────────────
# Gate 1 – the message must contain one of these specific greeting PHRASES.
# Gate 2 – the message must NOT contain any legal keyword.
# Both gates must pass for a message to be classified as a greeting.

_GREETING_PHRASES = [
    "السلام عليكم", "عليكم السلام",
    "أهلا وسهلا", "أهلاً وسهلاً", "أهلا", "أهلاً", "اهلا",
    "هلا", "مرحبا", "مرحباً", "مرحبتين",
    "صباح الخير", "صباح النور", "مساء الخير", "مساء النور",
    "كيف حالك", "كيف الحال", "كيفك",
    "شكرا", "شكراً", "شكرا جزيلا", "شكراً جزيلاً",
    "وداعا", "وداعاً", "مع السلامة", "تصبح على خير", "تمسى على خير",
    "hi", "hello", "thanks", "thank you", "bye", "good morning",
]

# If ANY of these words appear → it is a legal question, not a greeting
_LEGAL_KEYWORDS = [
    "قانون", "مادة", "ماد", "عقد", "شركة", "ضريبة", "ضرائب",
    "عمل", "راتب", "أجر", "اجر", "إجازة", "اجازة", "إجازات", "اجازات",
    "موظف", "عامل", "صاحب العمل", "فصل", "إنهاء", "انهاء",
    "تعويض", "غرامة", "جزاء", "عقوبة",
    "محكمة", "حق", "حقوق", "التزام", "واجب", "مصرف", "بنك",
    "ربح", "خسارة", "نظام", "لائحة", "قرار", "تأسيس", "شريك",
    "مكافأة", "تأمين", "تامين", "ميراث", "وصية", "عقار", "بيع", "إيجار",
    "رهن", "كفالة", "وكالة", "ضمان", "تجاري", "مدني", "مالي",
    "ربوي", "غسل", "أموال", "اموال", "أوراق مالية", "سوق", "نسبة", "رأس المال",
    "ملكية", "حكم", "نزاع", "اتفاق", "بند", "فقرة", "باب",
    "تسجيل", "ترخيص", "إفلاس", "افلاس", "تصفية", "دعوى", "شهادة", "توثيق",
    "تقاعد", "معاش", "طفل", "حقوق الطفل",
]


def _is_greeting(query: str) -> bool:
    """
    Returns True ONLY if:
      1. The query contains a known greeting phrase, AND
      2. The query contains NO legal keyword.
    """
    q = query.strip().lower()

    # Gate 2 first (cheaper) — any legal keyword disqualifies immediately
    if any(kw in q for kw in _LEGAL_KEYWORDS):
        return False

    # Gate 1 — must match a specific greeting phrase
    return any(phrase in q for phrase in _GREETING_PHRASES)


def _format_greeting_response(query: str) -> str:
    """
    Returns an appropriate reply matching the user's greeting,
    then invites them to ask their legal question.
    """
    q = query.strip().lower()
    if "سلام" in q and "عليكم" in q or "السلام عليكم" in q:
        reply = "وعليكم السلام ورحمة الله وبركاته! 😊"
    elif "صباح" in q:
        reply = "صباح النور والسرور! ☀️"
    elif "مساء" in q:
        reply = "مساء النور والسرور! 🌙"
    elif any(w in q for w in ["شكر", "thanks", "thank"]):
        reply = "العفو، على الرحب والسعة دائماً! 😊"
    elif any(w in q for w in ["وداع", "سلامة", "bye"]) or "مع السلامة" in q:
        reply = "في أمان الله وحفظه! مع السلامة. 👋"
    else:
        # Default for أهلا, مرحبا, هلا, hi, hello, etc.
        reply = "أهلاً وسهلاً بك! 😊"

    return (
        f"{reply}\n\n"
        "أنا **الميزان — المستشار القانوني الليبي الذكي**، جاهز لمساعدتك في أي استفسار حول القوانين والتشريعات الليبية.\n\n"
        "هل لديك سؤال أو استفسار قانوني تودّ طرحه؟ 🏛️"
    )


# ─── No-answer response ────────────────────────────────────────────────────────
NO_ANSWER_RESPONSE = (
    "أهلاً بك! يسعدني دائماً مساعدتك.\n\n"
    "**لا أعرف الإجابة الدقيقة عن هذا السؤال، إذ لا توجد مواد قانونية كافية أو مرتبطة به في قاعدة المعرفة الحالية.**\n\n"
    "💡 **أسباب محتملة:**\n"
    "- الموضوع المطروح قد لا يكون منظماً في أي من التشريعات المتاحة (موضوعات عامة، أسعار، سياسة، إلخ).\n"
    "- قد يتبع تشريعاً ليبياً لم يُضف بعد إلى قاعدة المعرفة.\n"
    "- يمكنك إعادة صياغة السؤال بمصطلحات قانونية أكثر تحديداً للحصول على نتيجة أفضل.\n\n"
    "📚 **التشريعات المتاحة حالياً:**\n"
    "- قانون علاقات العمل رقم (12) لسنة 2010 ولائحته التنفيذية (قرار 888 لسنة 2023)\n"
    "- القانون المدني الليبي\n"
    "- دليل حقوق الطفل في ليبيا\n"
    "- قانون المصارف والصيرفة الإسلامية رقم (46) لسنة 2012\n"
    "- قانون ضرائب الدخل رقم (7) لسنة 2010 ولائحته التنفيذية (قرار 592 لسنة 2010)\n"
    "- قانون منع المعاملات الربوية رقم (1) لسنة 2013\n"
    "- قانون مكافحة غسل الأموال رقم (2) لسنة 2005\n"
    "- قانون النظام المالي للدولة\n"
    "- النظام الأساسي لسوق الأوراق المالية الليبي (2006)\n"
    "- قانون النشاط التجاري رقم (23) لسنة 2010 (النص الكامل)\n\n"
    "⚖️ تنويه: المعلومات المقدمة استرشادية مبنية على التشريعات الليبية المتاحة في قاعدة المعرفة."
)

# ─── Out-of-scope response ──────────────────────────────────────────────────────
OUT_OF_SCOPE_RESPONSE = (
    "أهلاً بك! يسعدني دائماً مساعدتك.\n\n"
    "**هذا السؤال خارج نطاق عملي كمستشار قانوني.** أنا **الميزان — المستشار القانوني الليبي الذكي**،"
    " متخصص في التشريعات والقوانين الليبية فقط، ولا أستطيع الإفادة في الموضوعات العامة "
    "(مدارس وجامعات، مطاعم وأسواق، رياضة، طقس، سياسة وأخبار، برامج وتطبيقات... إلخ).\n\n"
    "💡 جرّب أن تسأل سؤالاً قانونياً ليبياً، مثلاً:\n"
    "- «ما هي أحكام الإجازة السنوية؟»\n"
    "- «شن حقوقي إذا فصلوني تعسفياً من العمل؟»\n"
    "- «ما هي شروط تأسيس شركة تجارية؟»\n\n"
    "⚖️ تنويه: المعلومات المقدمة استرشادية مبنية على التشريعات الليبية المتاحة في قاعدة المعرفة."
)

# ─── Legal terms (used by the relevance gate) ──────────────────────────────────
LEGAL_TERMS = {
    # Labor
    "عمل", "أجر", "اجر", "عقد", "عقود", "فصل", "إجازة", "اجازه", "خدمة", "وظيفة",
    "وظائف", "موظف", "عامل", "صاحب", "إنهاء", "انهاء", "استقالة", "تجربة", "ساعات",
    "تعويض", "مرتب", "راتب", "رواتب", "جزاء", "تأديب", "تاديب",
    "تعيين", "اختبار", "شروط", "دخل",
    # Pension / Social Security
    "تقاعد", "معاش", "ضمان", "اجتماعي", "شيخوخة", "عجز", "ورثة", "تأمين", "تامين",
    # Tax
    "ضريبة", "ضرائب", "جباية", "تهرب", "إقرار", "وعاء", "رسم", "معدل",
    # Civil / Commercial / General
    "مادة", "قانون", "لائحة", "قرار", "حقوق", "واجبات",
    "محكمة", "قضية", "دعوى", "حكم", "استئناف", "نقض",
    "شركة", "تأسيس", "تجاري", "مدني", "مصرف", "مصارف", "بنك", "ربوي", "غسل",
    "أوراق", "سوق", "طفل", "ميراث", "وصية", "عقار", "بيع", "إيجار", "رهن",
    # Scope-gate additions (institutional / procedural / general legal)
    "قطاع", "وزارة", "هيئة", "محكمة", "قاض", "محام", "عدالة", "عدل",
    "تشريع", "قانوني", "نافذ", "سجل", "شهادة", "إقامة", "شهود",
}

# Legal terms too generic to vouch for the legal-ness of a question on their
# own ('سوق' appears in 'أفضل هاتف في السوق'). Used only by the off-topic rule.
_WEAK_LEGAL_TERMS = {"سوق", "حق", "حقوق", "نظام", "نسبة", "حكم", "قانون", "قانوني", "باب"}

# Everyday-life topics that mark a question as out-of-scope when no STRONG
# legal term accompanies them (schools, phones, weather, sports...).
_OFF_TOPIC_TERMS = {
    "هاتف", "جوال", "تلفون", "موبايل", "مدرسه", "مدارس", "جامعه", "جامعات",
    "فندق", "فنادق", "مطعم", "مطاعم", "سياره", "سيارات", "طقس", "نكته", "نكت",
    "كوره", "كره", "مباراه", "مباريات", "طبخ", "حلويات", "افلام", "اغاني",
    "العاب", "سفر", "شوبينج", "موضه",
}


def _has_explicit_article(query: str) -> bool:
    return bool(re.search(r"ماد[ةه]\s*\d+", query))


# Light Arabic suffix stripper: handles regular plurals and attached pronouns
# so 'اجازات' matches 'اجازه', 'ضريبيه' matches 'ضريبه', etc. Single-character
# suffixes only strip when a stem of >= 3 letters remains.
_STEM_SUFFIXES = ("ات", "ون", "ين", "يه", "ية", "ها", "هم", "كم", "هن", "ه", "ي")


def _light_stem(t: str) -> str:
    for suf in _STEM_SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[: -len(suf)]
    return t


# Detached-clitic stripper: removes attached conjunctions/prepositions and the
# definite article (و/ف/ب/ك/ل + ال) so 'بتعسف' ~ 'تعسف' and 'الحق' ~ 'حق'.
_CLITICS = ("وال", "بال", "كال", "فال", "لل", "ال", "و", "ف", "ب", "ك", "ل")


def _strip_clitics(t: str) -> str:
    while True:
        for c in _CLITICS:
            if t.startswith(c) and len(t) - len(c) >= 3:
                t = t[len(c):]
                break
        else:
            return t


# Lenient second stem: attached-pronoun suffixes may leave a 2-letter root
# ('حقي' -> 'حق', 'حقوقه' -> 'حقوق'), never a 1-letter fragment.
_PRONOUN_SUFFIXES = ("ية", "يه", "ها", "هم", "كم", "هن", "ي", "ه", "ه")


def _light_stem_pronoun(t: str) -> str:
    for suf in _PRONOUN_SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 2:
            return t[: -len(suf)]
    return t


def _token_variants(t: str) -> set:
    """All comparable forms of a token: raw, stem-clitic-stripped, stem.

    Also includes the lenient definite-article strip ('الحق' -> 'حق', allowed
    down to a 2-letter remainder) so 'حقي' ~ 'حق' ~ 'الحق' all compare equal.
    """
    out = {t}
    base = _strip_clitics(t)
    out.add(base)
    if base.startswith("ال") and len(base) >= 4:
        out.add(base[2:])
    out.add(_light_stem(base))
    out.add(_light_stem(t))
    out.add(_light_stem_pronoun(base))
    out.add(_light_stem_pronoun(t))
    return {v for v in out if v}


def _tokens_related(tok: str, doc_tokens: set) -> bool:
    """Loose Arabic stem match: handles article prefix + simple inflection."""
    tok_vars = _token_variants(tok)
    for d in doc_tokens:
        doc_vars = _token_variants(d)
        if tok_vars & doc_vars:
            return True
        for tv in tok_vars:
            for dv in doc_vars:
                if len(tv) >= 3 and dv.startswith(tv):
                    return True
                if len(dv) >= 3 and tv.startswith(dv):
                    return True
    return False


def _tokenize_lexicon(terms: set) -> set:
    try:
        return set(tokenize_arabic(" ".join(terms)))
    except Exception:
        return {t for t in " ".join(terms).split() if len(t) > 1}


_NORM_LEGAL_TERMS = None
_NORM_STRONG_LEGAL_TERMS = None
_NORM_OFF_TOPIC_TERMS = None


def _lexicons():
    """Lazily normalized lexicons (normalized once per process)."""
    global _NORM_LEGAL_TERMS, _NORM_STRONG_LEGAL_TERMS, _NORM_OFF_TOPIC_TERMS
    if _NORM_LEGAL_TERMS is None:
        _NORM_LEGAL_TERMS = _tokenize_lexicon(LEGAL_TERMS)
        weak = _tokenize_lexicon(_WEAK_LEGAL_TERMS)
        _NORM_STRONG_LEGAL_TERMS = _NORM_LEGAL_TERMS - weak
        _NORM_OFF_TOPIC_TERMS = _tokenize_lexicon(_OFF_TOPIC_TERMS)
    return (
        _NORM_LEGAL_TERMS,
        _NORM_STRONG_LEGAL_TERMS,
        _NORM_OFF_TOPIC_TERMS,
    )


def _lexicon_hit(core: str, lexicon: set) -> bool:
    """Exact, stemmed, or (substantial) prefix match of a core token vs lexicon."""
    if core in lexicon:
        return True
    if _light_stem(core) in lexicon:
        return True
    for term in lexicon:
        if len(core) >= 4 and len(term) >= 4 and (
            core.startswith(term) or term.startswith(core)
        ):
            return True
        # stem-level prefix: 'تعويضات' stem 'تعوض'? keep prefix on raw forms
        st = _light_stem(core)
        sl = _light_stem(term)
        if len(st) >= 4 and len(sl) >= 4 and (st.startswith(sl) or sl.startswith(st)):
            return True
    return False


def _has_legal_term(query: str, strong_only: bool = False) -> bool:
    _, strong_terms, _ = _lexicons()
    lexicon = strong_terms if strong_only else _lexicons()[0]
    try:
        tokens = set(tokenize_arabic(query))
    except Exception:
        tokens = set(query.split())
    for t in tokens:
        core = _ar_core(t)
        if _lexicon_hit(core, lexicon):
            return True
    return False


def _has_off_topic_without_legal(query: str) -> bool:
    """
    True when the question names an everyday-life topic (phone, school...)
    while carrying no STRONG legal term — e.g. 'أفضل هاتف في السوق'.
    'سوق' alone does not rescue it; 'بيع سيارة' is still legal (بيع is strong).
    """
    _, strong_terms, off_terms = _lexicons()
    try:
        tokens = set(tokenize_arabic(query))
    except Exception:
        tokens = set(query.split())
    has_off = False
    for t in tokens:
        core = _ar_core(t)
        if _lexicon_hit(core, off_terms):
            has_off = True
            break
    if not has_off:
        return False
    for t in tokens:
        core = _ar_core(t)
        if _lexicon_hit(core, strong_terms):
            return False
    return True


# ─── Domain-scope detection & lexical topic verification ──────────────────────
# Function words / question words — carry no legal "topic" signal.
_STOPWORDS = {
    "ما", "ماذا", "من", "في", "على", "عن", "الى", "او", "و", "ثم", "ايضا",
    "كذلك", "هو", "هي", "ان", "لا", "لن", "قد", "لو", "اذا", "بل", "غير",
    "نفس", "هذا", "هذه", "ذلك", "تلك", "الذي", "التي", "الذين", "اما", "ام",
    "لكن", "حتى", "فقط", "بعض", "كل", "لدي", "عند", "عندي", "مع", "يكون",
    "تكون", "يوجد", "بعد", "قبل", "بين", "هل", "كيف", "لماذا", "متى", "كم",
    "شن", "شنو", "قداش", "وين", "علاش", "هلا", "بش", "اي", "نبي", "اريد",
    "اعرف", "اخبرني", "رجاء", "برجاء", "شكرا", "شكراً", "هل", "وهل",
    # Quantity / vague words
    "اكثر", "اقل", "ابدا", "جدا",
    # Meta tokens injected by reformulation prompts ("في سياق: ...")
    "سياق", "سالت", "سابقا", "سابق", "سالف",
}

_TOKEN_TRIM = "؟?.,:;«»()[]\"'-،؛"


def _ar_core(t: str) -> str:
    """
    Iteratively strip Arabic prepositional compounds (وال/بال/كال/فال/لل) and
    the definite article (ال) from a word, plus surrounding punctuation.
    Single-letter conjunctions (و/ب) are NOT stripped: they would break
    words genuinely starting with them (وظيفة, وعاء, بنك, بيع...).
    Attached junk forms (وماذا, وسبق) simply never match doc content, which
    only lowers the denominator safely.
    """
    t = t.strip(_TOKEN_TRIM)
    while len(t) > 3:
        for p in ("وال", "بال", "كال", "فال", "لل", "ال"):
            if t.startswith(p) and len(t) > len(p) + 2:
                t = t[len(p):]
                break
        else:
            return t
    return t


def _is_legal_query(query: str) -> bool:
    """
    Scope gate: is the question a legal-domain question at all?
    True if it contains an explicit article reference, or any lexicon word —
    unless an everyday-life topic word dominates it (phone/school/weather).
    Non-legal questions are refused before any retrieval happens.
    """
    if _has_explicit_article(query):
        return True
    if _has_off_topic_without_legal(query):
        return False
    return bool(_has_legal_term(query))


def _content_tokens(text: str) -> set:
    """Normalized contentful words (drop article + stopwords)."""
    try:
        tokens = tokenize_arabic(text)
    except Exception:
        tokens = text.split()
    out = set()
    for t in tokens:
        core = _ar_core(t)
        # 'وماذا'/'وكيف' carry no more topic signal than 'ماذا'/'كيف'
        unwrapped = t[1:] if t.startswith("و") and len(t) > 2 else t
        if (
            t in _STOPWORDS
            or unwrapped in _STOPWORDS
            or core in _STOPWORDS
        ):
            continue
        if len(core) < 3:
            continue
        out.add(core)
    return out


# Corpus document-frequency cache: (df_counter, total_chunks) per corpus.
_CORPUS_DF_CACHE: dict[int, tuple] = {}


def _compute_corpus_df(bm25_searcher) -> tuple | None:
    corpus = getattr(bm25_searcher, "corpus_tokens", None)
    if not corpus:
        return None
    key = id(bm25_searcher)
    cached = _CORPUS_DF_CACHE.get(key)
    if cached is not None:
        return cached
    from collections import Counter
    df = Counter()
    for doc in corpus:
        df.update(set(doc))
    result = (df, len(corpus))
    _CORPUS_DF_CACHE[key] = result
    return result


# Words that name no legal topic by themselves: country/nationality names and
# generic adjectives ('ليبيا', 'خاص' as in 'قطاع خاص' or 'الإجازات الخاصة').
# Filtered from the topic signal on BOTH the question and the chunk side.
_TOPIC_GENERIC = {
    "ليبيا", "الليبي", "الليبيه", "ليبي", "ليبيه", "جماهيريه", "عظمي", "عظمي",
    "عام", "عامه", "خاص", "خاصه",
}

_COMMON_RATIO = 0.15  # appears in >15% of chunks -> corpus-ubiquitous


def _topic_tokens(text: str, corpus_df: tuple | None) -> set:
    """
    Content words that carry actual topic signal for a text: content tokens
    minus corpus-ubiquitous words minus generic words (country names etc.).
    """
    q_tokens = _content_tokens(text)
    df = None
    n_chunks_total = 0
    if corpus_df:
        df, n_chunks_total = corpus_df

    def _is_common(w: str) -> bool:
        return df is not None and df.get(w, 0) / n_chunks_total > _COMMON_RATIO

    return {w for w in q_tokens if not _is_common(w) and w not in _TOPIC_GENERIC}


def _passes_topic_match(
    retrieval_query: str,
    sources: list[dict],
    corpus_df: tuple | None = None,
) -> bool:
    """
    Second verification gate (lexical): after the score gate accepts a chunk,
    confirm the chunk actually SHARES contentful words with the question.
    This blocks authoritative-looking answers built from legally-plausible but
    topically-unrelated articles (e.g. a follow-up about aspects the knowledge
    base does not cover). Score-based gates alone miss these.

    Words that appear in a large share of the corpus (e.g. عمل, قانون) cannot
    validate overlap on their own -- otherwise every chunk would 'overlap' with
    every question. Bypassed for explicit article lookups (e.g. 'المادة 34').
    """
    if not sources:
        return False
    if _has_explicit_article(retrieval_query):
        return True

    q_topic = _topic_tokens(retrieval_query, corpus_df)
    if not q_topic:
        return True  # question is fully generic; trust the score gate

    df = None
    n_chunks_total = 0
    if corpus_df:
        df, n_chunks_total = corpus_df

    def _is_common(w: str) -> bool:
        return df is not None and df.get(w, 0) / n_chunks_total > _COMMON_RATIO

    for s in sources:
        doc_tokens = _content_tokens(s.get("text") or "")
        if not doc_tokens:
            continue
        doc_topic = {
            w for w in doc_tokens
            if not _is_common(w) and w not in _TOPIC_GENERIC
        }
        matched = [w for w in q_topic if _tokens_related(w, doc_topic)]
        ratio = len(matched) / len(q_topic)
        # Accept ONLY dominant overlap: more than half of the question's topic
        # roots appear in the chunk (prevents legally-plausible junk matches
        # like عمل/عامل/امر from validating unrelated articles).
        if len(matched) >= 2 and ratio >= 0.55:
            return True
        if len(matched) >= 1 and len(q_topic) <= 2:
            return True
        # High-confidence semantic escape: a near-paraphrase dense match
        # (>= 0.87) with at least one topic word present. Covers conjugated /
        # derived forms the light stemmer cannot relate (يؤجلها vs تأجيلها,
        # تنقطع vs قطعها) — an off-topic chunk never reaches this dense score.
        dense = s.get("dense_score") or 0
        if len(matched) >= 1 and dense >= 0.87:
            return True
    return False


# ─── Ambiguous-question detection ──────────────────────────────────────────────
AMBIGUOUS_RESPONSE = (
    "سؤالك عام ويحتاج إلى توضيح أكثر حتى أستطيع مساعدتك بدقة. 🤔\n\n"
    "**حدد من فضلك الموضوع القانوني الذي تريد الاستفسار عنه**، مثلاً:\n"
    "- «شن حقوقي في الإجازة السنوية؟»\n"
    "- «شن شروط تأسيس شركة تجارية؟»\n"
    "- «ما هو التعويض عند الفصل التعسفي؟»\n\n"
    "⚖️ تنويه: المعلومات المقدمة استرشادية مبنية على التشريعات الليبية المتاحة في قاعدة المعرفة."
)


def _is_ambiguous(query: str, corpus_df: tuple | None) -> bool:
    """
    A question with NO topic signal at all ('شن القانون؟', 'وش الحكم؟')
    cannot be answered faithfully: any retrieval would be arbitrary.
    Explicit article lookups ('المادة 34') are never ambiguous.
    """
    if _has_explicit_article(query):
        return False
    return not _topic_tokens(query, corpus_df)


def _compute_confidence(sources: list[dict]) -> float:
    """
    Weighted average of DENSE cosine similarities (rank-weighted).
    Uses dense_score (0..1 semantic similarity), NOT the RRF score,
    so the value is interpretable and comparable to the thresholds.
    """
    if not sources:
        return 0.0
    weights = [1.0 / (i + 1) for i in range(len(sources))]
    total_weight = sum(weights)
    weighted = sum(w * (s.get("dense_score") or 0) for w, s in zip(weights, sources))
    return round(weighted / total_weight, 3)


def _is_relevant(query: str, sources: list[dict], mode: str) -> bool:
    """
    Score gate. Returns True if the retrieved evidence is strong enough to
    attempt an answer:
    1. Explicit article query (e.g., 'المادة 15') is always accepted.
    2. Hybrid/dense: best dense cosine >= DENSE_HIGH_THRESHOLD (0.83).
    3. Pure BM25 mode: best BM25 >= BM25_STRONG_THRESHOLD.
    See the threshold block above for the calibration rationale.
    """
    if not sources:
        return False

    if _has_explicit_article(query):
        return True

    best_dense = max((s.get("dense_score") or 0) for s in sources)
    best_bm25 = max((s.get("bm25_score") or 0) for s in sources)

    if mode == "bm25":
        return best_bm25 >= BM25_STRONG_THRESHOLD

    # 'dense' and 'hybrid' both carry dense scores
    return best_dense >= DENSE_HIGH_THRESHOLD


class MizanAssistant:
    def __init__(
        self,
        provider: str = "auto",
        api_key: str = None,
        model_name: str = None,
        system_prompt: str = None,
        retriever_mode: str = "hybrid",
        dense_weight: float = 1.0,
        bm25_weight: float = 1.0,
    ):
        self.retriever = LibyanLawRetriever(bm25_enabled=True)
        self.generator = LegalAnswerGenerator(
            provider=provider,
            api_key=api_key,
            model_name=model_name,
            system_prompt=system_prompt,
        )
        self.default_mode = retriever_mode
        self.dense_weight = dense_weight
        self.bm25_weight = bm25_weight
        self._corpus_df = None

    def _get_corpus_df(self) -> tuple | None:
        """(doc-freq counter, total chunks) — computed once per session."""
        if self._corpus_df is None:
            searcher = getattr(self.retriever, "bm25_searcher", None)
            if searcher is not None:
                self._corpus_df = _compute_corpus_df(searcher)
        return self._corpus_df

    # ─── Citations ─────────────────────────────────────────────────────────────
    @staticmethod
    def _dedupe_sources(sources: list[dict]) -> list[dict]:
        """
        One source per (article, document): long articles arrive as several
        OCR windows, and generation + citations must see the SAME deduplicated
        set so every quoted figure stays traceable to a cited text.
        """
        deduped, seen = [], set()
        for s in sources:
            key = (str(s.get("article")), s.get("document"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        return deduped

    def _build_citations(self, sources: list[dict]) -> list[dict]:
        citations = []
        for s in sources:
            citations.append({
                "article": s.get("article"),
                "page": s.get("page"),
                "section": s.get("section"),
                "chapter": s.get("chapter"),
                "document": s.get("document"),
                "doc_id": s.get("doc_id"),
                "doc_type": s.get("doc_type"),
                "year": s.get("year"),
                "score": s.get("score"),
                "rrf_score": s.get("rrf_score"),
                "dense_score": s.get("dense_score"),
                "bm25_score": s.get("bm25_score"),
                "dense_rank": s.get("dense_rank"),
                "bm25_rank": s.get("bm25_rank"),
                "text": (s.get("text") or "")[:600],
            })
        return citations

    # ─── Retrieval only (for streaming UIs) ────────────────────────────────────
    def retrieve_only(
        self,
        query: str,
        top_k: int = 3,
        mode: str = None,
        filters: dict = None,
        chat_history: list[dict] = None,
    ) -> tuple[list[dict], bool, str]:
        """
        Reformulate (if follow-up) then retrieve.
        Returns (sources, is_relevant_and_verified, retrieval_query).
        """
        search_mode = mode or self.default_mode
        retrieval_query = self.generator.contextualize_query(query, chat_history)
        sources = self.retriever.search(
            query=retrieval_query,
            top_k=top_k,
            mode=search_mode,
            dense_weight=self.dense_weight,
            bm25_weight=self.bm25_weight,
            filters=filters,
        )
        sources = self._dedupe_sources(sources)
        relevant = _is_relevant(retrieval_query, sources, search_mode)
        verified = relevant and _passes_topic_match(
            retrieval_query, sources, self._get_corpus_df(),
        )
        return sources, verified, retrieval_query

    # ─── Streaming end-to-end ──────────────────────────────────────────────────
    def ask_stream(self, query: str, top_k: int = 3, mode: str = None,
                   filters: dict = None, chat_history: list[dict] = None) -> dict:
        """
        Prepare the RAG state for a streaming answer.
        Returns a dict:
          {"type": "greeting",  "answer": str}
          {"type": "no_match",  "answer": str, "confidence": 0.0}
          {"type": "answer",    "sources": [...], "citations": [...],
           "confidence": float, "retrieval_query": str,
           "stream": generator-of-tokens}
        After consuming the stream, call finish_stream() to get the cleaned text.
        """
        search_mode = mode or self.default_mode

        if _is_greeting(query):
            return {"type": "greeting", "answer": _format_greeting_response(query)}

        # Scope gate: refuse non-legal questions before any retrieval.
        if not _is_legal_query(query):
            return {
                "type": "no_match",
                "answer": OUT_OF_SCOPE_RESPONSE,
                "confidence": 0.0,
            }

        # Ambiguity gate: questions with no topic signal ('شن القانون؟')
        # would make any retrieval arbitrary — ask for clarification instead.
        if _is_ambiguous(query, self._get_corpus_df()):
            return {
                "type": "no_match",
                "answer": AMBIGUOUS_RESPONSE,
                "confidence": 0.0,
            }

        sources, is_relevant, retrieval_query = self.retrieve_only(
            query=query, top_k=top_k, mode=search_mode,
            filters=filters, chat_history=chat_history,
        )

        if not is_relevant:
            return {
                "type": "no_match",
                "answer": NO_ANSWER_RESPONSE,
                "confidence": 0.0,
            }

        return {
            "type": "answer",
            "sources": sources,
            "citations": self._build_citations(sources),
            "confidence": _compute_confidence(sources),
            "retrieval_query": retrieval_query,
            "stream": self.generator.generate_stream(query, sources, chat_history=chat_history),
        }

    def finish_stream(self, raw_text: str) -> str:
        """Apply anti-repetition cleaning once the stream has been consumed."""
        return self.generator.clean_answer(raw_text)

    # ─── Non-streaming end-to-end ──────────────────────────────────────────────
    def answer_question(
        self,
        query: str,
        top_k: int = 3,
        mode: str = None,
        filters: dict = None,
        chat_history: list[dict] = None,
    ) -> dict:
        """
        End-to-end RAG pipeline (non-streaming):
          1. Greeting / chitchat — bypass RAG entirely.
          2. Reformulate follow-up queries using conversation history (if any).
          3. Retrieve top-k relevant law articles using Hybrid search.
          4. Check relevance scores — return "no information" if below threshold.
          5. Generate cited, grounded legal answer with full conversation context.
        """
        search_mode = mode or self.default_mode

        if _is_greeting(query):
            return {
                "query": query,
                "answer": _format_greeting_response(query),
                "citations": [],
                "provider": self.generator.provider,
                "retriever_mode": search_mode,
                "confidence": 1.0,
                "no_match": False,
            }

        # Scope gate: refuse non-legal questions before any retrieval.
        if not _is_legal_query(query):
            return {
                "query": query,
                "answer": OUT_OF_SCOPE_RESPONSE,
                "citations": [],
                "provider": self.generator.provider,
                "retriever_mode": search_mode,
                "confidence": 0.0,
                "no_match": True,
            }

        # Ambiguity gate: questions with no topic signal ('شن القانون؟')
        # would make any retrieval arbitrary — ask for clarification instead.
        if _is_ambiguous(query, self._get_corpus_df()):
            return {
                "query": query,
                "answer": AMBIGUOUS_RESPONSE,
                "citations": [],
                "provider": self.generator.provider,
                "retriever_mode": search_mode,
                "confidence": 0.0,
                "no_match": True,
            }

        retrieval_query = self.generator.contextualize_query(query, chat_history)

        sources = self.retriever.search(
            query=retrieval_query,
            top_k=top_k,
            mode=search_mode,
            dense_weight=self.dense_weight,
            bm25_weight=self.bm25_weight,
            filters=filters,
        )
        sources = self._dedupe_sources(sources)

        relevant = _is_relevant(retrieval_query, sources, search_mode)
        verified = relevant and _passes_topic_match(
            retrieval_query, sources, self._get_corpus_df(),
        )

        if not verified:
            return {
                "query": query,
                "answer": NO_ANSWER_RESPONSE,
                "citations": [],
                "provider": self.generator.provider,
                "retriever_mode": search_mode,
                "confidence": 0.0,
                "no_match": True,
            }

        answer = self.generator.generate(query, sources, chat_history=chat_history)

        return {
            "query": query,
            "answer": answer,
            "citations": self._build_citations(sources),
            "provider": self.generator.provider,
            "retriever_mode": search_mode,
            "confidence": _compute_confidence(sources),
            "no_match": False,
        }
    def chat(
        self,
        query: str,
        top_k: int = 3,
        mode: str = None,
        filters: dict = None,
        chat_history: list[dict] = None,
        **kwargs,
    ) -> dict:
        """Backwards-compatible alias for answer_question used by UI frontends."""
        return self.answer_question(
            query=query,
            top_k=top_k,
            mode=mode,
            filters=filters,
            chat_history=chat_history,
        )

# Backwards-compatible alias
LibyanLawAssistant = MizanAssistant
