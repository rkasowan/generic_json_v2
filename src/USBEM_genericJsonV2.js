(function process(/*RESTAPIRequest*/ request, body) {
    var core = new USBEM_Core({ request: request });
    var lookups = new USBEM_Lookups(core);
    var debugHelper = new USBEM_Debug(core);
    var rawPayloadText = '';

    try {
        rawPayloadText = (typeof body === 'string') ? body : core.safeJSONStringify(body);
    } catch (eRaw) {
        rawPayloadText = '';
    }

    function processSingleEvent(rawEvent, envelope) {
        var ctx = core.createRecordContext(rawEvent, envelope);
        var finalAdditionalInfo;
        var dtiHelper;

        lookups.resolveAll(ctx);

        finalAdditionalInfo = core.addOperationalAdditionalInfo(ctx);
        core.insertEventRecord(ctx, finalAdditionalInfo);

        if (ctx.flags.direct_to_incident || ctx.flags.wait_requested) {
            dtiHelper = new USBEM_DTI(core);
            dtiHelper.handlePostInsert(ctx);
        }

        if (ctx.flags.debug_enabled) {
            ctx.result.debug_enabled = 'true';
            ctx.result.debug_capture_mode = 'companion_event';
        }

        core.finalizeContext(ctx, finalAdditionalInfo);
        return ctx;
    }

    try {
        var payload = (typeof body === 'string') ? JSON.parse(body) : body;
        var envelope = {};
        var records = [];
        var contexts = [];
        var results = [];
        var i;
        var response;
        var debugEventSysId = '';

        if (core.isArray(payload)) {
            records = payload;
        } else if (core.isObject(payload) && core.isArray(payload.records)) {
            envelope = core.deepClone(payload);
            delete envelope.records;
            records = payload.records;
        } else if (core.isObject(payload) && core.isArray(payload.events)) {
            envelope = core.deepClone(payload);
            delete envelope.events;
            records = payload.events;
        } else {
            records = [payload];
        }

        for (i = 0; i < records.length; i++) {
            contexts.push(processSingleEvent(records[i], envelope));
            results.push(contexts[i].result);
        }

        response = {
            status: 'success',
            inserted: String(results.length),
            sys_ids: [],
            results: results,
            version: core.VERSION
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

        return JSON.stringify(response);
    } catch (er) {
        var errorResponse;
        var errorDebugEventSysId = '';

        gs.error('USBEM genericJsonV2 transform failed: ' + er);
        if (typeof status !== 'undefined') {
            status = 500;
        }

        errorResponse = {
            status: 'error',
            message: String(er),
            version: core.VERSION
        };

        errorDebugEventSysId = debugHelper.createDebugEvent(rawPayloadText, errorResponse, [], String(er));
        if (core.hasValue(errorDebugEventSysId)) {
            errorResponse.debug_raw_event_sys_id = errorDebugEventSysId;
        }

        return JSON.stringify(errorResponse);
    }
})(request, body);

