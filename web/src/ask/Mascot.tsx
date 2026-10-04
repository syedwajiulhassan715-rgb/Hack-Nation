// "Loci": the Ask Locus character. An original inline SVG built from the Locus mark (a black
// map pin wearing the state + city layers as a cap), with big eyes, reading glasses and an open
// book. Decorative only (aria-hidden). Motion respects prefers-reduced-motion.
import { useEffect, useState } from 'react'
import { motion, useReducedMotion, type Transition } from 'motion/react'

export type MascotMood = 'idle' | 'thinking' | 'answer' | 'unsure'

interface Props {
  mood: MascotMood
  size?: number
  /** Static pose (no float, no blink): for older replies in the thread. */
  still?: boolean
}

const INK = '#111111'
const PAPER = '#F6F2E9'
const BLUE = '#4F7CFF'
const TEAL = '#2DD4BF'

const PIN = 'M32 3C18.7 3 8 13.4 8 26.4 8 44.2 32 61 32 61s24-16.8 24-34.6C56 13.4 45.3 3 32 3Z'
const centered = { transformBox: 'fill-box', transformOrigin: 'center' } as const

function useBlink(enabled: boolean): boolean {
  const [blink, setBlink] = useState(false)
  useEffect(() => {
    if (!enabled) return
    let t1: ReturnType<typeof setTimeout>
    let t2: ReturnType<typeof setTimeout>
    const loop = () => {
      t1 = setTimeout(
        () => {
          setBlink(true)
          t2 = setTimeout(() => {
            setBlink(false)
            loop()
          }, 140)
        },
        2600 + Math.random() * 2600,
      )
    }
    loop()
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
      setBlink(false)
    }
  }, [enabled])
  return blink
}

