"use client";

import { ArrowUp, Lightbulb, RotateCcw, Sparkles, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useCopilot } from "@/components/app/copilot/copilot-provider";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Spinner } from "@/components/ui/progress";
import { useToast } from "@/components/ui/toast";
import { ApiError, errorMessage } from "@/lib/api";
import { generateClip } from "@/lib/clips";
import {
  charCount,
  QUESTION_MAX,
  askCopilot,
  clearCopilotThread,
  copilotScope,
  getCopilotContext,
  getCopilotStatus,
  getCopilotThread,
  lengthNote,
  resolveCopilotAction,
  starters,
  threadKey,
  waitingText,
  type CopilotAction,
  type CopilotContext,
  type CopilotMessage,
  type CopilotScope,
  type CopilotStatus,
} from "@/lib/copilot";
import { createHref } from "@/lib/edits";

const DESKTOP = "(min-width: 1024px)";
const subscribeMedia = (notify: () => void) => {
  const query = window.matchMedia(DESKTOP);
  query.addEventListener("change", notify);
  return () => query.removeEventListener("change", notify);
};

function useDesktop(): boolean {
  return useSyncExternalStore(subscribeMedia, () => window.matchMedia(DESKTOP).matches, () => true);
}

type Pending = { key: string; text: string; startedAt: number };

