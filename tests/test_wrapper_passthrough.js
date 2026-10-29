'use strict';

// Local behavior tests: real Core normalization and DTI field/note writers, with
// a minimal Incident field adapter. Live dictionary, ACLs and alert processing
// must still be exercised by the release gate on the target instance.
const assert = require('assert');
const USBEM_Core = require('../src/USBEM_Core.js');
const USBEM_DTI = require('../src/USBEM_DTI.js');

let passed = 0;
function test(name, run) {
    run();
    passed++;
    console.log('PASS ' + name);
}

const WRAPPERS = ['event', 'payload', 'data', 'record', 'alert'];
const CALLER_ID = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const GROUP_ID = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const REQUIRED = {
    caller_id: CALLER_ID,
    category: 'software',
    subcategory: 'os',
    impact: '2',
    urgency: '2',
    short_description: 'Wrapped Incident short description',
    description: 'Wrapped Incident detailed description'
};

function eventFields(overrides) {
    return Object.assign({
        source: 'wrapper-regression',
        messageKey: 'wrapper-regression-key',
        severity: '2',
        directToIncident: true,
        ciType: 'cmdb_ci_server',
        ciIdentifier: { serial_number: 'SERIAL-EXPECTED' },
        assignmentGroup: GROUP_ID,
        work_notes: 'Wrapped sender work note',
        custom_context: { nested: { category: 'not-an-Incident-field' } }
    }, REQUIRED, overrides || {});
}

function normalize(raw, envelope) {
    return new USBEM_Core().createRecordContext(raw, envelope);
}

function incidentFromContext(ctx) {
    const core = new USBEM_Core();
    const dti = new USBEM_DTI(core);
    const values = {
        description: ctx.mapped.description,
        short_description: ctx.special.dti_short_description,
        impact: ctx.dti.impact,
        urgency: ctx.dti.urgency,
        cmdb_ci: ctx.resolved.cmdb_ci_sys_id || ctx.mapped.cmdb_ci || '',
        assignment_group: ctx.resolved.assignment_group_sys_id || ctx.special.assignment_group || ''
    };
    const validFields = new Set(Object.keys(REQUIRED).concat([
        'contact_type', 'work_notes', 'cmdb_ci', 'assignment_group'
    ]));
    const inc = {
        isValidField: field => validFields.has(field),
        setValue: (field, value) => { values[field] = String(value); },
        getValue: field => values[field] || '',
        getElement: field => ({ setDisplayValue: value => { values[field] = String(value); } })
    };
    dti.applyRequestedIncidentFields(inc, ctx);
    values.work_notes = dti.buildCreationWorkNote(ctx, null);
    return values;
}

function assertRequiredFields(ctx) {
    const values = incidentFromContext(ctx);
    for (const field of Object.keys(REQUIRED)) {
        assert.strictEqual(values[field], REQUIRED[field], field + ' was lost or overridden');
    }
    assert.ok(values.work_notes.includes('Wrapped sender work note'));
    assert.strictEqual(ctx.flags.direct_to_incident, true);
    assert.strictEqual(ctx.flags.wait_requested, false);
    assert.strictEqual(ctx.special.assignment_group, GROUP_ID);
    assert.strictEqual(ctx.mapped.ci_type, 'cmdb_ci_server');
    assert.deepStrictEqual(ctx.ci_identifier_obj, { serial_number: 'SERIAL-EXPECTED' });
}

test('flat payload retains all seven required fields and sender work notes', () => {
    assertRequiredFields(normalize(eventFields()));
});

