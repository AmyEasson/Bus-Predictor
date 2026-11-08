import { useEffect, useRef, useState } from 'react';
import { searchStops } from '../services/api';

// Stop search with suggestions. Controlled by `value` (the selected stop, or null).
// Keyboard: up/down to move, Enter to pick, Escape to close.
export function SearchBox({ value, onSelect, onHover = () => {}, placeholder, leading, trailing, autoFocus, className = '' }) {
  const [query, setQuery] = useState(value?.stop_name ?? '');
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const typedRef = useRef(false); // true when the selection was cleared by the user typing

  // follow the selected stop when it changes from outside (swap, "Directions", the clear button).
  // Not when typing cleared it: that would wipe what the user is typing.
  useEffect(() => {
    if (!value && typedRef.current) { typedRef.current = false; return; }
    typedRef.current = false;
    setQuery(value?.stop_name ?? '');
  }, [value]);

  useEffect(() => {
    const q = query.trim();
    if (!open || q.length < 2 || (value && q === value.stop_name)) {
      setSuggestions([]);
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const results = await searchStops(q);
      if (!cancelled) {
        setSuggestions(results);
        setActive(0);
      }
    }, 200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query, open, value]);

  const pick = (stop) => {
    setOpen(false);
    setSuggestions([]);
    onHover(null);
    onSelect(stop);
    inputRef.current?.blur();
  };

  const onKeyDown = (e) => {
    if (!suggestions.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, suggestions.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(suggestions[active]); }
    else if (e.key === 'Escape') { setOpen(false); onHover(null); }
  };

  const showEmpty = open && query.trim().length >= 2 && !suggestions.length && !(value && query === value.stop_name);

  return (
    <div className={`searchbox ${className}`}>
      {leading}
      <input
        ref={inputRef}
        value={query}
        placeholder={placeholder}
        autoFocus={autoFocus}
        autoComplete="off"
        spellCheck={false}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => { setOpen(false); onHover(null); }, 120)}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          if (value) { typedRef.current = true; onSelect(null); }
        }}
        onKeyDown={onKeyDown}
      />
      {trailing}
      {open && suggestions.length > 0 && (
        <ul className="suggestions" role="listbox">
          {suggestions.map((s, i) => (
            <li
              key={s.stop_id}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : ''}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => { setActive(i); onHover(s); }}
              onMouseLeave={() => onHover(null)}
              onClick={() => pick(s)}
            >
              <span className="sugg-icon" aria-hidden>●</span>
              <span className="sugg-text">
                <b>{s.stop_name}</b>
                <small>{s.towards ? `towards ${s.towards}` : 'Bus stop'}</small>
              </span>
              {s.lines?.length > 0 && (
                <span className="sugg-lines">
                  {s.lines.slice(0, 3).map((l) => <span key={l} className="line">{l}</span>)}
                  {s.lines.length > 3 && <span className="muted small">+{s.lines.length - 3}</span>}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {showEmpty && <div className="suggestions empty">No matching stops</div>}
    </div>
  );
}
