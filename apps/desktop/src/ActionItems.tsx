import { useEffect, useMemo, useState } from "react";

import {
  getActionItems,
  setActionItemDone,
  type ActionItem,
} from "./api";
import { toast } from "./toast";

interface MeetingGroup {
  meetingId: number;
  title: string;
  items: ActionItem[];
}

export function ActionItems({
  onOpenMeeting,
}: {
  onOpenMeeting: (meetingId: number) => void;
}) {
  const [items, setItems] = useState<ActionItem[] | null>(null);

  useEffect(() => {
    getActionItems()
      .then(setItems)
      .catch(() => {
        setItems([]);
        toast("Couldn't load action items.");
      });
  }, []);

  const groups = useMemo<MeetingGroup[]>(() => {
    const byMeeting = new Map<number, MeetingGroup>();
    for (const item of items ?? []) {
      let group = byMeeting.get(item.meeting_id);
      if (!group) {
        group = {
          meetingId: item.meeting_id,
          title: item.meeting_title,
          items: [],
        };
        byMeeting.set(item.meeting_id, group);
      }
      group.items.push(item);
    }
    return [...byMeeting.values()];
  }, [items]);

  const toggle = async (item: ActionItem) => {
    const next = !item.done;
    setItems(
      (current) =>
        current?.map((i) => (i.id === item.id ? { ...i, done: next } : i)) ??
        null,
    );
    try {
      await setActionItemDone(item.id, next);
    } catch {
      setItems(
        (current) =>
          current?.map((i) =>
            i.id === item.id ? { ...i, done: item.done } : i,
          ) ?? null,
      );
      toast("Couldn't update that action item.");
    }
  };

  if (items === null) {
    return (
      <div className="transcript transcript--empty">
        <p className="transcript__placeholder">Loading action items…</p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="transcript transcript--empty">
        <p className="transcript__placeholder">
          No action items yet — they're collected from meeting summaries.
        </p>
      </div>
    );
  }

  return (
    <div className="transcript">
      <div className="action-items">
        {groups.map((group) => (
          <section className="action-group" key={group.meetingId}>
            <button
              className="action-group__title"
              onClick={() => onOpenMeeting(group.meetingId)}
              title="Open this meeting"
            >
              {group.title}
            </button>
            <ul className="action-group__list">
              {group.items.map((item) => (
                <li key={item.id}>
                  <label
                    className={
                      "action-item" + (item.done ? " action-item--done" : "")
                    }
                  >
                    <input
                      type="checkbox"
                      checked={item.done}
                      onChange={() => toggle(item)}
                    />
                    <span>{item.text}</span>
                  </label>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
