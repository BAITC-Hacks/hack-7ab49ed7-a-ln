import { useState, type FormEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import { api } from '../api/client';
import type { AssistantAction, AssistantAnswer, AssistantMode } from '../api/types';
import { useTask } from '../hooks/useTask';
import { Empty, ErrorView, Gid, Loading, Warnings } from './Common';
import s from './Panels.module.css';

export interface AssistantCallbacks {
  select: (id: string) => void;
  action: (action: AssistantAction) => void;
  highlight: (highlight: AssistantAnswer['highlight']) => void;
  preview: (highlight: AssistantAnswer['highlight'] | null) => void;
}
export function SafeMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      skipHtml
      allowedElements={[
        'p',
        'strong',
        'em',
        'ul',
        'ol',
        'li',
        'blockquote',
        'code',
        'pre',
        'h1',
        'h2',
        'h3',
        'h4',
        'hr',
        'br',
      ]}
      unwrapDisallowed
    >
      {text}
    </ReactMarkdown>
  );
}
export function AssistantPanel({
  runId,
  llmEnabled,
  callbacks,
}: {
  runId: string;
  llmEnabled: boolean;
  callbacks: AssistantCallbacks;
}) {
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<AssistantMode>('auto');
  const task = useTask<AssistantAnswer>();
  const ask = async (text: string) => {
    setQuestion(text);
    callbacks.preview(null);
    const answer = await task.execute((signal) => api.assistant(runId, text, mode, signal));
    if (answer) callbacks.preview(answer.highlight);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (question.trim() && !task.pending) void ask(question.trim());
  };
  return (
    <section className={s.assistant}>
      <div>
        <span className={s.eyebrow}>Помощник аналитика</span>
        <h3>Вопросы к данным</h3>
      </div>
      <p>Попросите объяснить роль, найти путь или общий узел, собирающий переводы.</p>
      <form onSubmit={submit}>
        <label>
          Ваш вопрос
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (question.trim() && !task.pending) void ask(question.trim());
              }
            }}
            aria-describedby="assistant-keyboard-hint"
            placeholder="Почему этот клиент в приоритетном списке?"
            maxLength={2000}
            required
          />
        </label>
        <small id="assistant-keyboard-hint">Ctrl/⌘ + Enter — отправить · Enter — новая строка</small>
        <div className={s.buttonRow}>
          <label>
            Режим
            <select value={mode} onChange={(e) => setMode(e.target.value as AssistantMode)}>
              <option value="auto">Автоматически</option>
              <option value="offline">Локальный</option>
              {llmEnabled && <option value="llm">LLM</option>}
            </select>
          </label>
          <button className="primary" disabled={!question.trim() || task.pending}>
            Задать вопрос
          </button>
          {task.pending && (
            <button type="button" onClick={task.reset}>
              Отменить
            </button>
          )}
        </div>
      </form>
      {llmEnabled && mode !== 'offline' && (
        <Warnings
          items={['В этом режиме сервер может передать вопрос и сведения о графе внешней языковой модели.']}
        />
      )}
      <div className={s.suggestions}>
        {(task.data?.suggestions ?? ['топ 5 консолидаторов', 'топ 10 координаторов']).map((text) => (
          <button key={text} onClick={() => void ask(text)} disabled={task.pending}>
            {text}
          </button>
        ))}
      </div>
      {task.pending && <Loading label="Поиск ответа в графе…" />}
      {task.error && <ErrorView error={task.error} />}{' '}
      {!task.pending && !task.data && !task.error && (
        <Empty>Ответ появится здесь. Ссылки на клиентов откроют их карточки.</Empty>
      )}
      {task.data && <AssistantResult answer={task.data} callbacks={callbacks} />}
    </section>
  );
}
function AssistantResult({ answer, callbacks }: { answer: AssistantAnswer; callbacks: AssistantCallbacks }) {
  return (
    <div className={s.answer} aria-live="polite">
      <span className={s.eyebrow}>
        {answer.mode_used === 'llm' ? 'Ответ языковой модели' : 'Ответ по локальным правилам'}
      </span>
      <Warnings items={answer.warnings} />
      <SafeMarkdown text={answer.answer_markdown} />
      {answer.citations.map((c) => (
        <div key={c.id} className={s.citation}>
          <Gid id={c.id} onSelect={callbacks.select} />
          <p>{c.note}</p>
        </div>
      ))}
      {answer.candidates.map((c) => (
        <div key={c.fragment}>
          <h4>Уточните ID «{c.fragment}»</h4>
          {c.ids.map((id) => (
            <div key={id}>
              <Gid id={id} onSelect={callbacks.select} />
            </div>
          ))}
        </div>
      ))}
      <div className={s.suggestions}>
        {answer.actions.map((action, i) => (
          <button key={`${action.type}:${i}`} onClick={() => callbacks.action(action)}>
            {action.label}
          </button>
        ))}
        {answer.highlight.nodes.length > 0 && (
          <button onClick={() => callbacks.highlight(answer.highlight)}>Показать на графе</button>
        )}
      </div>
    </div>
  );
}
