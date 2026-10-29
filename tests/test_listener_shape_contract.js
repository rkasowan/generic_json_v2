'use strict';

// Execute the actual listener with a recording platform adapter. No network or Glide writes.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const USBEM_Core = require('../src/USBEM_Core.js');
const source = fs.readFileSync(path.join(__dirname, '../servicenow/USBEM_genericJsonV2.listener.js'), 'utf8');
let passed = 0;

function execute(body) {
    const inserts = [];
    const errors = [];
    class RecordingCore extends USBEM_Core {
        createRecordContext(event, envelope) {
            const ctx = super.createRecordContext(event, envelope);
            ctx.testEvent = event;
            ctx.testEnvelope = envelope;
            return ctx;
        }
        addOperationalAdditionalInfo() { return {}; }
        insertEventRecord(ctx) {
            inserts.push({event: ctx.testEvent, envelope: ctx.testEnvelope});
            ctx.result.status = 'success';
            ctx.result.event_sys_id = inserts.length.toString(16).padStart(32, '0');
            ctx.result.message_key = ctx.mapped.message_key;
        }
        finalizeContext() {}
    }
    const context = {
        body, request: {}, status: 200,
        gs: {error: value => errors.push(String(value))},
        x_usbna_usb_event: {
            USBEM_Core: RecordingCore,
            USBEM_Lookups: class { resolveAll() {} },
            USBEM_Debug: class { createDebugEvent() { return ''; } },
            USBEM_DTI: class { handlePostInsert() {} }
        }
    };
    const result = JSON.parse(vm.runInNewContext(source, context));
    return {result, inserts, errors, status: context.status};
}

function test(name, run) {
    run();
    passed++;
    console.log('PASS ' + name);
}

for (const value of [null, 42, true, false, 'text']) {
    for (const wire of [value, JSON.stringify(value)]) {
        test('reject scalar/null shape ' + JSON.stringify(wire), () => {
            const actual = execute(wire);
            assert.strictEqual(actual.result.status, 'error');
            assert.match(actual.result.message, /Payload must be a JSON object|SyntaxError/);
            assert.strictEqual(actual.status, 500);
            assert.strictEqual(actual.inserts.length, 0);
        });
    }
}

for (const container of ['records', 'events']) {
    for (const member of [null, 42, false, 'text', []]) {
        test(container + ' validates every member before any insert: ' + JSON.stringify(member), () => {
            const actual = execute({[container]: [{message_key: 'would-have-inserted'}, member]});
            assert.strictEqual(actual.result.status, 'error');
            assert.match(actual.result.message, /Event at index 1 must be a JSON object/);
            assert.strictEqual(actual.inserts.length, 0);
        });
    }
    for (const value of [null, {}, 42, 'text']) {
        test(container + ' must be an array: ' + JSON.stringify(value), () => {
            const actual = execute({[container]: value});
            assert.strictEqual(actual.result.status, 'error');
            assert.strictEqual(actual.inserts.length, 0);
        });
    }
}

test('bare array validates all members before first insert', () => {
    const actual = execute([{message_key: 'first'}, null]);
    assert.strictEqual(actual.result.status, 'error');
    assert.strictEqual(actual.inserts.length, 0);
});
test('malformed JSON returns an explicit error without inserts', () => {
    const actual = execute('{"broken":');
    assert.strictEqual(actual.result.status, 'error');
    assert.strictEqual(actual.inserts.length, 0);
});
test('flat object still inserts one event', () => {
    const actual = execute({message_key: 'flat'});
    assert.strictEqual(actual.result.status, 'success');
    assert.strictEqual(actual.result.inserted, '1');
    assert.strictEqual(actual.result.message_key, 'flat');
});
test('empty object and empty batch keep their existing supported behavior', () => {
    assert.strictEqual(execute({}).result.inserted, '1');
    assert.strictEqual(execute([]).result.inserted, '0');
    assert.strictEqual(execute({records: []}).result.inserted, '0');
});
for (const container of ['records', 'events']) {
    test(container + ' preserves envelope defaults and member overrides', () => {
        const actual = execute({source: 'envelope', [container]: [
            {message_key: 'one'}, {message_key: 'two', source: 'member'}
        ]});
        assert.strictEqual(actual.result.status, 'success');
        assert.strictEqual(actual.result.inserted, '2');
        assert.deepStrictEqual(actual.result.results.map(row => row.message_key), ['one', 'two']);
        assert.strictEqual(actual.inserts[0].envelope.source, 'envelope');
    });
}
for (const wrapper of ['event', 'payload', 'data', 'record', 'alert']) {
    test('supported one-level wrapper remains accepted: ' + wrapper, () => {
        const actual = execute({[wrapper]: {message_key: wrapper}});
        assert.strictEqual(actual.result.status, 'success');
        assert.strictEqual(actual.result.message_key, wrapper);
    });
}

console.log('Listener shape contract tests passed: ' + passed + ' cases');
