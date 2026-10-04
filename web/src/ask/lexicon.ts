// Ask Locus vocabulary: words people use for each question type, EN and ES.
// UI vocabulary only, never law: no thresholds, citations, dates, statute numbers, dollar
// amounts or rule names. Entries are matched after normalisation (lowercase, accents
// stripped). A word of 4+ letters also matches longer words that start with it
// ("evict" matches "evicted", "eviction"); shorter words must match exactly.
import type { Category } from '../api/types'
import type { AskIntentKind } from './types'

export const CATEGORY_WORDS: Record<Category, string[]> = {
  rent_increase_limits: [
    // en
    'rent increase', 'increas', 'raise', 'raising', 'hike', 'go up', 'goes up', 'going up',
    'cap', 'rent cap', 'rent control', 'rent stabiliz', 'stabiliz', 'inflation', 'cpi',
    'how much more', 'rent go up',
    // es
    'aumento', 'aumentar', 'aumentan', 'subir', 'suben', 'sube', 'subo', 'subida', 'suba',
    'incremento', 'tope', 'control de rentas', 'control de alquiler', 'inflacion', 'alza',
  ],
  just_cause_eviction: [
    // en
    'evict', 'kick out', 'kicked out', 'thrown out', 'throw out', 'just cause', 'good cause',
    'end a tenancy', 'end my tenancy', 'end the tenancy', 'end my lease', 'end the lease',
    'terminate', 'termination', 'non renewal', 'nonrenewal', 'renew', 'notice to quit',
    'move out', 'without a reason',
    // es
    'desaloj', 'desahucio', 'echar', 'echan', 'causa justa', 'justa causa', 'terminar',
    'renovar', 'renovacion', 'sin motivo', 'sin un motivo',
  ],
  security_deposits: [
    // en
    'deposit', 'security deposit', 'move in', 'refund', 'get it back', 'last month',
    'withhold', 'damage',
    // es
    'deposito', 'fianza', 'garantia', 'devolver', 'devuelven', 'devolucion', 'reembolso',
  ],
  application_screening_fees: [
    // en
    'application fee', 'screening fee', 'apply fee', 'fee', 'fees', 'charge', 'to apply',
    'application', 'applying', 'processing fee',
    // es
    'cuota', 'cuotas', 'tarifa', 'cargo', 'cobrar', 'cobran', 'solicitud', 'solicitar',
    'por solicitar', 'costo de solicitud',
  ],
  screening_restrictions: [
    // en
    'background check', 'background', 'credit', 'credit check', 'credit score', 'criminal',
    'criminal record', 'conviction', 'arrest', 'source of income', 'income source', 'voucher',
    'housing voucher', 'section 8', 'screen', 'discriminat', 'tenant history', 'look at',
    // es
    'antecedentes', 'historial crediticio', 'penales', 'record criminal', 'fuente de ingresos',
    'vale', 'vales', 'cupon', 'evaluar', 'evaluacion', 'discrimina', 'revisar',
  ],
  algorithmic_rent_setting: [
    // en
    'algorithm', 'software', 'realpage', 'pricing tool', 'pricing software', 'revenue management',
    'ai', 'artificial intelligence', 'automated', 'computer', 'rent setting', 'price fixing',
    'pricing',
    // es
    'algoritmo', 'programa', 'inteligencia artificial', 'herramienta de precios', 'automatizado',
    'fijar precios', 'fijar mi alquiler',
  ],
}

type NonCategoryIntent = Exclude<AskIntentKind, 'category' | 'no_match'>

