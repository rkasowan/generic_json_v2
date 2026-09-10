(function execute(inputs, outputs) {
    var SUBJECT_TOKEN = 'jabberwocky';
    var ACTION_NAME = 'USBEM Jabberwocky Inbound JSON Event';

    function text(value) {
        if (value === null || typeof value === 'undefined') {
            return '';
        }
        return String(value);
    }

    function stripHtml(value) {
        return text(value)
            .replace(/<br\s*\/?>/gi, '\n')
            .replace(/<\/p>/gi, '\n')
            .replace(/<[^>]+>/g, ' ')
            .replace(/&quot;/g, '"')
            .replace(/&#34;/g, '"')
            .replace(/&apos;/g, "'")
            .replace(/&#39;/g, "'")
            .replace(/&lt;/g, '<')
            .replace(/&gt;/g, '>')
            .replace(/&amp;/g, '&');
    }

    function parseFirstJson(textValue) {
        var input = text(textValue);
        var i;
        var j;
        var start;
        var ch;
        var stack;
        var inString;
        var escapeNext;
        var quote;
        var opener;
        var closer;
        var candidate;

        for (i = 0; i < input.length; i++) {
            opener = input.charAt(i);
            if (opener !== '{' && opener !== '[') {
                continue;
            }

            stack = [opener === '{' ? '}' : ']'];
            inString = false;
            escapeNext = false;
            quote = '';
            start = i;

            for (j = i + 1; j < input.length; j++) {
                ch = input.charAt(j);

                if (inString) {
                    if (escapeNext) {
                        escapeNext = false;
                    } else if (ch === '\\') {
                        escapeNext = true;
                    } else if (ch === quote) {
                        inString = false;
                    }
                    continue;
                }

                if (ch === '"' || ch === "'") {
                    inString = true;
                    quote = ch;
                    continue;
                }

                if (ch === '{' || ch === '[') {
                    stack.push(ch === '{' ? '}' : ']');
                    continue;
                }

                if (ch === '}' || ch === ']') {
                    closer = stack.pop();
                    if (ch !== closer) {
                        break;
                    }
                    if (stack.length === 0) {
                        candidate = input.substring(start, j + 1);
                        return JSON.parse(candidate);
                    }
                }
            }
        }

        throw new Error('No JSON object or array was found in the inbound email body');
    }

    function newCore() {
        if (typeof x_usbna_usb_event !== 'undefined' && x_usbna_usb_event.USBEM_Core) {
            return new x_usbna_usb_event.USBEM_Core({ request: null });
        }
        return new USBEM_Core({ request: null });
    }

    function newLookups(core) {
        if (typeof x_usbna_usb_event !== 'undefined' && x_usbna_usb_event.USBEM_Lookups) {
            return new x_usbna_usb_event.USBEM_Lookups(core);
        }
        return new USBEM_Lookups(core);
    }

    function newDebugHelper(core) {
        if (typeof x_usbna_usb_event !== 'undefined' && x_usbna_usb_event.USBEM_Debug) {
            return new x_usbna_usb_event.USBEM_Debug(core);
        }
        return new USBEM_Debug(core);
    }

    function newDtiHelper(core) {
        if (typeof x_usbna_usb_event !== 'undefined' && x_usbna_usb_event.USBEM_DTI) {
            return new x_usbna_usb_event.USBEM_DTI(core);
        }
        return new USBEM_DTI(core);
    }

    function processSingleEvent(core, lookups, rawEvent, envelope) {
        var ctx = core.createRecordContext(rawEvent, envelope);
        var finalAdditionalInfo;
        var dtiHelper;

        lookups.resolveAll(ctx);

        finalAdditionalInfo = core.addOperationalAdditionalInfo(ctx);
        core.insertEventRecord(ctx, finalAdditionalInfo);

        if (ctx.flags.direct_to_incident || ctx.flags.wait_requested) {
            dtiHelper = newDtiHelper(core);
            dtiHelper.handlePostInsert(ctx);
        }

        if (ctx.flags.debug_enabled) {
            ctx.result.debug_enabled = 'true';
            ctx.result.debug_capture_mode = 'companion_event';
        }

        core.finalizeContext(ctx, finalAdditionalInfo);
        return ctx;
    }

    function processPayload(payload, envelope, rawPayloadText, subject) {
        var core = newCore();
        var lookups = newLookups(core);
        var debugHelper = newDebugHelper(core);
        var records = [];
        var contexts = [];
        var results = [];
        var response;
        var debugEventSysId;
        var i;

        if (core.isArray(payload)) {
            records = payload;
        } else if (core.isObject(payload) && core.isArray(payload.records)) {
            envelope = core.deepClone(envelope);
            core.mergeDeep(envelope, payload);
            delete envelope.records;
            records = payload.records;
        } else if (core.isObject(payload) && core.isArray(payload.events)) {
            envelope = core.deepClone(envelope);
            core.mergeDeep(envelope, payload);
            delete envelope.events;
            records = payload.events;
        } else {
            records = [payload];
        }

        for (i = 0; i < records.length; i++) {
            contexts.push(processSingleEvent(core, lookups, records[i], envelope));
            results.push(contexts[i].result);
        }

        response = {
            status: 'success',
            inserted: String(results.length),
            sys_ids: [],
            results: results,
            version: core.VERSION,
            inbound_email_subject: subject
        };

        for (i = 0; i < contexts.length; i++) {
            response.sys_ids.push(contexts[i].result.event_sys_id);
        }

        if (results.length === 1) {
            core.mergeDeep(response, results[0]);
        }

        debugEventSysId = debugHelper.createDebugEvent(rawPayloadText, response, contexts, '');
        if (core.hasValue(debugEventSysId)) {
            response.debug_raw_event_sys_id = debugEventSysId;
        }

        return response;
    }

    var subject = text(inputs.subject);
    var body = [
        text(inputs.description),
        text(inputs.body_text),
        stripHtml(inputs.body_html)
    ].join('\n');
    var payload;
    var response;
    var envelope;

    outputs.status = 'skipped';
    outputs.skipped = true;
    outputs.inserted = 0;
    outputs.sys_ids = '';
    outputs.event_sys_id = '';
    outputs.version = '';
    outputs.message = '';
    outputs.response_json = '';

    if (subject.toLowerCase().indexOf(SUBJECT_TOKEN) < 0) {
        outputs.message = 'Skipped: subject did not contain ' + SUBJECT_TOKEN;
        return;
    }

    try {
        payload = parseFirstJson(body);
        envelope = {
            additional_info: {
                inbound_email_flow_action: ACTION_NAME,
                inbound_email_subject: subject,
                inbound_email_from: text(inputs.from_email),
                inbound_email_sys_id: text(inputs.sys_email_sys_id),
                inbound_email_received: new GlideDateTime().getDisplayValue()
            }
        };
        response = processPayload(payload, envelope, JSON.stringify(payload), subject);

        outputs.status = 'success';
        outputs.skipped = false;
        outputs.inserted = parseInt(response.inserted, 10) || 0;
        outputs.sys_ids = response.sys_ids.join(',');
        outputs.event_sys_id = text(response.event_sys_id);
        outputs.version = text(response.version);
        outputs.message = 'Inserted ' + response.inserted + ' event(s)';
        outputs.response_json = JSON.stringify(response);
    } catch (ex) {
        outputs.status = 'error';
        outputs.skipped = false;
        outputs.message = String(ex && ex.message ? ex.message : ex);
        outputs.response_json = JSON.stringify({ status: 'error', message: outputs.message });
        throw ex;
    }
})(inputs, outputs);