export function Mascot({ mood, size = 56, still = false }: Props) {
  const reduce = useReducedMotion() ?? false
  const calm = reduce || still
  const blink = useBlink(!calm && (mood === 'idle' || mood === 'thinking'))
  const instant: Transition = { duration: 0 }

  // Outer group: the idle float (a gentle bob), off when calm.
  const float =
    calm || mood === 'unsure'
      ? { y: 0 }
      : { y: [0, -2.6, 0], transition: { duration: 3.2, repeat: Infinity, ease: 'easeInOut' as const } }

  // Inner group: the pose for each mood.
  const pose = (() => {
    if (mood === 'thinking')
      return calm
        ? { rotate: 0, y: 0, transition: instant }
        : { rotate: [-4, 4, -4], y: 0, transition: { duration: 0.9, repeat: Infinity, ease: 'easeInOut' as const } }
    if (mood === 'answer')
      return calm
        ? { rotate: 0, y: 0, transition: instant }
        : { rotate: 0, y: [0, -7, 0, -2, 0], transition: { duration: 0.65, ease: 'easeOut' as const } }
    if (mood === 'unsure')
      return { rotate: -10, y: 0, transition: calm ? instant : { type: 'spring' as const, stiffness: 260, damping: 14 } }
    return { rotate: 0, y: 0, transition: calm ? instant : { type: 'spring' as const, stiffness: 200, damping: 20 } }
  })()

  // Pupils: look up while thinking, aside when unsure.
  const look =
    mood === 'thinking' ? { x: 1.4, y: -2.6 } : mood === 'unsure' ? { x: -2, y: 0.8 } : { x: 0, y: 0 }
  const lookT: Transition = calm ? instant : { type: 'spring', stiffness: 300, damping: 18 }

  // Hands: raised for the shrug.
  const shrugL = mood === 'unsure' ? { x: -3, y: -6 } : { x: 0, y: 0 }
  const shrugR = mood === 'unsure' ? { x: 3, y: -6 } : { x: 0, y: 0 }

  const squint = mood === 'answer'

  return (
    <svg
      className={`mascot mascot-${mood}`}
      width={size}
      height={size * (84 / 76)}
      viewBox="-4 -4 76 84"
      aria-hidden="true"
      focusable="false"
    >
      {/* ground shadow */}
      <motion.ellipse
        cx={32}
        cy={76}
        rx={13}
        ry={2.6}
        fill={INK}
        opacity={0.16}
        style={centered}
        animate={calm || mood === 'unsure' ? { scaleX: 1 } : { scaleX: [1, 0.86, 1] }}
        transition={calm || mood === 'unsure' ? instant : { duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.g animate={float}>
        <motion.g style={{ transformBox: 'view-box', transformOrigin: '32px 70px' }} animate={pose}>
          <g transform="translate(0 8)">
            {/* body */}
            <path d={PIN} fill={INK} />
            {/* cap: the state and city layers of the Locus mark */}
            <path d="M32 -1.5 44.5 4.6 32 10.7 19.5 4.6Z" fill={BLUE} stroke={INK} strokeWidth={1.4} strokeLinejoin="round" />
            <path d="M32 -7.5 41.5 -2.9 32 1.7 22.5 -2.9Z" fill={TEAL} stroke={INK} strokeWidth={1.4} strokeLinejoin="round" />
            {/* cheeks */}
            <ellipse cx={15.5} cy={35} rx={3.2} ry={1.8} fill={BLUE} opacity={0.6} />
            <ellipse cx={48.5} cy={35} rx={3.2} ry={1.8} fill={BLUE} opacity={0.6} />
            {/* eyes */}
            {squint ? (
              <g fill="none" stroke={PAPER} strokeWidth={2.4} strokeLinecap="round">
                <path d="M17.5 27.5 Q22.5 21.5 27.5 27.5" />
                <path d="M36.5 27.5 Q41.5 21.5 46.5 27.5" />
              </g>
            ) : (
              <motion.g style={centered} animate={{ scaleY: blink ? 0.1 : 1 }} transition={{ duration: 0.07 }}>
                <circle cx={22.5} cy={26} r={6.4} fill="#fff" />
                <circle cx={41.5} cy={26} r={6.4} fill="#fff" />
                <motion.g animate={look} transition={lookT}>
                  <circle cx={22.5} cy={26.4} r={3.3} fill={INK} />
                  <circle cx={41.5} cy={26.4} r={3.3} fill={INK} />
                  <circle cx={23.7} cy={25.1} r={1.1} fill="#fff" />
                  <circle cx={42.7} cy={25.1} r={1.1} fill="#fff" />
                </motion.g>
              </motion.g>
            )}
            {/* reading glasses */}
            <g fill="none" stroke={PAPER} strokeWidth={1.5}>
              <circle cx={22.5} cy={26} r={8.2} />
              <circle cx={41.5} cy={26} r={8.2} />
              <path d="M30.7 25.2 Q32 23.6 33.3 25.2" strokeLinecap="round" />
            </g>
            {/* mouth */}
            <g fill="none" stroke={PAPER} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              {mood === 'answer' && <path d="M27 37 Q32 42.5 37 37" />}
              {mood === 'idle' && <path d="M28.5 37.5 Q32 40.2 35.5 37.5" />}
              {mood === 'thinking' && <circle cx={33} cy={38.4} r={1.6} />}
              {mood === 'unsure' && <path d="M27.5 38.6 q2.25 -2 4.5 0 t4.5 0" />}
            </g>
            {/* open book */}
            <path d="M18.5 45 32 47.6 45.5 45 45.5 52.4 32 55 18.5 52.4Z" fill={BLUE} stroke={INK} strokeWidth={1.2} strokeLinejoin="round" />
            <path d="M20 44 32 46.2 32 53.4 20 51.2Z" fill={PAPER} stroke={INK} strokeWidth={1} strokeLinejoin="round" />
            <path d="M44 44 32 46.2 32 53.4 44 51.2Z" fill={PAPER} stroke={INK} strokeWidth={1} strokeLinejoin="round" />
            <g stroke={INK} strokeWidth={0.7} opacity={0.45}>
              <path d="M22.5 46.8 29.5 48.1M22.5 48.8 29.5 50.1" />
              <path d="M41.5 46.8 34.5 48.1M41.5 48.8 34.5 50.1" />
            </g>
            {/* hands */}
            <motion.circle cx={19} cy={48.5} r={2.6} fill={PAPER} stroke={INK} strokeWidth={1} animate={shrugL} transition={lookT} />
            <motion.circle cx={45} cy={48.5} r={2.6} fill={PAPER} stroke={INK} strokeWidth={1} animate={shrugR} transition={lookT} />
          </g>
        </motion.g>
      </motion.g>
      {/* thinking bubble */}
      {mood === 'thinking' &&
        [0, 1, 2].map((i) => (
          <motion.circle
            key={i}
            cx={53 + i * 6}
            cy={10 - i * 4.5}
            r={1.8 + i * 0.6}
            fill={PAPER}
            stroke={INK}
            strokeWidth={1.1}
            style={centered}
            initial={calm ? false : { opacity: 0, scale: 0.4 }}
            animate={calm ? { opacity: 1, scale: 1 } : { opacity: [0, 1, 1, 0], scale: [0.4, 1, 1, 0.6] }}
            transition={calm ? instant : { duration: 1.2, repeat: Infinity, delay: i * 0.18, times: [0, 0.3, 0.75, 1] }}
          />
        ))}
      {/* unsure: a question mark */}
      {mood === 'unsure' && (
        <motion.text
          x={58}
          y={14}
          fontSize={16}
          fontWeight={900}
          fill={INK}
          fontFamily="system-ui, sans-serif"
          initial={calm ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={calm ? instant : { type: 'spring', stiffness: 300, damping: 16 }}
        >
          ?
        </motion.text>
      )}
    </svg>
  )
}