export const INTENT_WORDS: Record<NonCategoryIntent, string[]> = {
  why_unknown: [
    // en
    'unknown', 'missing', 'why', 'why unknown', 'depends', 'depend on', 'not sure', 'uncertain',
    'what facts', 'which facts', 'unclear',
    // es
    'desconocid', 'falta', 'faltan', 'faltante', 'por que', 'depende', 'incierto', 'que datos',
    'no se sabe',
  ],
  upcoming: [
    // en
    'next year', 'future', 'pending', 'bill', 'bills', 'proposed', 'proposal', 'chang', 'soon',
    'upcoming', 'coming', 'new law', 'new laws', 'take effect', 'takes effect', 'start later',
    'starts later', 'later', 'what changes',
    // es
    'proximo ano', 'el ano que viene', 'futuro', 'pendiente', 'proyecto de ley', 'propuesta',
    'propuesto', 'cambi', 'pronto', 'nueva ley', 'nuevas leyes', 'entra en vigor', 'despues',
  ],
  jurisdiction: [
    // en
    'city', 'town', 'jurisdiction', 'which laws', 'which law', 'which city', 'what city',
    'municipality', 'state', 'local', 'which state', 'where is',
    // es
    'ciudad', 'municipio', 'jurisdiccion', 'que leyes', 'estado', 'que ciudad', 'que estado',
  ],
  conflict: [
    // en
    'conflict', 'disagree', 'contradict', 'clash', 'inconsistent', 'differ',
    // es
    'conflicto', 'contradic', 'desacuerdo', 'en desacuerdo', 'chocan',
  ],
  overview: [
    // en
    'overview', 'summary', 'summari', 'what applies', 'applies here', 'apply here', 'everything',
    'all rules', 'all laws', 'all the rules', 'tell me about', 'my rights', 'rights',
    'my obligations', 'obligations',
    // es
    'resumen', 'resumir', 'resume', 'que aplica', 'aplica aqui', 'todo', 'todas las leyes',
    'derechos', 'mis derechos', 'obligaciones',
  ],
}

/**
 * Ranking hints: when a question asks about an aspect ("how much", "when"), rows whose
 * title or key_value contains one of the matching row words rank higher. Vocabulary only.
 */
export const ASPECTS: Array<{ question: string[]; row: string[] }> = [
  {
    question: ['how much', 'how big', 'how large', 'how high', 'maximum', 'max', 'limit', 'cap', 'most',
      'cuanto', 'cuanta', 'que tan grande', 'maximo', 'limite', 'tope'],
    row: ['maximum', 'max', 'limit', 'cap', 'amount', 'exceed', 'ceiling', 'maximo', 'limite', 'tope', 'monto'],
  },
  {
    question: ['when', 'how long', 'how soon', 'deadline', 'cuando', 'plazo'],
    row: ['return', 'deadline', 'within', 'timing', 'time', 'days', 'plazo', 'devolucion'],
  },
  {
    question: ['back', 'return', 'refund', 'devolver', 'devuelven', 'reembolso'],
    row: ['return', 'refund', 'devolucion', 'reembolso'],
  },
  {
    question: ['penalty', 'penalties', 'fine', 'punish', 'multa', 'sancion'],
    row: ['penalty', 'penalties', 'damages', 'fine', 'multa', 'sancion'],
  },
  {
    question: ['notice', 'warning', 'aviso', 'notificacion'],
    row: ['notice', 'notification', 'aviso', 'notificacion'],
  },
  {
    question: ['reason', 'cause', 'why', 'motivo', 'causa'],
    row: ['cause', 'reason', 'grounds', 'causa', 'motivo'],
  },
]

/** Words ignored when comparing a question with a row title. */
export const STOPWORDS = new Set([
  'the', 'and', 'can', 'could', 'would', 'should', 'does', 'what', 'when', 'where', 'which', 'with',
  'this', 'that', 'there', 'their', 'they', 'them', 'have', 'from', 'about', 'into', 'your', 'mine',
  'much', 'many', 'more', 'some', 'here', 'will', 'rule', 'rules', 'laws', 'apply', 'applies',
  'building', 'landlord', 'tenant', 'owner', 'rent', 'rents',
  'que', 'cual', 'como', 'para', 'por', 'una', 'unos', 'unas', 'los', 'las', 'del', 'este', 'esta',
  'puede', 'pueden', 'aqui', 'reglas', 'leyes', 'alquiler', 'renta', 'edificio', 'arrendador',
  'inquilino', 'propietario', 'cuando', 'donde',
])