for (const wrapper of WRAPPERS) {
    test(wrapper + ' wrapper retains all seven required fields and sender work notes', () => {
        const ctx = normalize({ [wrapper]: eventFields() });
        assertRequiredFields(ctx);
        assert.deepStrictEqual(ctx.user_additional_info.custom_context,
            { nested: { category: 'not-an-Incident-field' } });
        assert.strictEqual(ctx.user_additional_info[wrapper], undefined);
    });

    test(wrapper + ' per-record Incident overrides beat flat envelope defaults', () => {
        const ctx = normalize({ [wrapper]: eventFields() }, {
            caller_id: 'cccccccccccccccccccccccccccccccc',
            category: 'envelope-category', subcategory: 'envelope-subcategory',
            impact: '4', urgency: '4', short_description: 'envelope-short',
            description: 'envelope Event description', work_notes: 'envelope-note',
            custom_envelope: 'preserved'
        });
        const values = incidentFromContext(ctx);
        for (const field of Object.keys(REQUIRED).filter(field => field !== 'description')) {
            assert.strictEqual(values[field], REQUIRED[field], field);
        }
        // Existing mapped alias selection remains root-first even across layers.
        assert.strictEqual(ctx.mapped.description, 'envelope Event description');
        assert.strictEqual(values.description, 'envelope Event description');
        assert.ok(values.work_notes.includes('Wrapped sender work note'));
        assert.strictEqual(ctx.user_additional_info.custom_envelope, 'preserved');
    });

    test(wrapper + ' losing Event aliases cannot overwrite selected outer Incident routing', () => {
        const ctx = normalize({
            description: 'outer Event description', cmdbCi: CALLER_ID,
            assignmentGroup: GROUP_ID,
            [wrapper]: {
                description: 'inner Event description', short_description: 'inner Incident short',
                cmdb_ci: 'cccccccccccccccccccccccccccccccc',
                assignment_group: 'dddddddddddddddddddddddddddddddd'
            }
        });
        const values = incidentFromContext(ctx);
        assert.strictEqual(values.description, 'outer Event description');
        assert.strictEqual(values.short_description, 'inner Incident short');
        assert.strictEqual(values.cmdb_ci, CALLER_ID);
        assert.strictEqual(values.assignment_group, GROUP_ID);
    });

    test(wrapper + ' Event description plus Incident short_description matches flat behavior', () => {
        const fields = eventFields();
        const flat = incidentFromContext(normalize(fields));
        const wrapped = incidentFromContext(normalize({ [wrapper]: fields }));
        assert.deepStrictEqual(wrapped, flat);
    });

    for (const additionalInfoAlias of ['additional_info', 'additionalInfo']) {
        for (const jsonEncoded of [false, true]) {
            test(wrapper + '.' + additionalInfoAlias + ' ' + (jsonEncoded ? 'JSON' : 'object') +
                ' promotes Event/SPECIAL fields and Incident passthrough', () => {
                const info = eventFields({ contact_type: 'monitoring' });
                const ctx = normalize({
                    [wrapper]: { [additionalInfoAlias]: jsonEncoded ? JSON.stringify(info) : info }
                });
                assertRequiredFields(ctx);
                assert.strictEqual(incidentFromContext(ctx).contact_type, 'monitoring');
                assert.deepStrictEqual(ctx.user_additional_info.custom_context,
                    { nested: { category: 'not-an-Incident-field' } });
                assert.strictEqual(ctx.user_additional_info[additionalInfoAlias], undefined);
            });

            test(wrapper + '.' + additionalInfoAlias + ' ' + (jsonEncoded ? 'JSON' : 'object') +
                ' per-record Incident overrides beat root additional_info envelope defaults', () => {
                const info = Object.assign({}, REQUIRED, { work_notes: 'record-AI-note' });
                const ctx = normalize({
                    [wrapper]: { [additionalInfoAlias]: jsonEncoded ? JSON.stringify(info) : info }
                }, { additional_info: {
                    caller_id: 'cccccccccccccccccccccccccccccccc',
                    category: 'envelope-category', subcategory: 'envelope-subcategory',
                    impact: '4', urgency: '4', short_description: 'envelope-short',
                    description: 'envelope AI Event description', work_notes: 'envelope-note',
                    custom_envelope: 'preserved'
                } });
                const values = incidentFromContext(ctx);
                for (const field of Object.keys(REQUIRED).filter(field => field !== 'description')) {
                    assert.strictEqual(values[field], REQUIRED[field], field);
                }
                assert.strictEqual(values.description, 'envelope AI Event description');
                assert.ok(values.work_notes.includes('record-AI-note'));
                assert.strictEqual(ctx.user_additional_info.custom_envelope, 'preserved');
            });
        }
    }
}

