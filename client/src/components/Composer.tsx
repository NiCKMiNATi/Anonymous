import { useState, type KeyboardEvent } from "react";

export const MAX_MESSAGE_CHARS = 32_000; // mirrors the server placeholder limit

interface Props {
  disabled: boolean;
  disabledReason?: string;
  error: string | null;
  onSend: (content: string) => void;
  /** Text restored after a refused send so the user does not lose their draft. */
  restoredText: string;
}

export function Composer({ disabled, disabledReason, error, onSend, restoredText }: Props) {
  const [text, setText] = useState(restoredText);
  const canSend = !disabled && text.trim().length > 0;

  const submit = () => {
    if (!canSend) return;
    onSend(text);
    setText("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {error && (
        <p className="composer__error" role="alert">
          {error}
        </p>
      )}
      {disabled && disabledReason && <p className="composer__note">{disabledReason}</p>}
      <label htmlFor="message-input" className="visually-hidden">
        Message
      </label>
      <textarea
        id="message-input"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Write a message (Enter to send, Shift+Enter for a new line)"
        rows={3}
        maxLength={MAX_MESSAGE_CHARS}
      />
      <button type="submit" disabled={!canSend}>
        Send
      </button>
    </form>
  );
}
