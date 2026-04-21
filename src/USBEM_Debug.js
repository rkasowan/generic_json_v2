if (typeof Class === 'undefined') {
    var Class = {
        create: function () {
            return function () {
                if (typeof this.initialize === 'function') {
                    this.initialize.apply(this, arguments);
                }
            };
        }
    };
}

var USBEM_Debug = Class.create();
USBEM_Debug.prototype = {
    initialize: function (core) {
        this.core = core;
        this.ATTACHMENTS = [
            { key: 'raw_payload', name: '01_raw_payload.json', type: 'application/json' },
            { key: 'normalized_payload', name: '02_normalized_payload.json', type: 'application/json' },
            { key: 'mapped_event', name: '03_mapped_event.json', type: 'application/json' },
            { key: 'lookup_trace', name: '04_lookup_trace.json', type: 'application/json' },
            { key: 'candidate_scores', name: '05_candidate_scores.json', type: 'application/json' },
            { key: 'correlation_hints', name: '06_correlation_hints.json', type: 'application/json' },
            { key: 'performance', name: '07_performance.json', type: 'application/json' },
            { key: 'response_summary', name: '08_response_summary.json', type: 'application/json' },
            { key: 'dti_timeline', name: '09_dti_timeline.json', type: 'application/json' },
            { key: 'error_context', name: '10_error_context.json', type: 'application/json' }
        ];
    },

    shouldCreateDebugEvent: function (contexts, rawPayloadText) {
        var i;
        if (this.core.rawPayloadLooksDebugEnabled(rawPayloadText)) {
            return true;
        }
        if (!this.core.isArray(contexts)) {
            return false;
        }
        for (i = 0; i < contexts.length; i++) {
            if (contexts[i] && contexts[i].flags && contexts[i].flags.debug_enabled === true) {
                return true;
            }
        }
        return false;
    },

    buildPayloadSet: function (rawPayloadText, responseObject, contexts, errorText) {
        var normalizedPayload = [];
        var mappedEvent = [];
        var lookupTrace = [];
        var candidateScores = [];
        var correlationHints = [];
        var performance = [];
        var dtiTimeline = [];
        var i;
        var ctx;
        var out = {};

        out.raw_payload = this.core.hasValue(rawPayloadText) ? String(rawPayloadText) : '';

        for (i = 0; i < contexts.length; i++) {
            ctx = contexts[i];
            if (!ctx) {
                continue;
            }

            normalizedPayload.push({
                record_index: i,
                normalized_input: this.core.deepClone(ctx.snapshots.normalized_input || {}),
                raw_event: this.core.deepClone(ctx.raw_event || {})
            });

            mappedEvent.push({
                record_index: i,
                event_sys_id: ctx.result ? ctx.result.event_sys_id : '',
                final_event: this.core.deepClone(ctx.snapshots.final_event || {})
            });

            lookupTrace.push({
                record_index: i,
                steps: this.core.deepClone((ctx.debug && ctx.debug.steps) ? ctx.debug.steps : []),
                lookups: this.core.deepClone((ctx.debug && ctx.debug.lookups) ? ctx.debug.lookups : {}),
                notes: this.core.deepClone((ctx.debug && ctx.debug.notes) ? ctx.debug.notes : []),
                errors: this.core.deepClone((ctx.debug && ctx.debug.errors) ? ctx.debug.errors : [])
            });

            candidateScores.push({
                record_index: i,
                candidates: this.core.deepClone((ctx.debug && ctx.debug.candidates) ? ctx.debug.candidates : {})
            });

            correlationHints.push({
                record_index: i,
                event_sys_id: ctx.result ? ctx.result.event_sys_id : '',
                message_key: ctx.mapped ? ctx.mapped.message_key : '',
                source: ctx.mapped ? ctx.mapped.source : '',
                event_class: ctx.mapped ? ctx.mapped.event_class : '',
                node: ctx.mapped ? ctx.mapped.node : '',
                resource: ctx.mapped ? ctx.mapped.resource : '',
                ci_type: ctx.mapped ? ctx.mapped.ci_type : '',
                cmdb_ci: ctx.resolved ? ctx.resolved.cmdb_ci_sys_id : '',
                assignment_group: ctx.resolved ? ctx.resolved.assignment_group_sys_id : '',
                cmdb_ci_service: ctx.resolved ? ctx.resolved.cmdb_ci_service : '',
                cmdb_ci_service_offering: ctx.resolved ? ctx.resolved.cmdb_ci_service_offering : '',
                cmdb_ci_business_app: ctx.resolved ? ctx.resolved.cmdb_ci_business_app : '',
                dummy_ci_used: ctx.resolved ? ctx.resolved.dummy_ci_used === true : false,
                dummy_assignment_group_used: ctx.resolved ? ctx.resolved.dummy_assignment_group_used === true : false
            });

            performance.push({
                record_index: i,
                processing_ms: ctx.result ? ctx.result.usbem_processing_ms : '',
                perf: this.core.deepClone((ctx.debug && ctx.debug.perf) ? ctx.debug.perf : {}),
                quality: this.core.deepClone((ctx.debug && ctx.debug.quality) ? ctx.debug.quality : {})
            });

            if ((ctx.flags && (ctx.flags.usbem_wait_for_alert || ctx.flags.dti_wait_for_incident || ctx.flags.direct_to_incident))) {
                dtiTimeline.push({
                    record_index: i,
                    direct_to_incident: ctx.flags.direct_to_incident === true,
                    wait_for_alert: ctx.flags.usbem_wait_for_alert === true,
                    wait_for_incident: ctx.flags.dti_wait_for_incident === true,
                    dti: this.core.deepClone(ctx.dti || {}),
                    result: this.core.deepClone(ctx.result || {})
                });
            }
        }

        out.normalized_payload = this.core.safeJSONStringify(normalizedPayload);
        out.mapped_event = this.core.safeJSONStringify(mappedEvent);
        out.lookup_trace = this.core.safeJSONStringify(lookupTrace);
        out.candidate_scores = this.core.safeJSONStringify(candidateScores);
        out.correlation_hints = this.core.safeJSONStringify(correlationHints);
        out.performance = this.core.safeJSONStringify(performance);
        out.response_summary = this.core.safeJSONStringify(responseObject || {});
        if (dtiTimeline.length > 0) {
            out.dti_timeline = this.core.safeJSONStringify(dtiTimeline);
        }
        if (this.core.hasValue(errorText)) {
            out.error_context = this.core.safeJSONStringify({ error: String(errorText) });
        }

        return out;
    },

    createDebugEvent: function (rawPayloadText, responseObject, contexts, errorText) {
        var payloads;
        var parentEventIds = [];
        var parentMessageKeys = [];
        var i;
        var debugAi = {};
        var debugGr;
        var attachGr;
        var attachment;
        var debugSysId = '';
        var title = 'USBEM debug capture';
        var ctx;

        if (!this.shouldCreateDebugEvent(contexts, rawPayloadText)) {
            return '';
        }

        payloads = this.buildPayloadSet(rawPayloadText, responseObject, contexts || [], errorText);

        for (i = 0; i < contexts.length; i++) {
            ctx = contexts[i];
            if (ctx && ctx.result && this.core.hasValue(ctx.result.event_sys_id)) {
                parentEventIds.push(String(ctx.result.event_sys_id));
            }
            if (ctx && ctx.mapped && this.core.hasValue(ctx.mapped.message_key)) {
                parentMessageKeys.push(String(ctx.mapped.message_key));
            }
        }

        if (parentEventIds.length > 0) {
            title += ' for ' + parentEventIds.length + ' event(s)';
        }

        debugAi.usbem_debug_capture_mode = 'late_companion_event';
        debugAi.usbem_version = this.core.VERSION;
        if (parentEventIds.length > 0) {
            debugAi.usbem_debug_parent_event_sys_ids = parentEventIds.join(',');
        }
        if (parentMessageKeys.length > 0) {
            debugAi.usbem_debug_parent_message_keys = parentMessageKeys.join(',');
        }

        debugGr = new GlideRecord('em_event');
        debugGr.initialize();
        this.core.setIfPresent(debugGr, 'source', this.core.DEBUG_EVENT_SOURCE);
        this.core.setIfPresent(debugGr, 'event_class', this.core.DEBUG_EVENT_CLASS);
        this.core.setIfPresent(debugGr, 'severity', this.core.DEBUG_EVENT_SEVERITY);
        this.core.setIfPresent(debugGr, 'description', this.core.truncateString(title, 4000));
        if (debugGr.isValidField('message_key')) {
            debugGr.setValue('message_key', this.core.truncateString('USBEM_DEBUG_' + gs.generateGUID(), this.core.MESSAGE_KEY_MAX));
        }
        if (debugGr.isValidField('time_of_event')) {
            debugGr.setValue('time_of_event', new GlideDateTime().getValue());
        }
        if (debugGr.isValidField('state')) {
            try {
                debugGr.setDisplayValue('state', this.core.DEBUG_EVENT_STATE);
            } catch (eState) {
                debugGr.setValue('state', this.core.DEBUG_EVENT_STATE);
            }
        }
        debugGr.setValue('additional_info', this.core.buildAdditionalInfoString(debugAi));
        debugSysId = debugGr.insert();

        if (!this.core.hasValue(debugSysId)) {
            return '';
        }

        attachGr = new GlideRecord('em_event');
        if (!attachGr.get(debugSysId)) {
            return debugSysId;
        }

        attachment = new GlideSysAttachment();
        for (i = 0; i < this.ATTACHMENTS.length; i++) {
            if (this.core.hasValue(payloads[this.ATTACHMENTS[i].key])) {
                try {
                    attachment.write(
                        attachGr,
                        this.ATTACHMENTS[i].name,
                        this.ATTACHMENTS[i].type,
                        payloads[this.ATTACHMENTS[i].key]
                    );
                } catch (eAttach) {
                }
            }
        }

        return debugSysId;
    },

    type: 'USBEM_Debug'
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = USBEM_Debug;
}

