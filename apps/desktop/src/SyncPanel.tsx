import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";

import {
  applyAllProposals,
  applyProposal,
  patchProposal,
  type SyncProposal,
} from "./api";
import { segmentIn } from "./motion";
import { toast } from "./toast";

const TARGET_META: Record<string, { label: string; verb: string }> = {
  "apple-reminders": { label: "Reminders", verb: "Add reminder" },
  "apple-calendar": { label: "Calendar", verb: "Add event" },
  "apple-notes": { label: "Notes", verb: "Add note" },
};

function formatWhen(iso?: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function EditableTitle({
  proposal,
  onSave,
}: {
  proposal: SyncProposal;
  onSave: (title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(proposal.title);
  const locked = proposal.status === "applied";

  const save = () => {
    setEditing(false);
    const next = value.trim();
    if (next && next !== proposal.title) onSave(next);
  };

  if (editing) {
    return (
      <input
        className="sync-card__title-input"
        value={value}
        autoFocus
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") {
            setValue(proposal.title);
            setEditing(false);
          }
        }}
      />
    );
  }
  return (
    <button
      className="sync-card__title"
      onClick={() => {
        if (locked) return;
        setValue(proposal.title);
        setEditing(true);
      }}
      title={locked ? undefined : "Click to edit before sending"}
      disabled={locked}
    >
      {proposal.title}
    </button>
  );
}

export function SyncPanel({
  meetingId,
  onChange,
}: {
  meetingId: number;
  onChange?: (proposals: SyncProposal[]) => void;
}) {
  const [proposals, setProposals] = useState<SyncProposal[] | null>(null);
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const [applyingAll, setApplyingAll] = useState(false);

  // Keep the parent's tab badge in sync with what happens in here.
  useEffect(() => {
    if (proposals !== null) onChange?.(proposals);
  }, [proposals, onChange]);

  useEffect(() => {
    setProposals(null);
    import("./api").then(({ getMeetingProposals }) =>
      getMeetingProposals(meetingId)
        .then(setProposals)
        .catch(() => {
          setProposals([]);
          toast("Couldn't load sync suggestions.");
        }),
    );
  }, [meetingId]);

  const groups = useMemo(() => {
    const byTarget = new Map<string, SyncProposal[]>();
    for (const proposal of proposals ?? []) {
      if (proposal.status === "stale") continue;
      const bucket = byTarget.get(proposal.target) ?? [];
      bucket.push(proposal);
      byTarget.set(proposal.target, bucket);
    }
    return [...byTarget.entries()];
  }, [proposals]);

  const replace = (next: SyncProposal) =>
    setProposals((current) =>
      current?.map((p) => (p.id === next.id ? next : p)) ?? null,
    );

  const withBusy = async (id: number, work: () => Promise<void>) => {
    setBusyIds((s) => new Set(s).add(id));
    try {
      await work();
    } finally {
      setBusyIds((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
    }
  };

  const apply = (proposal: SyncProposal) =>
    withBusy(proposal.id, async () => {
      try {
        replace(await applyProposal(proposal.id));
      } catch {
        toast("Couldn't apply that item.");
      }
    });

  const skip = (proposal: SyncProposal, undo: boolean) =>
    withBusy(proposal.id, async () => {
      try {
        replace(
          await patchProposal(proposal.id, {
            status: undo ? "proposed" : "skipped",
          }),
        );
      } catch {
        toast("Couldn't update that item.");
      }
    });

  const rename = (proposal: SyncProposal, title: string) =>
    withBusy(proposal.id, async () => {
      try {
        replace(await patchProposal(proposal.id, { title }));
      } catch {
        toast("Couldn't save that edit.");
      }
    });

  const applyAll = async () => {
    setApplyingAll(true);
    try {
      setProposals(await applyAllProposals(meetingId));
    } catch {
      toast("Couldn't apply the suggestions.");
    } finally {
      setApplyingAll(false);
    }
  };

  if (proposals === null) {
    return (
      <div className="transcript transcript--empty">
        <p className="transcript__placeholder">Loading suggestions…</p>
      </div>
    );
  }

  const open = proposals.filter(
    (p) => p.status === "proposed" || p.status === "failed",
  );

  if (groups.length === 0) {
    return (
      <div className="transcript transcript--empty">
        <p className="transcript__placeholder">
          No sync suggestions for this meeting — they're generated from the
          summary after each recording.
        </p>
      </div>
    );
  }

  return (
    <div className="transcript">
      <div className="sync">
        <p className="sync__lede">
          Nothing is sent anywhere until you approve it — review, edit, then
          apply each item.
        </p>
        {groups.map(([target, items]) => (
          <section className="sync-group" key={target}>
            <h3 className="sync-group__title">
              {TARGET_META[target]?.label ?? target}
            </h3>
            {items.map((proposal) => {
              const busy = busyIds.has(proposal.id);
              const when =
                proposal.kind === "event"
                  ? formatWhen(proposal.payload.start_iso)
                  : formatWhen(proposal.payload.due_iso);
              return (
                <motion.div
                  className={
                    "sync-card" +
                    (proposal.status === "skipped" ? " sync-card--skipped" : "")
                  }
                  key={proposal.id}
                  variants={segmentIn}
                  initial="initial"
                  animate="animate"
                >
                  <div className="sync-card__main">
                    <EditableTitle
                      proposal={proposal}
                      onSave={(title) => rename(proposal, title)}
                    />
                    <span className="sync-card__meta">
                      {when && <>{when} · </>}
                      {proposal.kind === "note"
                        ? "summary, key points & action items"
                        : proposal.body}
                    </span>
                    {proposal.status === "failed" && proposal.error && (
                      <span className="sync-card__error">{proposal.error}</span>
                    )}
                  </div>
                  <div className="sync-card__actions">
                    {proposal.status === "applied" ? (
                      <span className="sync-card__done">Added ✓</span>
                    ) : proposal.status === "skipped" ? (
                      <button
                        className="sync-card__skip"
                        disabled={busy}
                        onClick={() => skip(proposal, true)}
                      >
                        Undo skip
                      </button>
                    ) : (
                      <>
                        <button
                          className="sync-card__skip"
                          disabled={busy}
                          onClick={() => skip(proposal, false)}
                        >
                          Skip
                        </button>
                        <button
                          className="sync-card__apply"
                          disabled={busy}
                          onClick={() => apply(proposal)}
                        >
                          {busy
                            ? "Adding…"
                            : proposal.status === "failed"
                              ? "Retry"
                              : (TARGET_META[target]?.verb ?? "Add")}
                        </button>
                      </>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </section>
        ))}
        {open.length > 1 && (
          <button
            className="sync__apply-all"
            disabled={applyingAll}
            onClick={applyAll}
          >
            {applyingAll ? "Applying…" : `Apply all ${open.length} suggestions`}
          </button>
        )}
      </div>
    </div>
  );
}
