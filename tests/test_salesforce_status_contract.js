'use strict';

// Pure normalization regressions. These execute the actual Core; there are no
// platform mocks, database writes, network calls, fixtures, or credentials.
const assert = require('assert');
const Core = require('../src/USBEM_Core.js');

let passed = 0;
function test(name, run) {
    run();
    passed++;
    console.log('PASS ' + name);
}

function normalize(payload, envelope) {
    return new Core().createRecordContext(payload, envelope || {});
}

function sf(fields) {
    return Object.assign({ case_number: 'USBEM-SF-STATUS-REGRESSION', subject: 'Retained ordinary case' }, fields || {});
}

function assertCase(ctx, severity, resolution) {
    assert.strictEqual(ctx.mapped.severity, severity);
    assert.strictEqual(ctx.mapped.resolution_state, resolution);
    assert.strictEqual(ctx.mapped.source, 'salesforce');
    assert.strictEqual(ctx.mapped.event_class, 'salesforce');
    assert.strictEqual(ctx.mapped.type, 'peru');
    assert.strictEqual(ctx.flags.wait_requested, false);
    assert.strictEqual(ctx.flags.direct_to_incident, false);
}

for (const statusField of ['status', 'case_status', 'case status', 'casestatus', 'caseStatus',
    'salesforce_case_status', 'sf_case_status']) {
    test(statusField + '=Closed produces Clear severity and Closing', () => {
        assertCase(normalize(sf({ [statusField]: 'Closed' })), '0', 'Closing');
    });
}

for (const closed of ['Closed', 'Close', 'Resolved', 'Cleared', 'Clear']) {
    test('consumed generic status=' + closed + ' retains closed severity inference', () => {
        assertCase(normalize(sf({ status: closed })), '0', 'Closing');
    });
}

for (const wrapper of ['event', 'payload', 'data', 'record', 'alert']) {
    test(wrapper + ' wrapped generic Closed status is recovered', () => {
        assertCase(normalize({ [wrapper]: sf({ status: 'Closed' }) }), '0', 'Closing');
    });
    for (const infoKey of ['additional_info', 'additionalInfo']) {
        for (const encoded of [false, true]) {
            test(wrapper + '.' + infoKey + ' ' + (encoded ? 'JSON string' : 'object') +
                ' generic Closed status is recovered without changing native context', () => {
                const info = sf({ status: 'Closed', custom_context: { retained: true, count: 7 } });
                const value = encoded ? JSON.stringify(info) : info;
                const ctx = normalize({ [wrapper]: { [infoKey]: value } });
                assertCase(ctx, '0', 'Closing');
                assert.deepStrictEqual(ctx.user_additional_info.custom_context, { retained: true, count: 7 });
            });
        }
    }
}

for (const infoKey of ['additional_info', 'additionalInfo']) {
    for (const encoded of [false, true]) {
        test(infoKey + ' ' + (encoded ? 'JSON string' : 'object') + ' root generic Closed status is recovered', () => {
            const info = sf({ status: 'Closed' });
            assertCase(normalize({ [infoKey]: encoded ? JSON.stringify(info) : info }), '0', 'Closing');
        });
        test(infoKey + ' ' + (encoded ? 'JSON string' : 'object') + ' case-specific status beats original root status', () => {
            const info = sf({ case_status: 'Open' });
            const ctx = normalize({ status: 'Closed', [infoKey]: encoded ? JSON.stringify(info) : info });
            // Generic mapped resolution remains explicit; it is not rewritten by case inference.
            assertCase(ctx, '3', 'Closing');
        });
        test(infoKey + ' ' + (encoded ? 'JSON string' : 'object') + ' original AI generic status beats original root fallback', () => {
            const info = sf({ status: 'Closed' });
            const ctx = normalize({ status: 'Open', [infoKey]: encoded ? JSON.stringify(info) : info });
            assertCase(ctx, '0', 'New');
        });
    }
}

test('blank root generic status does not hide canonical Closed case status', () => {
    assertCase(normalize(sf({ status: '', case_status: 'Closed' })), '0', 'Closing');
});

test('canonical Open case status remains authoritative over consumed generic Closed', () => {
    assertCase(normalize(sf({ status: 'Closed', case_status: 'Open' })), '3', 'Closing');
});

test('canonical Closed case status remains authoritative over consumed generic Open', () => {
    assertCase(normalize(sf({ status: 'Open', case_status: 'Closed' })), '0', 'New');
});

test('blank case-specific status allows original generic Closed recovery', () => {
    assertCase(normalize(sf({ status: 'Closed', case_status: '' })), '0', 'Closing');
});

for (const severity of ['1', '2', '3', '4', '5']) {
    test('explicit severity ' + severity + ' is not replaced by Closed inference', () => {
        assertCase(normalize(sf({ status: 'Closed', severity })), severity, 'Closing');
    });
}

test('explicit severity and resolution are both preserved', () => {
    assertCase(normalize(sf({ status: 'Closed', severity: 'warning', resolution_state: 'New' })), '4', 'New');
});

test('explicit Event source, type, description, key, and resource remain unchanged', () => {
    const ctx = normalize(sf({ status: 'Closed', source: 'explicit-source', event_class: 'explicit-class',
        type: 'explicit-type', description: 'explicit-description', message_key: 'explicit-key', resource: 'explicit-resource' }));
    assert.strictEqual(ctx.mapped.severity, '0');
    assert.strictEqual(ctx.mapped.resolution_state, 'Closing');
    for (const [field, expected] of Object.entries({ source: 'explicit-source', event_class: 'explicit-class',
        type: 'explicit-type', description: 'explicit-description', message_key: 'explicit-key', resource: 'explicit-resource' })) {
        assert.strictEqual(ctx.mapped[field], expected);
    }
});

test('Open ordinary case retains Minor severity', () => {
    assertCase(normalize(sf({ status: 'Open' })), '3', 'New');
});

test('Open outage case retains Major inference', () => {
    assertCase(normalize(sf({ status: 'Open', subject: 'Major outage' })), '2', 'New');
});

test('Closed outage case must clear rather than infer Major from its subject', () => {
    assertCase(normalize(sf({ status: 'Closed', subject: 'Major outage' })), '0', 'Closing');
});

test('case number plus Closed status remains enough to recognize Salesforce without subject', () => {
    const ctx = normalize({ case_number: 'USBEM-CLOSED-NO-SUBJECT', status: 'Closed' });
    assertCase(ctx, '0', 'Closing');
    assert.strictEqual(ctx.mapped.description, 'Salesforce case USBEM-CLOSED-NO-SUBJECT');
});

test('plain non-Salesforce Closed Event retains generic defaults', () => {
    const ctx = normalize({ source: 'plain-regression', message_key: 'USBEM-PLAIN-CLOSED', status: 'Closed' });
    assert.strictEqual(ctx.mapped.severity, '5');
    assert.strictEqual(ctx.mapped.resolution_state, 'Closing');
    assert.strictEqual(ctx.mapped.source, 'plain-regression');
    assert.strictEqual(ctx.mapped.event_class, 'plain-regression');
    assert.strictEqual(ctx.mapped.type, undefined);
});

test('subject and Closed status without a case number is not Salesforce', () => {
    const ctx = normalize({ subject: 'Ordinary subject', status: 'Closed' });
    assert.strictEqual(ctx.mapped.source, 'GenericJSON');
    assert.strictEqual(ctx.mapped.severity, '5');
    assert.strictEqual(ctx.mapped.resolution_state, 'Closing');
    assert.strictEqual(ctx.mapped.type, undefined);
});

console.log('Salesforce status contract: ' + passed + ' cases passed');
