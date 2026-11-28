/**
 * Accessible form field wrapper preserving visible labels, required markers, and optional helper text.
 */
export default function FormField({
  label,
  htmlFor,
  required = false,
  hint = '',
  className = '',
  children,
}) {
  return (
    <div className={`form-group ${className}`.trim()}>
      {label && (
        <label className="form-label" htmlFor={htmlFor}>
          {label}
          {required && <span className="required" aria-hidden="true"> *</span>}
        </label>
      )}
      {children}
      {hint && <span className="form-hint">{hint}</span>}
    </div>
  )
}