/** Ask PeakSift: a side panel on large screens, a full-height sheet on phones. */
export function CopilotPanel() {
  const { open, request, closeCopilot, takeQueued } = useCopilot();
  const desktop = useDesktop();
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const search = typeof window === "undefined" ? "" : window.location.search;
  const scope = useMemo(() => copilotScope(pathname, search), [pathname, search]);
  const key = threadKey(scope);

  const [threads, setThreads] = useState<Record<string, CopilotMessage[]>>({});
  const [scopes, setScopes] = useState<Record<string, string>>({});
  const [context, setContext] = useState<CopilotContext | null>(null);
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [draft, setDraft] = useState("");
  const composer = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);

  const messages = threads[key];

  // Load the conversation of this project (or the workspace), its context label and availability.
  useEffect(() => {
    if (!open || threads[key] !== undefined) return;
    let cancelled = false;
    getCopilotThread(scope.projectId)
      .then((thread) => {
        if (cancelled) return;
        // A question asked as the panel opened may already be answered: keep it after the history.
        setThreads((all) => {
          const known = new Set(thread.messages.map((message) => message.id));
          return { ...all, [key]: [...thread.messages, ...(all[key] ?? []).filter((message) => !known.has(message.id))] };
        });
        setScopes((all) => ({ ...all, [key]: thread.scope }));
      })
      .catch((failure: unknown) => !cancelled && setError(errorMessage(failure)));
    return () => {
      cancelled = true;
    };
  }, [open, key, scope.projectId, threads]);

  const contextKey = `${scope.page}|${scope.projectId}|${scope.clipId}|${scope.editId}`;
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getCopilotContext(scope)
      .then((value) => !cancelled && setContext(value))
      .catch(() => !cancelled && setContext(null));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- contextKey covers the scope
  }, [open, contextKey]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getCopilotStatus()
      .then((value) => !cancelled && setStatus(value))
      .catch(() => !cancelled && setStatus(null));
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Keep the newest message in view — in the side panel and in the phone sheet, whose scrolling
  // box is the dialog's body.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages?.length, pending, open]);

  const ask = useCallback(
    async (text: string, at: CopilotScope = scope) => {
      const question = text.trim();
      if (!question || pending || charCount(question) > QUESTION_MAX) return;
      const askedKey = threadKey(at);
      setError(null);
      setDraft("");
      setPending({ key: askedKey, text: question, startedAt: Date.now() });
      try {
        const exchange = await askCopilot(at, question);
        setThreads((all) => ({
          ...all,
          [askedKey]: [...(all[askedKey] ?? []), exchange.question, exchange.answer],
        }));
      } catch (failure) {
        setDraft((current) => current || question); // nothing typed is lost
        setError(
          failure instanceof ApiError && failure.status === 429
            ? "You're asking quickly — wait a moment, then try again."
            : errorMessage(failure),
        );
      } finally {
        setPending(null);
        // Keep typing where the conversation is (the starter that was clicked may be gone).
        window.setTimeout(() => composer.current?.focus({ preventScroll: true }), 0);
      }
    },
    [scope, pending],
  );

  // Escape closes the desktop panel wherever focus is (a clicked starter may have disappeared);
  // the phone sheet is a native dialog and handles Escape itself.
  useEffect(() => {
    if (!open || !desktop || confirmClear) return;
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (document.querySelector("dialog[open]")) return; // another dialog is in front
      closeCopilot();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, desktop, confirmClear, closeCopilot]);

  // On each opening request: ask a question handed over by another entry point (e.g. the command
  // menu) — or, while an answer is still coming, leave it in the composer — or put the cursor in
  // the composer. Only on a request, never on later renders.
  const askRef = useRef(ask);
  const pendingRef = useRef(pending);
  useEffect(() => {
    askRef.current = ask;
    pendingRef.current = pending;
  }, [ask, pending]);
  useEffect(() => {
    if (!open) return;
    const queued = takeQueued();
    if (queued && !pendingRef.current) void askRef.current(queued);
    else if (queued) setDraft(queued);
    if (!queued && window.matchMedia(DESKTOP).matches) composer.current?.focus();
  }, [open, request, takeQueued]);

  async function runAction(message: CopilotMessage, action: CopilotAction) {
    const id = `${message.id}:${action.index}`;
    setBusyAction(id);
    setActionErrors((all) => ({ ...all, [id]: "" }));
    try {
      const resolution = await resolveCopilotAction(message.id, action.index);
      if (resolution.kind === "navigate") {
        router.push(resolution.href);
      } else {
        const clip = await generateClip(resolution.project_id, resolution.video_id, resolution.run_id,
          resolution.candidate_id);
        router.push(createHref(resolution.project_id, clip.id));
      }
      if (!desktop) closeCopilot();
    } catch (failure) {
      setActionErrors((all) => ({ ...all, [id]: errorMessage(failure) }));
    } finally {
      setBusyAction(null);
    }
  }

  async function clear() {
    setConfirmClear(false);
    try {
      await clearCopilotThread(scope.projectId);
      setThreads((all) => ({ ...all, [key]: [] }));
      toast("Conversation cleared");
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void ask(draft);
    }
  }

  const scopeLabel = context?.scope ?? scopes[key] ?? "Your workspace";
  const facts = context && context.scope === scopeLabel ? context.facts : [];
  const waiting = pending && pending.key === key ? pending : null;
  const header = (
    <div className="min-w-0">
      <p className="truncate text-caption text-subtle" title={[scopeLabel, ...facts].join(" · ")}>
        {[scopeLabel, ...facts].join(" · ")}
      </p>
    </div>
  );

  const body = (
    <div className="flex flex-col gap-4">
      {status && !status.available ? (
        <InlineAlert tone="info" title="PeakSift's local assistant isn't available right now">
          Everything else works as usual. Questions still get PeakSift&apos;s own next step.
        </InlineAlert>
      ) : null}
      {messages === undefined ? (
        <div role="status" className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Loading the conversation…
        </div>
      ) : messages.length === 0 && !waiting ? (
        <Welcome page={scope.page} hasSource={context?.has_source ?? null} scope={scopeLabel} onAsk={(text) => void ask(text)} disabled={!!pending} />
      ) : (
        <ol className="flex flex-col gap-4" aria-label="Conversation">
          {(messages ?? []).map((message) => (
            <li key={message.id}>
              <Message
                message={message}
                busyAction={busyAction}
                actionErrors={actionErrors}
                onAction={(action) => void runAction(message, action)}
              />
            </li>
          ))}
          {waiting ? (
            <li>
              <article aria-label="Your question" dir="auto" className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-accent/15 px-3.5 py-2.5 text-sm text-foreground">
                {waiting.text}
              </article>
            </li>
          ) : null}
        </ol>
      )}
      {waiting ? <Waiting startedAt={waiting.startedAt} /> : null}
      {error ? <InlineAlert title="That didn't work">{error}</InlineAlert> : null}
      <div ref={end} />
    </div>
  );

  const composerBlock = (
    <div className="w-full space-y-2">
      {messages && messages.length > 0 && !pending ? (
        <ul className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5 [scrollbar-width:none]" aria-label="Suggested questions">
          {starters(scope.page, context?.has_source ?? null).map((text) => (
            <li key={text} className="shrink-0">
              <button
                type="button"
                onClick={() => void ask(text)}
                className="inline-flex min-h-8 items-center rounded-full border border-border bg-surface-2 px-3 text-caption whitespace-nowrap text-muted transition-colors hover:border-border-strong hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent pointer-coarse:min-h-11"
              >
                {text}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <Composer
      inputRef={composer}
      value={draft}
      onChange={setDraft}
      onKeyDown={onKeyDown}
      onSubmit={() => void ask(draft)}
      disabled={!!pending}
      placeholder={scope.projectId ? "Ask about this project…" : "Ask about your projects and Shorts…"}
    />
    </div>
  );

  const confirm = (
    <Dialog
      open={confirmClear}
      onClose={() => setConfirmClear(false)}
      title="Clear this conversation?"
      footer={
        <>
          <Button variant="secondary" onClick={() => setConfirmClear(false)} data-autofocus>
            Keep it
          </Button>
          <Button variant="danger" onClick={() => void clear()}>
            Clear conversation
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted">
        The questions and answers about {scopeLabel} are deleted. Your project and everything in it stay
        as they are.
      </p>
    </Dialog>
  );

  const clearButton = messages && messages.length > 0 ? (
    <IconButton aria-label="Clear conversation" size="sm" onClick={() => setConfirmClear(true)} disabled={!!pending}>
      <RotateCcw aria-hidden="true" />
    </IconButton>
  ) : null;

  if (!desktop) {
    return (
      <>
        <Dialog
          open={open}
          onClose={closeCopilot}
          title="Ask PeakSift"
          description={[scopeLabel, ...facts].join(" · ")}
          placement="full"
          footer={composerBlock}
          headerActions={clearButton}
        >
          <div>{body}</div>
        </Dialog>
        {confirm}
      </>
    );
  }

  if (!open) return null;
  return (
    <>
      <aside
        aria-label="Ask PeakSift"
        className="fixed inset-y-0 right-0 z-40 flex w-[min(26rem,100vw)] animate-sheet-right flex-col border-l border-border bg-surface shadow-2xl"
      >
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <span aria-hidden="true" className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent-soft">
            <Sparkles className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-title">Ask PeakSift</h2>
            {header}
          </div>
          {clearButton}
          <IconButton aria-label="Close Ask PeakSift" size="sm" onClick={closeCopilot}>
            <X aria-hidden="true" />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {body}
        </div>
        <div className="border-t border-border px-4 py-3">{composerBlock}</div>
      </aside>
      {confirm}
    </>
  );
}

function Welcome({
  page,
  hasSource,
  scope,
  onAsk,
  disabled,
}: {
  page: CopilotScope["page"];
  hasSource: boolean | null;
  scope: string;
  onAsk: (text: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="space-y-4">
      <div>
        <p className="text-title">Ask about {scope}</p>
        <p className="mt-1 text-sm text-pretty text-muted">
          PeakSift answers from your own projects, moments, Shorts and analytics — not the internet. It suggests;
          you decide and click.
        </p>
      </div>
      <ul className="flex flex-col gap-2" aria-label="Suggested questions">
        {starters(page, hasSource).map((text) => (
          <li key={text}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onAsk(text)}
              className="flex min-h-11 w-full items-center rounded-xl border border-border bg-surface-2 px-3.5 py-2 text-left text-sm text-foreground transition-colors hover:border-border-strong hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60"
            >
              {text}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Waiting({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(startedAt);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 400);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-muted">
      <Spinner />
      {waitingText(now - startedAt)}
    </p>
  );
}

function Message({
  message,
  busyAction,
  actionErrors,
  onAction,
}: {
  message: CopilotMessage;
  busyAction: string | null;
  actionErrors: Record<string, string>;
  onAction: (action: CopilotAction) => void;
}) {
  if (message.role === "user") {
    return (
      <article aria-label="Your question" className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-accent/15 px-3.5 py-2.5 text-sm break-words whitespace-pre-wrap text-foreground">
        {message.content}
      </article>
    );
  }
  const inCards = new Set(message.cards.map((card) => card.action).filter((i): i is number => i !== null));
  const actions = message.actions.filter((action) => !inCards.has(action.index));
  return (
    <article aria-label="PeakSift's answer" className="space-y-3">
      <p dir="auto" className={`text-sm leading-relaxed break-words text-pretty ${message.status === "ok" ? "text-foreground" : "text-muted"}`}>
        {message.content}
      </p>
      {message.suggestion ? (
        <div className="rounded-xl border border-accent/25 bg-accent/[0.05] px-3.5 py-2.5">
          <p className="text-caption font-medium text-accent-soft">Suggestion</p>
          <p dir="auto" className="mt-0.5 text-sm text-pretty text-foreground">{message.suggestion}</p>
        </div>
      ) : null}
      {message.cards.length ? (
        <ul className="space-y-2" aria-label="Short ideas">
          {message.cards.map((card, index) => (
            <li key={`${card.time}-${index}`} className="rounded-xl border border-border bg-surface-2 px-3.5 py-3">
              <p className="flex items-start gap-2 text-sm font-medium text-foreground">
                <Lightbulb aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-accent-soft" />
                <span dir="auto" className="min-w-0 break-words">{card.title}</span>
              </p>
              <p className="mt-1 text-caption text-subtle">
                {[card.time, card.angle, card.style ? `Suggested style: ${card.style[0].toUpperCase()}${card.style.slice(1)}` : null]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              {card.why ? <p dir="auto" className="mt-1 text-small text-pretty text-muted">{card.why}</p> : null}
              {card.note ? <p className="mt-1 text-small text-amber-200">{card.note}</p> : null}
              {card.action !== null && message.actions[card.action] ? (
                <div className="mt-2">
                  <ActionButton message={message} action={message.actions[card.action]} busyAction={busyAction} error={actionErrors[`${message.id}:${card.action}`]} onAction={onAction} />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {message.references.length ? (
        <p className="flex flex-wrap items-center gap-1.5 text-caption text-subtle">
          <span>Based on</span>
          {message.references.map((ref) => (
            <span key={`${ref.kind}-${ref.label}`} className="max-w-full truncate rounded-full bg-surface-3 px-2 py-0.5 text-muted">
              {ref.label}
            </span>
          ))}
        </p>
      ) : null}
      {actions.length ? (
        <div className="flex flex-col items-start gap-2">
          {actions.map((action) => (
            <ActionButton key={action.index} message={message} action={action} busyAction={busyAction} error={actionErrors[`${message.id}:${action.index}`]} onAction={onAction} />
          ))}
        </div>
      ) : null}
    </article>
  );
}

function ActionButton({
  message,
  action,
  busyAction,
  error,
  onAction,
}: {
  message: CopilotMessage;
  action: CopilotAction;
  busyAction: string | null;
  error?: string;
  onAction: (action: CopilotAction) => void;
}) {
  const busy = busyAction === `${message.id}:${action.index}`;
  return (
    <div className="max-w-full">
      <Button size="sm" variant="secondary" onClick={() => onAction(action)} disabled={busyAction !== null} className="max-w-full">
        <span className="truncate">{busy ? "Opening…" : action.label}</span>
      </Button>
      {error ? <p role="alert" className="mt-1 text-small text-amber-200">{error}</p> : null}
    </div>
  );
}

function Composer({
  inputRef,
  value,
  onChange,
  onKeyDown,
  onSubmit,
  disabled,
  placeholder,
}: {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmit: () => void;
  disabled: boolean;
  placeholder: string;
}) {
  const id = useId();
  const note = lengthNote(value);
  const rows = Math.min(5, Math.max(1, value.split("\n").length));
  return (
    <form
      className="w-full"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label htmlFor={id} className="sr-only">
        Ask PeakSift
      </label>
      <div className="flex items-end gap-2 rounded-2xl border border-border-strong bg-surface-2 p-1.5 focus-within:border-accent/60">
        <textarea
          ref={inputRef}
          id={id}
          dir="auto"
          value={value}
          rows={rows}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-describedby={note ? `${id}-note` : undefined}
          className="min-h-9 w-full resize-none bg-transparent px-2 py-1.5 pointer-coarse:min-h-11 text-base text-foreground outline-none placeholder:text-subtle sm:text-sm"
        />
        <IconButton
          type="submit"
          variant="secondary"
          aria-label="Send question"
          disabled={disabled || !value.trim() || charCount(value) > QUESTION_MAX}
          className="shrink-0 bg-foreground text-background hover:bg-zinc-200 disabled:bg-surface-3 disabled:text-subtle"
        >
          <ArrowUp aria-hidden="true" />
        </IconButton>
      </div>
      {note ? (
        <p id={`${id}-note`} className={`mt-1 text-right text-caption ${value.length > QUESTION_MAX ? "text-amber-200" : "text-subtle"}`}>
          {note}
        </p>
      ) : null}
    </form>
  );
}
