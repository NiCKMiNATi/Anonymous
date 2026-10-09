// REVIEW ONLY. Assertions describe required behavior; known defects intentionally fail.
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { FakeBackend } from '../src/test/fakeBackend';

let backend: FakeBackend;
beforeEach(() => {
  backend = new FakeBackend();
  vi.stubGlobal('fetch', backend.fetch);
  window.history.replaceState(null, '', '/');
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('R1: completing a send in A must not replace the selected B view or retarget the composer', async () => {
  const b = backend.seed('Beta');
  backend.seed('Alpha');
  let release!: () => void;
  backend.holdSends = new Promise<void>(resolve => { release = resolve; });
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Message'), 'first{Enter}');
  await user.click(screen.getByRole('button', { name: /Beta/ }));
  await screen.findByRole('heading', { name: 'Beta', level: 2 });
  await act(async () => release());
  await waitFor(() => expect(backend.details.get(backend.conversations[0]!.id)!.messages).toHaveLength(2));
  await waitFor(() => expect(document.querySelector('.message--pending')).toBeNull());
  // Allow the completion-triggered history GET to finish deterministically.
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); });
  expect(window.location.hash).toContain(b.id);
  expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Beta');
});

it('R1: an older refresh response must not erase newly confirmed history', async () => {
  const c = backend.seed('Refresh race');
  const user = userEvent.setup();
  render(<App />);
  await screen.findByLabelText('Message');
  const oldResponse = await backend.fetch(`/api/v1/conversations/${c.id}`);
  let release!: (r: Response) => void;
  let held = false;
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    if (!held && String(input) === `/api/v1/conversations/${c.id}` && !init?.method) {
      held = true;
      return new Promise<Response>(resolve => { release = resolve; });
    }
    return backend.fetch(input, init);
  });
  await user.click(screen.getByRole('button', { name: 'Refresh' }));
  await user.type(screen.getByLabelText('Message'), 'new fact{Enter}');
  await screen.findByText('Fake reply to: new fact');
  await act(async () => release(oldResponse));
  expect(backend.details.get(c.id)!.messages).toHaveLength(2);
  expect(screen.queryByText('Fake reply to: new fact')).not.toBeNull();
});

it('R2: discard after lost acknowledgment must not restore already-saved text as a fresh send', async () => {
  const c = backend.seed('Lossy');
  backend.loseNextAcknowledgment = true;
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Message'), 'one intent{Enter}');
  await screen.findByText('Not confirmed saved');
  await user.click(screen.getByRole('button', { name: 'Discard and reload' }));
  await screen.findByText('Fake reply to: one intent');
  // The current implementation restores the draft and silently loses correlation.
  // Clicking Send on that restored text must not duplicate the unresolved original intent.
  await user.click(screen.getByRole('button', { name: 'Send' }));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); });
  expect(backend.details.get(c.id)!.messages.filter(m => m.role === 'user')).toHaveLength(1);
});

it('R3: malformed percent encoding in a conversation hash must not crash rendering', () => {
  window.history.replaceState(null, '', '/#/c/%');
  expect(() => render(<App />)).not.toThrow();
});

it('R4: initial HTTP 503 must offer an in-app reload path', async () => {
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({error: {
    code: 'storage_unavailable', message: 'Storage temporarily unavailable.'
  }}), { status: 503 }));
  render(<App />);
  await screen.findByRole('alert');
  expect(screen.queryByRole('button', { name: /Retry|Refresh/ })).not.toBeNull();
});

it('double-clicking Send produces one logical submission', async () => {
  backend.seed('Double click');
  let release!: () => void;
  backend.holdSends = new Promise<void>(resolve => { release = resolve; });
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Message'), 'once');
  await user.dblClick(screen.getByRole('button', { name: 'Send' }));
  expect(backend.sendCalls).toHaveLength(1);
  await act(async () => release());
  await screen.findByText('Fake reply to: once');
});

it('a failed generation reply lost in transit is replayed without a fresh user message', async () => {
  const c = backend.seed('Failed acknowledgment');
  backend.failGeneration = true;
  backend.loseNextAcknowledgment = true;
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Message'), 'fail once{Enter}');
  await screen.findByText('Not confirmed saved');
  await user.click(screen.getByRole('button', { name: 'Retry sending' }));
  await screen.findByText('Response failed.');
  expect(backend.sendCalls[0]!.submissionId).toBe(backend.sendCalls[1]!.submissionId);
  expect(backend.details.get(c.id)!.messages).toHaveLength(1);
});