test('explicit outer Incident fields win over wrapper fields', () => {
    const ctx = normalize({
        category: 'outer-category',
        subcategory: 'outer-subcategory',
        caller_id: CALLER_ID,
        work_notes: 'outer-note',
        event: eventFields({ category: 'inner-category', work_notes: 'inner-note' })
    });
    assert.strictEqual(ctx.user_additional_info.category, 'outer-category');
    assert.strictEqual(ctx.user_additional_info.subcategory, 'outer-subcategory');
    assert.strictEqual(ctx.user_additional_info.work_notes, 'outer-note');
});

test('explicit blank, null and false outer context values are not replaced by wrappers', () => {
    const ctx = normalize({
        category: '', custom_null: null, custom_false: false,
        event: { category: 'inner-category', custom_null: 'inner', custom_false: true }
    });
    assert.strictEqual(ctx.user_additional_info.category, '');
    assert.strictEqual(ctx.user_additional_info.custom_null, null);
    assert.strictEqual(ctx.user_additional_info.custom_false, false);
});

test('competing wrappers follow event > payload > data > record > alert priority', () => {
    // Deliberately reverse input insertion order so JSON key order cannot choose a winner.
    const raw = {};
    for (const wrapper of WRAPPERS.slice().reverse()) {
        raw[wrapper] = { category: wrapper, [wrapper + '_context']: wrapper };
    }
    for (const wrapper of WRAPPERS) {
        const ctx = normalize(raw);
        assert.strictEqual(ctx.user_additional_info.category, wrapper);
        assert.strictEqual(ctx.user_additional_info[wrapper + '_context'], wrapper);
        delete raw[wrapper];
    }
});

test('outer camelCase Event and SPECIAL aliases beat inner snake_case aliases', () => {
    const ctx = normalize({
        ciType: 'cmdb_ci_linux_server',
        ciIdentifier: { serial_number: 'OUTER' },
        messageKey: 'outer-key',
        directToIncident: false,
        dtiShortDescription: 'outer-short',
        dtiImpact: '1',
        assignmentGroup: GROUP_ID,
        event: {
            ci_type: 'cmdb_ci_server',
            ci_identifier: { serial_number: 'INNER' },
            message_key: 'inner-key',
            direct_to_incident: true,
            dti_short_description: 'inner-short',
            dti_impact: '3',
            assignment_group: 'inner-group'
        }
    });
    assert.strictEqual(ctx.mapped.ci_type, 'cmdb_ci_linux_server');
    assert.deepStrictEqual(ctx.ci_identifier_obj, { serial_number: 'OUTER' });
    assert.strictEqual(ctx.mapped.message_key, 'outer-key');
    assert.strictEqual(ctx.flags.direct_to_incident, false);
    assert.strictEqual(ctx.special.dti_short_description, 'outer-short');
    assert.strictEqual(ctx.special.dti_impact, '1');
    assert.strictEqual(ctx.special.assignment_group, GROUP_ID);
});

test('outer camelCase aliases inside additional_info still beat its wrapped snake_case aliases', () => {
    const ctx = normalize({ additional_info: {
        ciType: 'cmdb_ci_linux_server', directToIncident: false,
        event: { ci_type: 'cmdb_ci_server', direct_to_incident: true }
    } });
    assert.strictEqual(ctx.mapped.ci_type, 'cmdb_ci_linux_server');
    assert.strictEqual(ctx.flags.direct_to_incident, false);
});

test('root additionalInfo wins over wrapped additional_info despite snake_case alias order', () => {
    const ctx = normalize({
        additionalInfo: JSON.stringify({ category: 'outer', caller_id: CALLER_ID }),
        event: { additional_info: { category: 'inner', caller_id: 'inner' } }
    });
    assert.strictEqual(ctx.user_additional_info.category, 'outer');
    assert.strictEqual(ctx.user_additional_info.caller_id, CALLER_ID);
});

