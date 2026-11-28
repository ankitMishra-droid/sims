import { parseMarkdownBlocks } from './aiFormatting'

function renderInline(text, keyPrefix) {
  const parts = []
  const tokenRe = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g
  let lastIndex = 0
  let match
  let idx = 0

  while ((match = tokenRe.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    const token = match[0]
    if (token.startsWith('**') && token.endsWith('**')) {
      parts.push(
        <strong key={`${keyPrefix}-b-${idx}`} className="ai-md-strong">
          {token.slice(2, -2)}
        </strong>
      )
    } else if (token.startsWith('`') && token.endsWith('`')) {
      parts.push(
        <code key={`${keyPrefix}-c-${idx}`} className="ai-md-code">
          {token.slice(1, -1)}
        </code>
      )
    }
    idx += 1
    lastIndex = match.index + token.length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts.length ? parts : text
}

/**
 * Zero-dependency, XSS-safe lightweight Markdown renderer tuned for conversational AI.
 */
export default function AiMessageContent({ content, role = 'assistant' }) {
  const raw = String(content || '').replace(/\r\n/g, '\n').trim()
  if (!raw) return null

  if (role === 'user') {
    return <div className="ai-msg-text ai-user-text">{raw}</div>
  }

  const blocks = parseMarkdownBlocks(raw)

  return (
    <div className="ai-msg-text ai-md-content">
      {blocks.map((blk, idx) => {
        if (blk.type === 'heading') {
          return (
            <div key={idx} className="ai-md-heading">
              {renderInline(blk.text, `h-${idx}`)}
            </div>
          )
        }
        if (blk.type === 'ol') {
          return (
            <ol key={idx} className="ai-md-ol">
              {blk.items.map((item, itemIdx) => (
                <li key={itemIdx} className="ai-md-li">
                  <span>{renderInline(item.text, `ol-${idx}-${itemIdx}`)}</span>
                  {item.subBullets.length > 0 && (
                    <ul className="ai-md-subul">
                      {item.subBullets.map((sub, subIdx) => (
                        <li key={subIdx}>{renderInline(sub, `sub-${idx}-${itemIdx}-${subIdx}`)}</li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
          )
        }
        if (blk.type === 'ul') {
          return (
            <ul key={idx} className="ai-md-ul">
              {blk.items.map((item, itemIdx) => (
                <li key={itemIdx}>{renderInline(item, `ul-${idx}-${itemIdx}`)}</li>
              ))}
            </ul>
          )
        }
        return (
          <p key={idx} className="ai-md-p">
            {renderInline(blk.text, `p-${idx}`)}
          </p>
        )
      })}
    </div>
  )
}
