/**
 * Pure formatting & filtering utilities shared between AiMessageContent and tests.
 */

export function filterUserFacingSources(sources) {
  if (!Array.isArray(sources)) return []
  return sources.filter(
    (src) =>
      src &&
      typeof src === 'object' &&
      src.source_kind === 'document' &&
      Boolean(src.document_id) &&
      Boolean(src.title)
  )
}

export function parseMarkdownBlocks(content) {
  const raw = String(content || '').replace(/\r\n/g, '\n').trim()
  if (!raw) return []

  const lines = raw.split('\n')
  const blocks = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    const headingMatch = trimmed.match(/^#{1,4}\s+(.+)$/)
    if (headingMatch) {
      blocks.push({ type: 'heading', text: headingMatch[1].trim() })
      i += 1
      continue
    }

    const orderedMatch = line.match(/^\s*(\d+)\.\s+(.+)$/)
    if (orderedMatch) {
      const items = []
      while (i < lines.length) {
        while (i < lines.length && !lines[i].trim()) {
          // Keep blank lines inside the same <ol> if another numbered item follows immediately
          let peek = i + 1
          while (peek < lines.length && !lines[peek].trim()) peek += 1
          if (peek < lines.length && /^\s*\d+\.\s+/.test(lines[peek])) {
            i = peek
          } else {
            break
          }
        }
        if (i >= lines.length) break
        const curLine = lines[i]
        const curOrd = curLine.match(/^\s*(\d+)\.\s+(.+)$/)
        if (!curOrd) break
        const subBullets = []
        i += 1
        while (i < lines.length) {
          const nextLine = lines[i]
          if (!nextLine.trim()) {
            if (i + 1 < lines.length && /^\s*[-*•]\s+/.test(lines[i + 1]) && !/^\s*\d+\.\s+/.test(lines[i + 1])) {
              i += 1
              continue
            }
            break
          }
          const subMatch = nextLine.match(/^\s*[-*•]\s+(.+)$/)
          if (subMatch && !/^\s*\d+\.\s+/.test(nextLine)) {
            subBullets.push(subMatch[1].trim())
            i += 1
          } else {
            break
          }
        }
        items.push({ text: curOrd[2].trim(), subBullets })
      }
      blocks.push({ type: 'ol', items })
      continue
    }

    if (/^\s*[-*•]\s+/.test(line)) {
      const items = []
      while (i < lines.length) {
        const bMatch = lines[i].match(/^\s*[-*•]\s+(.+)$/)
        if (!bMatch) break
        items.push(bMatch[1].trim())
        i += 1
      }
      blocks.push({ type: 'ul', items })
      continue
    }

    const paraLines = []
    while (i < lines.length) {
      const cur = lines[i]
      if (
        !cur.trim() ||
        /^#{1,4}\s+/.test(cur.trim()) ||
        /^\s*\d+\.\s+/.test(cur) ||
        /^\s*[-*•]\s+/.test(cur)
      ) {
        break
      }
      paraLines.push(cur.trim())
      i += 1
    }
    if (paraLines.length) {
      blocks.push({ type: 'p', text: paraLines.join(' ') })
    }
  }

  return blocks
}
