import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/notifications/notifications.js', import.meta.url), 'utf8');
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

function setup(fetch) {
    const elements = new Map();
    const timers = new Map();
    const listeners = new Map();
    let timerId = 0;
    const element = () => ({
        hidden: true, textContent: '', children: [],
        dataset: { listUrl: '/api/notifications' },
        setAttribute() {}, addEventListener() {},
        replaceChildren() { this.children = []; },
        append(...children) { this.children.push(...children); },
        appendChild(child) { this.children.push(child); },
    });
    const document = {
        title: 'Sentinel', hidden: false,
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, element());
            return elements.get(id);
        },
        createElement: element,
        addEventListener(name, handler) { listeners.set(name, handler); },
    };
    const window = {
        setTimeout(fn, delay) { timers.set(++timerId, { fn, delay }); return timerId; },
        clearTimeout(id) { timers.delete(id); },
        addEventListener(name, handler) { listeners.set(name, handler); },
    };
    vm.runInNewContext(source, { document, window, fetch, AbortController });
    return {
        elements, timers, listeners,
        fireTimer() {
            const [id, timer] = timers.entries().next().value;
            timers.delete(id);
            timer.fn();
            return timer.delay;
        },
    };
}

function pendingUntilAbort(signal) {
    return new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    });
}

test('a pending request times out and releases the in-flight guard for retry', async () => {
    let calls = 0;
    const ui = setup((url, { signal }) => { calls++; return pendingUntilAbort(signal); });
    ui.listeners.get('online')();
    assert.equal(calls, 1);
    assert.equal(ui.fireTimer(), 10000);
    await settle();
    assert.match(ui.elements.get('notificationSummary').textContent, /Reconectando/);
    assert.equal(ui.fireTimer(), 10000);
    assert.equal(calls, 2);
});

test('the timeout also covers a response body that never finishes', async () => {
    const ui = setup(async (url, { signal }) => ({
        ok: true, json: () => pendingUntilAbort(signal),
    }));
    await settle();
    ui.fireTimer();
    await settle();
    assert.match(ui.elements.get('notificationSummary').textContent, /Reconectando/);
    assert.equal(ui.timers.size, 1);
});

test('successful requests clear the timeout and retain the normal polling interval', async () => {
    const ui = setup(async () => ({ ok: true, json: async () => ({ notifications: [], unread_count: 0 }) }));
    await settle();
    assert.equal(ui.elements.get('notificationSummary').textContent, '0 alertas ativos');
    assert.equal(ui.timers.size, 1);
    assert.equal([...ui.timers.values()][0].delay, 30000);
});

test('a later timeout keeps previously loaded alerts visible', async () => {
    let calls = 0;
    const ui = setup(async (url, { signal }) => {
        if (calls++ > 0) return pendingUntilAbort(signal);
        return { ok: true, json: async () => ({
            notifications: [{ id: 'test', title: 'Alerta', message: 'Teste', read: true }], unread_count: 0,
        }) };
    });
    await settle();
    assert.equal(ui.elements.get('notificationList').children.length, 1);
    ui.fireTimer();
    await settle();
    ui.fireTimer();
    await settle();
    assert.equal(ui.elements.get('notificationList').children.length, 1);
    assert.match(ui.elements.get('notificationSummary').textContent, /Reconectando; exibindo/);
});
