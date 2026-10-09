import type { ConversationDto } from "../api/types";
import { formatFullTime, formatMessageTime } from "../time";

interface Props {
  conversations: ConversationDto[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  creating: boolean;
}

export function ConversationList({ conversations, selectedId, onSelect, onCreate, creating }: Props) {
  return (
    <nav className="sidebar" aria-label="Conversations">
      <button type="button" className="sidebar__new" onClick={onCreate} disabled={creating}>
        New conversation
      </button>
      {conversations.length === 0 ? (
        <p className="empty">No conversations yet.</p>
      ) : (
        <ul className="sidebar__list">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                className="sidebar__item"
                aria-current={conversation.id === selectedId ? "true" : undefined}
                onClick={() => onSelect(conversation.id)}
              >
                <span className="sidebar__title">{conversation.title ?? "Untitled conversation"}</span>
                <time
                  className="sidebar__time"
                  dateTime={conversation.created_at}
                  title={formatFullTime(conversation.created_at)}
                >
                  {formatMessageTime(conversation.created_at)}
                </time>
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}
