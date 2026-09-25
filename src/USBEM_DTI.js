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

var USBEM_DTI = Class.create();
USBEM_DTI.prototype = {
    initialize: function (core) {
        this.core = core;
        this.PROPERTY_DTI_MAP_TABLE = 'x_usbna_usb_event.dti_map_table';
        this.PROPERTY_DTI_MAP_PENDING_WAIT_MS = 'x_usbna_usb_event.dti_map_pending_wait_ms';
        this.PROPERTY_DTI_TERMINAL_INCIDENT_STATES = 'x_usbna_usb_event.dti_terminal_incident_states';

        this.DEFAULT_DTI_MAP_PENDING_WAIT_MS = 1500;
        this.DEFAULT_DTI_TERMINAL_INCIDENT_STATES = '6,7,8';
        this.PENDING_MAP_POLL_MS = 100;
    },

    queryNow: function (gr, trace) {
        this.core.bumpMetric(trace, 'query_count', 1);
        gr.query();
    },

    getStringProperty: function (name, defaultValue, trace) {
        return this.core.trimToString(this.core.getProperty(name, defaultValue, trace));
    },

    getIntProperty: function (name, defaultValue, trace) {
        return this.core.toInt(this.core.getProperty(name, String(defaultValue), trace), defaultValue);
    },

    
    
    
    getDtiMapPendingWaitMs: function (trace) {
        var n = this.getIntProperty(this.PROPERTY_DTI_MAP_PENDING_WAIT_MS, this.DEFAULT_DTI_MAP_PENDING_WAIT_MS, trace);
        if (n < 0) {
            n = this.DEFAULT_DTI_MAP_PENDING_WAIT_MS;
        }
        return n;
    },

    getDtiMapTable: function (trace) {
        var tableName = this.getStringProperty(this.PROPERTY_DTI_MAP_TABLE, '', trace);
        if (!this.core.hasValue(tableName)) {
            return '';
        }
        if (!this.core.tableExists(tableName, trace)) {
            return '';
        }
        return tableName;
    },

    /**
     * Incident states that close the reuse window for a message key.
     * Read through the existing property helper and parsed once per instance. The value
     * must be a comma-separated list of integer incident.state values. A blank value, or
     * any token that is not an integer (labels, ';' separators, a null read), falls back
     * to the whole default: a mis-set property must not silently re-enable reuse of
     * resolved, closed or cancelled incidents.
     */
    getTerminalIncidentStates: function (trace) {
        var raw;
        var parts;
        var value;
        var states = [];
        var invalid = false;
        var i;

        if (this.terminalStatesCache) {
            return this.terminalStatesCache;
        }
        raw = this.getStringProperty(this.PROPERTY_DTI_TERMINAL_INCIDENT_STATES, this.DEFAULT_DTI_TERMINAL_INCIDENT_STATES, trace);
        if (this.core.hasValue(raw) && raw !== 'null' && raw !== 'undefined') {
            parts = String(raw).split(',');
            for (i = 0; i < parts.length; i++) {
                value = this.core.trimToString(parts[i]);
                if (!this.core.hasValue(value)) {
                    continue;
                }
                if (!/^-?\d+$/.test(value)) {
                    invalid = true;
                    break;
                }
                // Canonical form, so '07' matches the '7' that getValue('state') returns.
                value = String(parseInt(value, 10));
                if (states.indexOf(value) < 0) {
                    states.push(value);
                }
            }
        }
        if (invalid || !states.length) {
            if (invalid) {
                this.core.tracePush(trace, 'terminal incident states property invalid; using default ' + this.DEFAULT_DTI_TERMINAL_INCIDENT_STATES);
                try {
                    gs.warn('USBEM DTI: ' + this.PROPERTY_DTI_TERMINAL_INCIDENT_STATES + ' value "' + raw +
                        '" is not a comma-separated list of integer incident states; using ' + this.DEFAULT_DTI_TERMINAL_INCIDENT_STATES);
                } catch (eWarn) {
                }
            }
            states = String(this.DEFAULT_DTI_TERMINAL_INCIDENT_STATES).split(',');
        }
        this.terminalStatesCache = states;
        return states;
    },

    /**
     * The message key as incident.correlation_id actually stores it.
     * Keys may be up to 1024 characters but correlation_id is shorter (100 out of box)
     * and the platform truncates on write. Used only to let shouldPreferFastIncident move
     * a long key's own alert off a terminal incident. It is deliberately NOT used for the
     * correlation lookup: distinct keys sharing the first 100 characters would merge.
     */
    getCorrelationKey: function (messageKey) {
        var gr;
        var len;
        var key = this.core.hasValue(messageKey) ? String(messageKey) : '';

        if (typeof this.correlationKeyLength !== 'number') {
            this.correlationKeyLength = 0;
            try {
                gr = new GlideRecord('incident');
                if (gr.isValidField('correlation_id')) {
                    len = parseInt(gr.getElement('correlation_id').getED().getLength(), 10);
                    if (len > 0) {
                        this.correlationKeyLength = len;
                    }
                }
            } catch (eLen) {
            }
        }
        if (this.correlationKeyLength > 0 && key.length > this.correlationKeyLength) {
            return key.substring(0, this.correlationKeyLength);
        }
        return key;
    },

    /**
     * True when an incident can still absorb new events for its message key.
     * Judged on `state`, never on `active`: a Resolved incident is still active=true,
     * so an `active` test would let a resolved incident keep collecting events.
     */
    isIncidentReusable: function (incGr, trace) {
        var states;
        var value;
        var i;

        if (!incGr || !incGr.isValidRecord || !incGr.isValidRecord()) {
            return false;
        }
        if (!incGr.isValidField('state')) {
            return true;
        }
        value = this.core.trimToString(incGr.getValue('state'));
        if (!this.core.hasValue(value)) {
            return true;
        }
        states = this.getTerminalIncidentStates(trace);
        for (i = 0; i < states.length; i++) {
            if (states[i] === value) {
                return false;
            }
        }
        return true;
    },

    /**
     * A Closed alert reached by message key, or reconciled after the fact, belongs to a
     * finished incident cycle and is left on its incident; the next cycle gets its own
     * alert from Event Management. The exception is an event's own alert (em_event.alert),
     * which belongs to that event's cycle even if it has closed since.
     */
    isClosedAlert: function (alertGr) {
        if (!alertGr || !alertGr.isValidField || !alertGr.isValidField('state')) {
            return false;
        }
        return this.core.trimToString(alertGr.getValue('state') || '') === 'Closed';
    },

    describeIncident: function (incidentGr) {
        if (!incidentGr) {
            return '';
        }
        return this.core.trimToString(incidentGr.getValue('number')) + ' (state ' +
            this.core.trimToString(incidentGr.getValue('state')) + ')';
    },

    /**
     * The alert's linked incident, but only when it is still reusable.
     * getIncidentFromAlert stays state-blind for callers that need the current link
     * whatever its state; only the reuse decisions go through this wrapper.
     */
    getReusableIncidentFromAlert: function (alertGr, trace) {
        var incidentGr = this.getIncidentFromAlert(alertGr);
        if (!incidentGr) {
            return null;
        }
        if (this.isIncidentReusable(incidentGr, trace)) {
            return incidentGr;
        }
        this.core.tracePush(trace, 'terminal incident skipped on alert: ' + this.describeIncident(incidentGr));
        return null;
    },

    getEventBySysId: function (eventSysId) {
        var gr;
        if (!this.core.looksLikeSysId(eventSysId) || !this.core.tableExists('em_event')) {
            return null;
        }
        gr = new GlideRecord('em_event');
        if (gr.get(eventSysId)) {
            return gr;
        }
        return null;
    },

    getAlertBySysId: function (alertSysId) {
        var gr;
        if (!this.core.looksLikeSysId(alertSysId) || !this.core.tableExists('em_alert')) {
            return null;
        }
        gr = new GlideRecord('em_alert');
        if (gr.get(alertSysId)) {
            return gr;
        }
        return null;
    },

    getIncidentBySysId: function (incidentSysId) {
        var gr;
        if (!this.core.looksLikeSysId(incidentSysId) || !this.core.tableExists('incident')) {
            return null;
        }
        gr = new GlideRecord('incident');
        if (gr.get(incidentSysId)) {
            return gr;
        }
        return null;
    },

    getAlertFromEvent: function (eventGr) {
        var alertSysId;
        if (!eventGr || !eventGr.isValidField('alert')) {
            return null;
        }
        alertSysId = eventGr.getValue('alert');
        if (!this.core.looksLikeSysId(alertSysId)) {
            return null;
        }
        return this.getAlertBySysId(alertSysId);
    },

    getEventStateInfo: function (eventGr) {
        var rawValue = '';
        var displayValue = '';
        var normalized = '';
        if (eventGr && eventGr.isValidField('state')) {
            rawValue = eventGr.getValue('state') || '';
            displayValue = eventGr.getDisplayValue('state') || rawValue || '';
        }
        normalized = this.core.normalizeKey(displayValue || rawValue);
        return {
            raw: rawValue,
            display: displayValue,
            normalized: normalized
        };
    },

    isReadyEventState: function (stateInfo) {
        if (!stateInfo) {
            return true;
        }
        return stateInfo.normalized === '' || stateInfo.normalized === 'ready';
    },

    findAlertByMessageKey: function (messageKey, source, eventClass, trace) {
        var gr;
        if (!this.core.hasValue(messageKey) || !this.core.tableExists('em_alert', trace)) {
            return null;
        }
        gr = new GlideRecord('em_alert');
        if (!gr.isValidField('message_key')) {
            return null;
        }
        gr.addQuery('message_key', messageKey);
        if (this.core.hasValue(source) && gr.isValidField('source')) {
            gr.addQuery('source', source);
        }
        if (this.core.hasValue(eventClass) && gr.isValidField('event_class')) {
            gr.addQuery('event_class', eventClass);
        }
        if (gr.isValidField('sys_updated_on')) {
            gr.orderByDesc('sys_updated_on');
        }
        if (gr.isValidField('sys_created_on')) {
            gr.orderByDesc('sys_created_on');
        }
        gr.setLimit(1);
        this.queryNow(gr, trace);
        if (gr.next()) {
            return gr;
        }
        return null;
    },

    waitForAlert: function (ctx) {
        var deadlineMs = new Date().getTime() + ctx.flags.wait_ms;
        var alertGr = null;
        var eventGr = null;
        var stateInfo;
        var now;
        var nextPollAt = 0;
        var lastState = '';

        while (true) {
            now = new Date().getTime();
            if (now >= deadlineMs) {
                break;
            }
            if (now < nextPollAt) {
                continue;
            }
            nextPollAt = now + this.core.WAIT_ALERT_POLL_MS;

            if (this.core.looksLikeSysId(ctx.result.event_sys_id)) {
                eventGr = this.getEventBySysId(ctx.result.event_sys_id);
                if (eventGr) {
                    stateInfo = this.getEventStateInfo(eventGr);
                    if ((stateInfo.display || stateInfo.raw) !== lastState) {
                        lastState = stateInfo.display || stateInfo.raw || '';
                        if (this.core.hasValue(lastState)) {
                            this.core.tracePush(ctx.debug, 'event state observed: ' + lastState);
                        }
                    }

                    alertGr = this.getAlertFromEvent(eventGr);
                    if (alertGr) {
                        this.core.tracePush(ctx.debug, 'alert located via em_event.alert');
                        return alertGr;
                    }

                    if (!this.isReadyEventState(stateInfo) && this.core.hasValue(ctx.mapped.message_key)) {
                        alertGr = this.findAlertByMessageKey(ctx.mapped.message_key, ctx.mapped.source, ctx.mapped.event_class, ctx.debug);
                        if (alertGr) {
                            this.core.tracePush(ctx.debug, 'alert located by message_key after event left Ready');
                            return alertGr;
                        }
                    }
                }
            }

            if (this.core.hasValue(ctx.mapped.message_key)) {
                alertGr = this.findAlertByMessageKey(ctx.mapped.message_key, ctx.mapped.source, ctx.mapped.event_class, ctx.debug);
                if (alertGr) {
                    this.core.tracePush(ctx.debug, 'alert located by message_key');
                    return alertGr;
                }
            }
        }

        if (this.core.hasValue(ctx.mapped.message_key)) {
            alertGr = this.findAlertByMessageKey(ctx.mapped.message_key, ctx.mapped.source, ctx.mapped.event_class, ctx.debug);
            if (alertGr) {
                return alertGr;
            }
        }
        if (this.core.looksLikeSysId(ctx.result.event_sys_id)) {
            eventGr = this.getEventBySysId(ctx.result.event_sys_id);
            if (eventGr) {
                alertGr = this.getAlertFromEvent(eventGr);
                if (alertGr) {
                    return alertGr;
                }
            }
        }
        this.core.tracePush(ctx.debug, 'alert wait timed out');
        return null;
    },

    getIncidentFromAlert: function (alertGr) {
        var sysId;
        var inc;

        if (!alertGr) {
            return null;
        }
        if (alertGr.isValidField('incident')) {
            sysId = alertGr.getValue('incident');
            if (this.core.looksLikeSysId(sysId)) {
                inc = new GlideRecord('incident');
                if (inc.get(sysId)) {
                    return inc;
                }
            }
        }
        if (alertGr.isValidField('task')) {
            sysId = alertGr.getValue('task');
            if (this.core.looksLikeSysId(sysId)) {
                inc = new GlideRecord('incident');
                if (inc.get(sysId)) {
                    return inc;
                }
            }
        }
        return null;
    },

    waitForIncidentOnAlert: function (ctx, alertGr) {
        var deadlineMs = new Date().getTime() + ctx.flags.wait_ms;
        var alertSysId;
        var now;
        var nextPollAt = 0;
        var refreshedAlert;
        var incidentGr;

        if (!alertGr) {
            return null;
        }

        incidentGr = this.getIncidentFromAlert(alertGr);
        if (incidentGr) {
            this.core.tracePush(ctx.debug, 'incident already linked on alert');
            return incidentGr;
        }

        alertSysId = alertGr.getUniqueValue();

        while (true) {
            now = new Date().getTime();
            if (now >= deadlineMs) {
                break;
            }
            if (now < nextPollAt) {
                continue;
            }
            nextPollAt = now + this.core.WAIT_ALERT_POLL_MS;

            refreshedAlert = this.getAlertBySysId(alertSysId);
            if (!refreshedAlert) {
                break;
            }

            incidentGr = this.getIncidentFromAlert(refreshedAlert);
            if (incidentGr) {
                this.core.tracePush(ctx.debug, 'incident linked on alert after polling');
                return incidentGr;
            }
        }

        refreshedAlert = this.getAlertBySysId(alertSysId);
        if (refreshedAlert) {
            incidentGr = this.getIncidentFromAlert(refreshedAlert);
            if (incidentGr) {
                return incidentGr;
            }
        }

        this.core.tracePush(ctx.debug, 'incident wait timed out on alert');
        return null;
    },

    setWorkNotesIfPresent: function (incGr, value) {
        if (!this.core.hasValue(value)) {
            return;
        }
        // Journal fields only take dot assignment; setValue() is dropped without an error.
        if (incGr.isValidField('work_notes')) {
            incGr.work_notes = String(value);
        } else if (incGr.isValidField('comments')) {
            incGr.comments = String(value);
        }
    },

    /**
     * Post a sender-supplied work note onto the alert.
     * The alert does not exist while the request is being served, so the note travels in the
     * event's additional_info and is written when the alert is first handled. "alert_work_notes"
     * always targets the alert; a plain "work_notes" targets the alert only when there is no
     * incident to put it on, so a non-DTI sender can still annotate their alert.
     */
    applyAlertWorkNote: function (alertGr, hasIncident) {
        var info;
        var note;

        if (!alertGr || !alertGr.isValidField('work_notes') || !alertGr.isValidField('additional_info')) {
            return false;
        }
        info = this.core.tryParseJSON(String(alertGr.getValue('additional_info') || ''));
        if (!this.core.isObject(info)) {
            return false;
        }
        note = this.core.hasValue(info.alert_work_notes) ? info.alert_work_notes :
            (!hasIncident && this.core.hasValue(info.work_notes) ? info.work_notes : '');
        if (!this.core.hasValue(note)) {
            return false;
        }
        // work_notes is a journal_input: setValue() is silently dropped, dot assignment is what
        // actually registers the entry.
        alertGr.work_notes = String(note);
        alertGr.update();
        return true;
    },

    setCorrelationIfPresent: function (incGr, ctx) {
        if (!ctx || !ctx.mapped || !this.core.hasValue(ctx.mapped.message_key)) {
            return;
        }
        if (incGr.isValidField('correlation_id')) {
            incGr.setValue('correlation_id', ctx.mapped.message_key);
        }
        if (incGr.isValidField('correlation_display')) {
            incGr.setValue('correlation_display', 'USBEM DTI');
        }
    },

    /**
     * Link an alert to an incident, but only if nobody else owns it.
     * replaceableIncidentSysId widens the claim to one specific existing link - the
     * incident the caller already inspected. The condition is re-checked in the query
     * itself and is scoped to this alert and that exact sys_id, so it can never widen to
     * another alert or another owner; a concurrent writer that moved the alert elsewhere
     * before the query wins. Only the short gap between query and update() remains.
     */
    claimAlertForIncident: function (alertSysId, incidentSysId, replaceableIncidentSysId) {
        var claimGr;
        var linkField = '';
        var condition = null;
        var priorLink = '';

        if (!this.core.looksLikeSysId(alertSysId) || !this.core.looksLikeSysId(incidentSysId)) {
            return { claimed: false, incident: null, replaced: false };
        }

        claimGr = new GlideRecord('em_alert');
        claimGr.addQuery('sys_id', alertSysId);
        if (claimGr.isValidField('task')) {
            linkField = 'task';
        } else if (claimGr.isValidField('incident')) {
            linkField = 'incident';
        }
        if (linkField) {
            condition = claimGr.addNullQuery(linkField);
            if (this.core.looksLikeSysId(replaceableIncidentSysId) && condition) {
                try {
                    condition.addOrCondition(linkField, replaceableIncidentSysId);
                } catch (eOr) {
                }
            }
        }
        claimGr.setLimit(1);
        this.queryNow(claimGr);
        if (!claimGr.next()) {
            claimGr = new GlideRecord('em_alert');
            if (claimGr.get(alertSysId)) {
                return { claimed: false, incident: this.getIncidentFromAlert(claimGr), replaced: false };
            }
            return { claimed: false, incident: null, replaced: false };
        }

        if (linkField) {
            priorLink = this.core.trimToString(claimGr.getValue(linkField) || '');
        }
        if (claimGr.isValidField('incident')) {
            claimGr.setValue('incident', incidentSysId);
        }
        if (claimGr.isValidField('task')) {
            claimGr.setValue('task', incidentSysId);
        }
        claimGr.update();
        return { claimed: true, incident: null, replaced: this.core.looksLikeSysId(priorLink) };
    },

    forceAlertForIncident: function (alertSysId, incidentSysId) {
        var alertGr;
        if (!this.core.looksLikeSysId(alertSysId) || !this.core.looksLikeSysId(incidentSysId)) {
            return false;
        }
        alertGr = new GlideRecord('em_alert');
        if (!alertGr.get(alertSysId)) {
            return false;
        }
        if (alertGr.isValidField('incident')) {
            alertGr.setValue('incident', incidentSysId);
        }
        if (alertGr.isValidField('task')) {
            alertGr.setValue('task', incidentSysId);
        }
        alertGr.update();
        return true;
    },

    /**
     * Should `preferredIncident` displace `currentIncident` as the alert's link?
     * State is checked before age: an incident that has been resolved, closed or
     * cancelled can neither win nor hold the alert, however old it is.
     */
    shouldPreferFastIncident: function (payload, preferredIncident, currentIncident) {
        var correlationKey;
        var preferredCorrelation = '';
        var currentCorrelation = '';
        var preferredCreated = '';
        var currentCreated = '';
        var preferredCreatedBy = '';
        var currentCreatedBy = '';

        if (!payload || !preferredIncident || !currentIncident) {
            return false;
        }
        if (preferredIncident.getUniqueValue() === currentIncident.getUniqueValue()) {
            return false;
        }
        if (!this.core.hasValue(payload.message_key)) {
            return false;
        }

        if (preferredIncident.isValidField('correlation_id')) {
            preferredCorrelation = preferredIncident.getValue('correlation_id') || '';
        }
        if (currentIncident.isValidField('correlation_id')) {
            currentCorrelation = currentIncident.getValue('correlation_id') || '';
        }
        if (preferredCorrelation !== payload.message_key || currentCorrelation !== payload.message_key) {
            // Keys longer than correlation_id are stored truncated, so they never match
            // exactly. For those, allow only the terminal-replacement rule: the caller is
            // deciding for this key's own alert, so moving it off a finished incident onto
            // a live one of the same stored key cannot merge distinct keys. The age and
            // creator rules below still require an exact match, as before this change.
            correlationKey = this.getCorrelationKey(payload.message_key);
            if (correlationKey === String(payload.message_key) ||
                preferredCorrelation !== correlationKey || currentCorrelation !== correlationKey) {
                return false;
            }
            return this.isIncidentReusable(preferredIncident) && !this.isIncidentReusable(currentIncident);
        }

        if (!this.isIncidentReusable(preferredIncident)) {
            return false;
        }
        if (!this.isIncidentReusable(currentIncident)) {
            return true;
        }

        if (preferredIncident.isValidField('sys_created_by')) {
            preferredCreatedBy = preferredIncident.getValue('sys_created_by') || '';
        }
        if (currentIncident.isValidField('sys_created_by')) {
            currentCreatedBy = currentIncident.getValue('sys_created_by') || '';
        }
        if (currentCreatedBy === 'system' && preferredCreatedBy !== 'system') {
            return true;
        }

        if (preferredIncident.isValidField('sys_created_on')) {
            preferredCreated = preferredIncident.getValue('sys_created_on') || '';
        }
        if (currentIncident.isValidField('sys_created_on')) {
            currentCreated = currentIncident.getValue('sys_created_on') || '';
        }
        if (this.core.hasValue(preferredCreated) && this.core.hasValue(currentCreated) && preferredCreated <= currentCreated) {
            return true;
        }

        return false;
    },

    isUsbemDtiIncident: function (incidentGr) {
        if (!incidentGr || !incidentGr.isValidRecord || !incidentGr.isValidRecord()) {
            return false;
        }
        if (!incidentGr.isValidField('correlation_display')) {
            return false;
        }
        return incidentGr.getValue('correlation_display') === 'USBEM DTI';
    },

    pickPreferredCorrelationIncident: function (messageKey, preferredIncident, candidateIncident) {
        var payload = { message_key: messageKey || '' };
        var candidateIsUsbemDti;
        var preferredIsUsbemDti;

        if (!candidateIncident || !candidateIncident.isValidRecord || !candidateIncident.isValidRecord()) {
            return preferredIncident || null;
        }
        if (!preferredIncident || !preferredIncident.isValidRecord || !preferredIncident.isValidRecord()) {
            return candidateIncident;
        }

        candidateIsUsbemDti = this.isUsbemDtiIncident(candidateIncident);
        preferredIsUsbemDti = this.isUsbemDtiIncident(preferredIncident);
        if (candidateIsUsbemDti && !preferredIsUsbemDti) {
            return candidateIncident;
        }
        if (!candidateIsUsbemDti && preferredIsUsbemDti) {
            return preferredIncident;
        }
        if (this.shouldPreferFastIncident(payload, candidateIncident, preferredIncident)) {
            return candidateIncident;
        }
        return preferredIncident;
    },

    /**
     * Fields the connector owns. Everything else on the incident is fair game.
     */
    RESERVED_INCIDENT_FIELDS: ['sys_id', 'number', 'correlation_id', 'correlation_display'],

    /**
     * Write sender-supplied incident fields straight through, under their real names.
     * This endpoint replaces a direct write to the incident table, so a sender sets caller_id,
     * category, subcategory, contact_type or any other incident field exactly as they would
     * have on the record itself.
     *
     * The source is the payload keys the connector did not consume as event fields, so standard
     * event keys (source, node, severity, description and their aliases) can never leak in. A
     * 32-character value is written as-is; anything else goes through setDisplayValue, so
     * "category": "Software" or "caller_id": "Abel Tuter" work as written. A name that is not a
     * real incident field is skipped and reported rather than guessed at.
     */
    applyRequestedIncidentFields: function (incGr, ctx) {
        var applied = [];
        var skipped = [];
        var source = this.core.isObject(ctx.user_additional_info) ? ctx.user_additional_info : {};
        var field;
        var value;

        for (field in source) {
            if (!this.core.hasOwn(source, field)) {
                continue;
            }
            value = source[field];
            if (!this.core.hasValue(value) || this.core.isObject(value) || this.core.isArray(value)) {
                continue;
            }
            if (this.RESERVED_INCIDENT_FIELDS.indexOf(field) >= 0 || !incGr.isValidField(field)) {
                continue;
            }
            try {
                if (this.core.looksLikeSysId(value)) {
                    incGr.setValue(field, String(value));
                } else {
                    // Scoped GlideRecord has no setDisplayValue; the element does. This is what
                    // resolves "Software" to a choice value and "Abel Tuter" to a user sys_id.
                    incGr.getElement(field).setDisplayValue(String(value));
                }
                applied.push(field);
            } catch (eField) {
                skipped.push(field);
            }
        }

        if (applied.length) {
            ctx.result.incident_fields_applied = applied.join(',');
            this.core.tracePush(ctx.debug, 'incident fields from payload: ' + applied.join(','));
        }
        if (skipped.length) {
            ctx.result.incident_fields_skipped = skipped.join(',');
            this.core.tracePush(ctx.debug, 'incident fields skipped: ' + skipped.join(','));
        }
    },

    createIncidentRecord: function (ctx) {
        var inc;
        var sysId;
        var shortDescription;
        var description;
        var incident;

        if (!this.core.tableExists('incident', ctx.debug)) {
            return null;
        }

        inc = new GlideRecord('incident');
        inc.initialize();

        shortDescription = this.core.hasValue(ctx.special.dti_short_description) ? ctx.special.dti_short_description : ctx.mapped.description;
        description = ctx.mapped.description;

        this.core.setIfPresent(inc, 'short_description', this.core.truncateString(shortDescription, 160));
        this.core.setIfPresent(inc, 'description', this.core.truncateString(description, 4000));
        this.core.setIfPresent(inc, 'impact', ctx.dti.impact);
        this.core.setIfPresent(inc, 'urgency', ctx.dti.urgency);
        this.setCorrelationIfPresent(inc, ctx);

        if (this.core.hasValue(ctx.resolved.assignment_group_sys_id) && this.core.looksLikeSysId(ctx.resolved.assignment_group_sys_id)) {
            this.core.setIfPresent(inc, 'assignment_group', ctx.resolved.assignment_group_sys_id);
        }
        if (this.core.hasValue(ctx.resolved.cmdb_ci_sys_id) && this.core.looksLikeSysId(ctx.resolved.cmdb_ci_sys_id)) {
            this.core.setIfPresent(inc, 'cmdb_ci', ctx.resolved.cmdb_ci_sys_id);
        }
        if (this.core.hasValue(ctx.resolved.cmdb_ci_service) && this.core.looksLikeSysId(ctx.resolved.cmdb_ci_service)) {
            if (inc.isValidField('business_service')) {
                inc.setValue('business_service', ctx.resolved.cmdb_ci_service);
            } else if (inc.isValidField('service')) {
                inc.setValue('service', ctx.resolved.cmdb_ci_service);
            }
        }
        if (this.core.hasValue(ctx.resolved.cmdb_ci_service_offering) && this.core.looksLikeSysId(ctx.resolved.cmdb_ci_service_offering) && inc.isValidField('service_offering')) {
            inc.setValue('service_offering', ctx.resolved.cmdb_ci_service_offering);
        }

        // Sender-supplied fields last, so an explicitly supplied caller_id, category or any
        // other incident field wins over anything derived above.
        this.applyRequestedIncidentFields(inc, ctx);

        this.setWorkNotesIfPresent(inc, ctx.special.dti_work_note);

        sysId = inc.insert();
        if (!this.core.looksLikeSysId(sysId)) {
            return null;
        }

        incident = new GlideRecord('incident');
        if (incident.get(sysId)) {
            return incident;
        }
        return null;
    },

    /**
     * True when any alert references the incident. A just-created incident becomes
     * visible to the reconcile rule and async linkers as soon as it is inserted, so it
     * may already carry an alert by the time a race is detected. Unknown means yes.
     */
    isIncidentLinkedToAnyAlert: function (incidentSysId) {
        var gr;
        var linkField = '';
        if (!this.core.looksLikeSysId(incidentSysId)) {
            return true;
        }
        gr = new GlideRecord('em_alert');
        if (gr.isValidField('task')) {
            linkField = 'task';
        } else if (gr.isValidField('incident')) {
            linkField = 'incident';
        }
        if (!linkField) {
            return true;
        }
        gr.addQuery(linkField, incidentSysId);
        gr.setLimit(1);
        this.queryNow(gr);
        return gr.next();
    },

    deleteIncidentBestEffort: function (incidentGr) {
        try {
            if (incidentGr && incidentGr.isValidRecord && incidentGr.isValidRecord()) {
                incidentGr.deleteRecord();
            }
        } catch (e) {
        }
    },

    createOrReuseIncidentForAlert: function (ctx, alertGr) {
        var existingIncident;
        var linkedIncident;
        var terminalIncidentSysId = '';
        var skippedTerminal = false;
        var createdIncident;
        var claim;
        var refreshedAlert;
        var alertSysId;

        if (!alertGr) {
            return { incident: null, status: 'alert_not_found' };
        }

        alertSysId = alertGr.getUniqueValue();
        refreshedAlert = this.getAlertBySysId(alertSysId);
        linkedIncident = this.getIncidentFromAlert(refreshedAlert || alertGr);
        if (linkedIncident) {
            if (this.isIncidentReusable(linkedIncident, ctx.debug)) {
                return { incident: linkedIncident, status: 'existing' };
            }
            // Remember the exact finished incident so the claim below can replace that
            // one link, rather than either giving up or overwriting an unrelated owner.
            terminalIncidentSysId = linkedIncident.getUniqueValue();
            skippedTerminal = true;
            this.core.tracePush(ctx.debug, 'terminal incident skipped on alert: ' + this.describeIncident(linkedIncident));
        }

        if (!ctx.dti.allow_incident) {
            return { incident: null, status: 'suppressed_by_severity_map' };
        }

        // Only ever move an alert off one of our own incidents. A terminal task that
        // some other process attached is left exactly where it is.
        if (this.core.hasValue(terminalIncidentSysId) && !this.isUsbemDtiIncident(linkedIncident)) {
            this.core.tracePush(ctx.debug, 'alert holds a foreign terminal task; leaving the alert link untouched');
            terminalIncidentSysId = '';
        }
        if (this.core.hasValue(terminalIncidentSysId) && this.isClosedAlert(refreshedAlert || alertGr)) {
            this.core.tracePush(ctx.debug, 'closed alert left on its terminal incident');
            terminalIncidentSysId = '';
        }

        existingIncident = this.getExistingIncidentByCorrelationId(ctx.mapped.message_key, ctx.debug);
        if (existingIncident) {
            claim = this.claimAlertForIncident(alertSysId, existingIncident.getUniqueValue(), terminalIncidentSysId);
            if (claim.claimed) {
                this.core.tracePush(ctx.debug, 'existing incident claimed onto alert by correlation_id');
                if (claim.replaced) {
                    this.core.tracePush(ctx.debug, 'alert relinked from terminal incident to ' + this.describeIncident(existingIncident));
                    return { incident: existingIncident, status: 'claimed_from_terminal_incident' };
                }
                return { incident: existingIncident, status: 'existing_from_correlation_id' };
            }
            if (claim.incident && claim.incident.getUniqueValue() === existingIncident.getUniqueValue()) {
                this.core.tracePush(ctx.debug, 'alert already linked to the open correlation incident by a concurrent linker');
                return { incident: existingIncident, status: skippedTerminal ? 'claimed_from_terminal_incident' : 'existing_from_correlation_id' };
            }
            if (claim.incident && this.isIncidentReusable(claim.incident, ctx.debug)) {
                this.core.tracePush(ctx.debug, 'alert already linked while claiming existing correlation incident');
                return { incident: claim.incident, status: 'existing_after_race' };
            }
            // The alert could not be claimed: it holds a finished or foreign task we may
            // not replace. The open incident for this key is still the right answer;
            // creating another here would duplicate it.
            this.core.tracePush(ctx.debug, 'open correlation incident returned without claiming the alert');
            return {
                incident: existingIncident,
                status: (skippedTerminal || claim.incident) ? 'existing_after_terminal' : 'existing_unlinked'
            };
        }

        createdIncident = this.createIncidentRecord(ctx);
        if (!createdIncident) {
            return { incident: null, status: 'create_failed' };
        }

        claim = this.claimAlertForIncident(alertSysId, createdIncident.getUniqueValue(), terminalIncidentSysId);
        if (claim.claimed) {
            this.core.tracePush(ctx.debug, 'incident created and linked: ' + createdIncident.getUniqueValue());
            if (claim.replaced) {
                this.core.tracePush(ctx.debug, 'alert relinked from terminal incident to ' + this.describeIncident(createdIncident));
                return { incident: createdIncident, status: 'relinked_from_terminal_incident' };
            }
            return {
                incident: createdIncident,
                status: skippedTerminal ? 'created_after_terminal' : 'created'
            };
        }

        if (claim.incident && claim.incident.getUniqueValue() === createdIncident.getUniqueValue()) {
            // Another actor (the reconcile rule or an async linker) already moved the alert
            // onto the incident we just created. That is our own success, not a race lost.
            this.core.tracePush(ctx.debug, 'alert already linked to the created incident by a concurrent linker');
            return { incident: createdIncident, status: skippedTerminal ? 'relinked_from_terminal_incident' : 'created' };
        }

        if (claim.incident) {
            // Only stand down for a live owner. A finished incident on the alert must
            // never cost us the incident we just created and already have to return.
            if (this.isIncidentReusable(claim.incident, ctx.debug)) {
                this.core.tracePush(ctx.debug, 'incident race detected, existing linked incident reused');
                if (!this.isIncidentLinkedToAnyAlert(createdIncident.getUniqueValue())) {
                    this.deleteIncidentBestEffort(createdIncident);
                }
                return { incident: claim.incident, status: 'existing_after_race' };
            }
            this.core.tracePush(ctx.debug, 'terminal incident skipped on alert after claim race: ' + this.describeIncident(claim.incident));
            return { incident: createdIncident, status: 'created_after_terminal' };
        }

        return { incident: createdIncident, status: 'created_unlinked' };
    },

    getExistingIncidentByCorrelationId: function (messageKey, trace) {
        var gr;
        var preferredIncident = null;
        var candidateIncident;
        var terminalStates;
        if (!this.core.hasValue(messageKey) || !this.core.tableExists('incident', trace)) {
            return null;
        }
        gr = new GlideRecord('incident');
        if (!gr.isValidField('correlation_id')) {
            return null;
        }
        gr.addQuery('correlation_id', messageKey);
        // Terminal states are excluded in the query rather than after the fact, so the
        // result set stays small as a key cycles through incident after incident.
        terminalStates = this.getTerminalIncidentStates(trace);
        if (terminalStates.length && gr.isValidField('state')) {
            gr.addQuery('state', 'NOT IN', terminalStates.join(','));
            this.core.tracePush(trace, 'terminal incident states excluded from correlation lookup: ' + terminalStates.join(','));
        }
        if (gr.isValidField('sys_created_on')) {
            gr.orderBy('sys_created_on');
        }
        if (gr.isValidField('sys_updated_on')) {
            gr.orderBy('sys_updated_on');
        }
        this.queryNow(gr, trace);
        while (gr.next()) {
            candidateIncident = this.getIncidentBySysId(gr.getUniqueValue());
            preferredIncident = this.pickPreferredCorrelationIncident(messageKey, preferredIncident, candidateIncident);
        }
        return preferredIncident;
    },

    getMapRowByMessageKey: function (tableName, messageKey, trace) {
        var gr;
        if (!this.core.hasValue(tableName) || !this.core.hasValue(messageKey)) {
            return null;
        }
        gr = new GlideRecord(tableName);
        if (!gr.isValidField('u_message_key')) {
            return null;
        }
        gr.addQuery('u_message_key', messageKey);
        if (gr.isValidField('sys_updated_on')) {
            gr.orderByDesc('sys_updated_on');
        }
        gr.setLimit(1);
        this.queryNow(gr, trace);
        if (gr.next()) {
            return gr;
        }
        return null;
    },

    insertPendingMapRow: function (tableName, messageKey, eventSysId, trace) {
        var gr;
        var sysId = '';
        if (!this.core.hasValue(tableName) || !this.core.hasValue(messageKey)) {
            return { owner: false, row: null };
        }

        gr = new GlideRecord(tableName);
        gr.initialize();
        if (gr.isValidField('u_message_key')) {
            gr.setValue('u_message_key', messageKey);
        }
        if (this.core.looksLikeSysId(eventSysId) && gr.isValidField('u_last_event')) {
            gr.setValue('u_last_event', eventSysId);
        }
        if (gr.isValidField('u_state')) {
            gr.setValue('u_state', 'pending');
        }
        if (gr.isValidField('u_last_status')) {
            gr.setValue('u_last_status', 'pending');
        }

        try {
            sysId = gr.insert();
        } catch (eInsert) {
            sysId = '';
        }

        if (this.core.looksLikeSysId(sysId)) {
            gr = new GlideRecord(tableName);
            if (gr.get(sysId)) {
                return { owner: true, row: gr };
            }
        }

        gr = this.getMapRowByMessageKey(tableName, messageKey, trace);
        return { owner: false, row: gr };
    },

    updateMapRowIncident: function (rowGr, incidentSysId, eventSysId, statusValue) {
        if (!rowGr || !rowGr.isValidRecord || !rowGr.isValidRecord()) {
            return;
        }
        if (this.core.looksLikeSysId(incidentSysId) && rowGr.isValidField('u_incident')) {
            rowGr.setValue('u_incident', incidentSysId);
        }
        if (this.core.looksLikeSysId(eventSysId) && rowGr.isValidField('u_last_event')) {
            rowGr.setValue('u_last_event', eventSysId);
        }
        if (rowGr.isValidField('u_state')) {
            rowGr.setValue('u_state', this.core.hasValue(incidentSysId) ? 'linked' : 'pending');
        }
        if (rowGr.isValidField('u_last_status')) {
            rowGr.setValue('u_last_status', statusValue || '');
        }
        rowGr.update();
    },

    waitForMapIncident: function (tableName, rowSysId, trace) {
        var deadlineMs;
        var nextPollAt = 0;
        var now;
        var rowGr;
        var incidentGr;
        if (!this.core.hasValue(tableName) || !this.core.looksLikeSysId(rowSysId)) {
            return null;
        }

        deadlineMs = new Date().getTime() + this.getDtiMapPendingWaitMs(trace);

        while (true) {
            now = new Date().getTime();
            if (now >= deadlineMs) {
                break;
            }
            if (now < nextPollAt) {
                continue;
            }
            nextPollAt = now + this.PENDING_MAP_POLL_MS;
            rowGr = new GlideRecord(tableName);
            if (!rowGr.get(rowSysId)) {
                break;
            }
            if (rowGr.isValidField('u_incident')) {
                incidentGr = new GlideRecord('incident');
                if (incidentGr.get(rowGr.getValue('u_incident'))) {
                    return incidentGr;
                }
            }
        }

        rowGr = new GlideRecord(tableName);
        if (rowGr.get(rowSysId) && rowGr.isValidField('u_incident')) {
            incidentGr = new GlideRecord('incident');
            if (incidentGr.get(rowGr.getValue('u_incident'))) {
                return incidentGr;
            }
        }

        return null;
    },

    upsertMapWithIncident: function (messageKey, incidentSysId, eventSysId, trace) {
        var tableName = this.getDtiMapTable(trace);
        var row;
        var inserted;
        if (!this.core.hasValue(tableName) || !this.core.hasValue(messageKey) || !this.core.looksLikeSysId(incidentSysId)) {
            return;
        }
        row = this.getMapRowByMessageKey(tableName, messageKey, trace);
        if (!row) {
            inserted = this.insertPendingMapRow(tableName, messageKey, eventSysId, trace);
            row = inserted.row;
        }
        if (row) {
            this.updateMapRowIncident(row, incidentSysId, eventSysId, 'incident_ready');
        }
    },

    getOrCreateFastIncident: function (ctx) {
        var alertGr;
        var existingIncident;
        var tableName;
        var mapOutcome;
        var waitedIncident;
        var createdIncident;
        var skippedTerminal = false;

        if (!ctx.dti.allow_incident) {
            return { incident: null, status: 'suppressed_by_severity_map' };
        }

        alertGr = this.findAlertByMessageKey(ctx.mapped.message_key, ctx.mapped.source, ctx.mapped.event_class, ctx.debug);
        if (alertGr) {
            existingIncident = this.getReusableIncidentFromAlert(alertGr, ctx.debug);
            if (existingIncident) {
                this.upsertMapWithIncident(ctx.mapped.message_key, existingIncident.getUniqueValue(), ctx.result.event_sys_id, ctx.debug);
                return { incident: existingIncident, status: 'existing_from_alert' };
            }
            // The previous alert for this key is still pointing at a finished incident.
            // Fall through and open a new one; the async linker moves the alert across.
            skippedTerminal = !!this.getIncidentFromAlert(alertGr);
        }

        existingIncident = this.getExistingIncidentByCorrelationId(ctx.mapped.message_key, ctx.debug);
        if (existingIncident) {
            this.upsertMapWithIncident(ctx.mapped.message_key, existingIncident.getUniqueValue(), ctx.result.event_sys_id, ctx.debug);
            return {
                incident: existingIncident,
                status: skippedTerminal ? 'existing_fast_after_terminal' : 'existing_from_correlation_id'
            };
        }

        tableName = this.getDtiMapTable(ctx.debug);
        if (this.core.hasValue(tableName)) {
            mapOutcome = this.insertPendingMapRow(tableName, ctx.mapped.message_key, ctx.result.event_sys_id, ctx.debug);
            if (mapOutcome.row && !mapOutcome.owner) {
                waitedIncident = this.waitForMapIncident(tableName, mapOutcome.row.getUniqueValue(), ctx.debug);
                if (waitedIncident) {
                    return { incident: waitedIncident, status: 'existing_from_dti_map' };
                }
                existingIncident = this.getExistingIncidentByCorrelationId(ctx.mapped.message_key, ctx.debug);
                if (existingIncident) {
                    this.updateMapRowIncident(mapOutcome.row, existingIncident.getUniqueValue(), ctx.result.event_sys_id, 'existing_after_wait');
                    return { incident: existingIncident, status: 'existing_after_wait' };
                }
                return { incident: null, status: 'pending_existing_request' };
            }
        }

        createdIncident = this.createIncidentRecord(ctx);
        if (!createdIncident) {
            return { incident: null, status: 'create_failed' };
        }

        this.upsertMapWithIncident(ctx.mapped.message_key, createdIncident.getUniqueValue(), ctx.result.event_sys_id, ctx.debug);
        return {
            incident: createdIncident,
            status: skippedTerminal ? 'created_fast_after_terminal' : 'created_fast'
        };
    },

    
    
    
    
    
    
    
    reconcileAlertIncident: function (alertGr, trace) {
        var messageKey;
        var preferredIncident;
        var existingIncident;
        var existingIsTerminal = false;
        var claim;
        var outcome;
        var noteWritten = false;

        if (!alertGr || !alertGr.isValidRecord || !alertGr.isValidRecord()) {
            return { status: 'alert_missing' };
        }

        messageKey = alertGr.isValidField('message_key') ? (alertGr.getValue('message_key') || '') : '';
        if (!this.core.hasValue(messageKey)) {
            return { status: 'message_key_missing', alert_sys_id: alertGr.getUniqueValue() };
        }

        // A Closed alert keeps the incident of the cycle it closed with. Without this,
        // any later update to an old alert would pull it onto the key's newest incident.
        if (this.isClosedAlert(alertGr)) {
            return { status: 'skipped_closed_alert', alert_sys_id: alertGr.getUniqueValue() };
        }

        noteWritten = this.applyAlertWorkNote(alertGr, this.core.looksLikeSysId(alertGr.getValue('incident')));

        preferredIncident = this.getExistingIncidentByCorrelationId(messageKey, trace);
        if (!preferredIncident || !this.isUsbemDtiIncident(preferredIncident)) {
            return {
                status: 'no_usbemdti_incident',
                alert_sys_id: alertGr.getUniqueValue(),
                message_key: messageKey,
                alert_work_note: noteWritten
            };
        }

        existingIncident = this.getIncidentFromAlert(alertGr);
        if (existingIncident && existingIncident.getUniqueValue() === preferredIncident.getUniqueValue()) {
            return {
                status: 'already_linked',
                alert_sys_id: alertGr.getUniqueValue(),
                incident_sys_id: existingIncident.getUniqueValue()
            };
        }

        // Never take an alert away from a task some other process attached.
        if (existingIncident && !this.isUsbemDtiIncident(existingIncident)) {
            return {
                status: 'kept_existing',
                alert_sys_id: alertGr.getUniqueValue(),
                incident_sys_id: existingIncident.getUniqueValue()
            };
        }

        if (existingIncident) {
            existingIsTerminal = !this.isIncidentReusable(existingIncident, trace);
            if (existingIsTerminal) {
                this.core.tracePush(trace, 'terminal incident skipped on alert: ' + this.describeIncident(existingIncident));
            }
        }

        if (existingIncident && !this.shouldPreferFastIncident({ message_key: messageKey }, preferredIncident, existingIncident)) {
            return {
                status: existingIsTerminal ? 'kept_terminal_incident' : 'kept_existing',
                alert_sys_id: alertGr.getUniqueValue(),
                incident_sys_id: existingIncident.getUniqueValue()
            };
        }

        // Conditional write: lands only if the alert is still unlinked or still holds the
        // exact incident inspected above. A link to a non-incident task (which
        // getIncidentFromAlert cannot see) or a concurrent writer's link is never replaced.
        claim = this.claimAlertForIncident(alertGr.getUniqueValue(), preferredIncident.getUniqueValue(),
            existingIncident ? existingIncident.getUniqueValue() : '');
        if (claim.claimed) {
            outcome = {
                status: existingIsTerminal ? 'relinked_from_terminal_incident' :
                    (existingIncident ? 'relinked_to_fast_incident' : 'linked'),
                alert_sys_id: alertGr.getUniqueValue(),
                incident_sys_id: preferredIncident.getUniqueValue()
            };
            if (existingIsTerminal) {
                outcome.previous_incident_sys_id = existingIncident.getUniqueValue();
                this.core.tracePush(trace, 'alert relinked from terminal incident ' + this.describeIncident(existingIncident) +
                    ' to ' + this.describeIncident(preferredIncident));
                // The reconcile business rule logs only linked/relinked_to_fast_incident and
                // passes no trace, so this outcome is logged here to stay observable.
                try {
                    gs.info('USBEM DTI alert relinked from terminal incident: ' + this.core.safeJSONStringify(outcome));
                } catch (eLog) {
                }
            }
            return outcome;
        }

        return {
            status: 'kept_existing',
            alert_sys_id: alertGr.getUniqueValue(),
            incident_sys_id: claim.incident ? claim.incident.getUniqueValue() : (alertGr.getValue('incident') || '')
        };
    },

    handleFastDti: function (ctx) {
        var outcome;
        if (!ctx.flags.direct_to_incident) {
            return ctx.result;
        }

        outcome = this.getOrCreateFastIncident(ctx);
        ctx.result.dti_mode = 'fast_async';
        ctx.result.dti_incident_status = outcome.status || '';
        if (outcome.incident) {
            this.core.mergeDeep(ctx.result, this.core.summarizeIncident(outcome.incident));
        }
        // Nothing is queued here. The alert does not exist yet, and the em_alert business rule
        // links it the moment Event Management creates it.
        return ctx.result;
    },

    handlePostInsert: function (ctx) {
        var alertGr = null;
        var incidentGr = null;
        var dtiOutcome;

        if (ctx.flags.direct_to_incident && !ctx.flags.dti_wait_for_incident) {
            return this.handleFastDti(ctx);
        }

        if (ctx.flags.usbem_wait_for_alert) {
            alertGr = this.waitForAlert(ctx);
            if (alertGr) {
                this.core.mergeDeep(ctx.result, this.core.summarizeAlert(alertGr));
            } else {
                ctx.result.alert_wait_status = 'timeout';
            }
        }

        if (ctx.flags.direct_to_incident && ctx.flags.dti_wait_for_incident) {
            if (!alertGr) {
                alertGr = this.waitForAlert(ctx);
                if (alertGr) {
                    this.core.mergeDeep(ctx.result, this.core.summarizeAlert(alertGr));
                }
            }

            dtiOutcome = this.createOrReuseIncidentForAlert(ctx, alertGr);
            ctx.result.dti_mode = 'wait_for_incident';
            ctx.result.dti_incident_status = dtiOutcome.status || '';
            incidentGr = dtiOutcome.incident;
            if (incidentGr) {
                this.core.mergeDeep(ctx.result, this.core.summarizeIncident(incidentGr));
            }
        }

        return ctx.result;
    },

    type: 'USBEM_DTI'
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = USBEM_DTI;
}
