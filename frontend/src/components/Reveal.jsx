import { useEffect, useRef, useState } from 'react'

// Revela o bloco com um leve deslize quando ele entra na tela (uma vez só).
export default function Reveal({ as: Tag = 'div', className = '', delay = 0, style, children, ...rest }) {
  const ref = useRef(null)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el || !('IntersectionObserver' in window)) {
      setShown(true)
      return undefined
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true)
          io.disconnect()
        }
      },
      { threshold: 0.12 }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return (
    <Tag ref={ref} className={`rv ${shown ? 'in' : ''} ${className}`} style={{ ...style, '--rd': `${delay}s` }} {...rest}>
      {children}
    </Tag>
  )
}
