import { useCallback, useEffect, useState } from "react";

// The selected conversation id lives in the URL hash (#/c/<id>) so a reload reopens the same
// conversation. This is client interaction state only; the server owns all conversation data.
// The hash is untrusted input (anyone can hand over a link), so it is parsed defensively.

const PREFIX = "#/c/";

export type HashSelection =
  | { kind: "none" }
  | { kind: "id"; id: string }
  /** The hash addresses a conversation but cannot be decoded into an identifier. */
  | { kind: "invalid" };

export function parseHash(hash: string): HashSelection {
  if (!hash.startsWith(PREFIX)) return { kind: "none" };
  const raw = hash.slice(PREFIX.length);
  try {
    const id = decodeURIComponent(raw);
    return id === "" ? { kind: "none" } : { kind: "id", id };
  } catch {
    // Malformed percent-encoding or invalid UTF-8 (URIError).
    return { kind: "invalid" };
  }
}

const read = (): HashSelection => parseHash(window.location.hash);

export function useHashSelection(): [string | null, (id: string | null) => void, boolean] {
  const [selection, setSelection] = useState<HashSelection>(read);

  useEffect(() => {
    const onChange = () => setSelection(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const select = useCallback((id: string | null) => {
    window.location.hash = id === null ? "" : PREFIX + encodeURIComponent(id);
  }, []);

  return [selection.kind === "id" ? selection.id : null, select, selection.kind === "invalid"];
}