test('root additional_info retains precedence over root additionalInfo', () => {
    const ctx = normalize({
        additional_info: { category: 'snake' }, additionalInfo: { category: 'camel' }
    });
    assert.strictEqual(ctx.user_additional_info.category, 'snake');
});

test('additional_info extraction follows supported wrapper priority', () => {
    const raw = {};
    for (const wrapper of WRAPPERS.slice().reverse()) {
        raw[wrapper] = { additional_info: { category: wrapper } };
    }
    for (const wrapper of WRAPPERS) {
        assert.strictEqual(normalize(raw).user_additional_info.category, wrapper);
        delete raw[wrapper];
    }
});

test('flat and wrapped payload leftovers retain precedence over additional_info fields', () => {
    const ctx = normalize({
        category: 'outer',
        event: { subcategory: 'wrapped', work_notes: 'wrapped-note' },
        additional_info: { category: 'info', subcategory: 'info', work_notes: 'info-note' }
    });
    assert.strictEqual(ctx.user_additional_info.category, 'outer');
    assert.strictEqual(ctx.user_additional_info.subcategory, 'wrapped');
    assert.strictEqual(ctx.user_additional_info.work_notes, 'wrapped-note');
});

test('per-record fields override matching envelope defaults without losing other envelope fields', () => {
    const ctx = normalize({
        category: 'record-category',
        event: { caller_id: CALLER_ID, subcategory: 'record-subcategory' },
        additional_info: { contact_type: 'record-contact-type' }
    }, {
        category: 'envelope-category',
        event: { caller_id: 'envelope-caller', subcategory: 'envelope-subcategory', impact: '2' },
        additional_info: { contact_type: 'envelope-contact-type', custom_envelope: true }
    });
    assert.strictEqual(ctx.user_additional_info.category, 'record-category');
    assert.strictEqual(ctx.user_additional_info.caller_id, CALLER_ID);
    assert.strictEqual(ctx.user_additional_info.subcategory, 'record-subcategory');
    assert.strictEqual(ctx.user_additional_info.impact, '2');
    assert.strictEqual(ctx.user_additional_info.contact_type, 'record-contact-type');
    assert.strictEqual(ctx.user_additional_info.custom_envelope, true);
});

test('arbitrary nested objects and nested wrapper-named custom keys are not recursively flattened', () => {
    const custom = { event: { category: 'nested-category' }, payload: { caller_id: 'nested-caller' } };
    const nestedWrapper = { category: 'second-level-category' };
    const ctx = normalize({
        custom_context: custom,
        event: { another_context: custom, payload: nestedWrapper }
    });
    assert.deepStrictEqual(ctx.user_additional_info.custom_context, custom);
    assert.deepStrictEqual(ctx.user_additional_info.another_context, custom);
    assert.deepStrictEqual(ctx.user_additional_info.payload, nestedWrapper);
    assert.strictEqual(ctx.user_additional_info.category, undefined);
    assert.strictEqual(ctx.user_additional_info.caller_id, undefined);
});

test('recognized wrapper names inside additional_info remain custom nested context', () => {
    const info = {
        event: { category: 'nested-category' },
        payload: { caller_id: 'nested-caller' },
        custom_context: { description: 'nested-description' }
    };
    const ctx = normalize({ additional_info: info });
    assert.deepStrictEqual(ctx.user_additional_info, info);
    assert.strictEqual(ctx.user_additional_info.category, undefined);
    assert.strictEqual(ctx.user_additional_info.caller_id, undefined);
});

test('normalization does not mutate raw record or envelope objects', () => {
    const raw = { event: eventFields(), additional_info: { custom_context: { record: 1 } } };
    const envelope = { event: { contact_type: 'monitoring' } };
    const originalRaw = JSON.stringify(raw);
    const originalEnvelope = JSON.stringify(envelope);
    normalize(raw, envelope);
    assert.strictEqual(JSON.stringify(raw), originalRaw);
    assert.strictEqual(JSON.stringify(envelope), originalEnvelope);
});

console.log('Wrapper passthrough tests passed: ' + passed + ' cases');
