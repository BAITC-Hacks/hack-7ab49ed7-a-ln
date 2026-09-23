import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { AssistantPanel, SafeMarkdown } from './AssistantPanel';

it('renders formatting without HTML, executable links or remote images', () => {
  const { container } = render(
    <SafeMarkdown
      text={
        '**Проверить** <script>alert(1)</script> [ссылка](javascript:alert(1)) ![tracking](https://example.test/pixel) <img src=x onerror=alert(1)>'
      }
    />,
  );
  expect(screen.getByText('Проверить').tagName).toBe('STRONG');
  expect(container.querySelector('script,img,a,iframe')).toBeNull();
});

it.each(['ctrlKey', 'metaKey'])(
  'submits with %s+Enter, preserves newlines and previews highlights',
  async (modifier) => {
    const callbacks = { select: vi.fn(), action: vi.fn(), highlight: vi.fn(), preview: vi.fn() };
    render(
      <AssistantPanel
        runId="00000000-0000-4000-8000-000000000001"
        llmEnabled={false}
        callbacks={callbacks}
      />,
    );
    const input = screen.getByRole('textbox', { name: 'Ваш вопрос' });
    await userEvent.type(input, 'топ 5 консолидаторов{Enter}');
    expect(input).toHaveValue('топ 5 консолидаторов\n');
    expect(callbacks.preview).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter', [modifier]: true });
    await waitFor(() => expect(screen.getByText('Ответ по локальным правилам')).toBeInTheDocument());
    expect(callbacks.preview).toHaveBeenLastCalledWith(expect.objectContaining({ nodes: expect.any(Array) }));
    await userEvent.click(screen.getByRole('button', { name: 'Показать на графе' }));
    expect(callbacks.highlight).toHaveBeenCalledWith(callbacks.preview.mock.lastCall?.[0]);
  },
);
