import { useCallback, useEffect, useState } from "react";

// The selected conversation id lives in the URL hash (#/c/<id>) so a reload reopens the same
// conversation. This is client interaction state only; the server owns all conversation data.

const PREFIX = "#/c/";

function read(): string | null {
  const hash = window.location.hash;
  return hash.startsWith(PREFIX) ? decodeURIComponent(hash.slice(PREFIX.length)) : null;
}

export function useHashSelection(): [string | null, (id: string | null) => void] {
  const [selected, setSelected] = useState<string | null>(read);

  useEffect(() => {
    const onChange = () => setSelected(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const select = useCallback((id: string | null) => {
    window.location.hash = id === null ? "" : PREFIX + encodeURIComponent(id);
  }, []);

  return [selected, select];
}
