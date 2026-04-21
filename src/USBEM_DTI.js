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
        this.PROPERTY_FAST_DTI_EVENT_NAME = 'x_usbna_usb_event.fast_dti_event_name';
        this.PROPERTY_FAST_DTI_LINK_DELAY_SECONDS = 'x_usbna_usb_event.fast_dti_link_delay_seconds';
        this.PROPERTY_FAST_DTI_LINK_MAX_RETRIES = 'x_usbna_usb_event.fast_dti_link_max_retries';
        this.PROPERTY_DTI_MAP_TABLE = 'x_usbna_usb_event.dti_map_table';
        this.PROPERTY_DTI_MAP_PENDING_WAIT_MS = 'x_usbna_usb_event.dti_map_pending_wait_ms';

        this.DEFAULT_FAST_DTI_EVENT_NAME = 'x_usbna_usb_event.link_alert_later';
        this.DEFAULT_FAST_DTI_LINK_DELAY_SECONDS = 10;
        this.DEFAULT_FAST_DTI_LINK_MAX_RETRIES = 6;
        this.DEFAULT_DTI_MAP_PENDING_WAIT_MS = 1500;
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

    getFastDtiEventName: function (trace) {
        return this.getStringProperty(this.PROPERTY_FAST_DTI_EVENT_NAME, this.DEFAULT_FAST_DTI_EVENT_NAME, trace);
    },

    getFastDtiLinkDelaySeconds: function (trace) {
        var n = this.getIntProperty(this.PROPERTY_FAST_DTI_LINK_DELAY_SECONDS, this.DEFAULT_FAST_DTI_LINK_DELAY_SECONDS, trace);
        if (n < 0) {
            n = this.DEFAULT_FAST_DTI_LINK_DELAY_SECONDS;
        }
        return n;
    },

    getFastDtiLinkMaxRetries: function (trace) {
        var n = this.getIntProperty(this.PROPERTY_FAST_DTI_LINK_MAX_RETRIES, this.DEFAULT_FAST_DTI_LINK_MAX_RETRIES, trace);
        if (n < 0) {
            n = this.DEFAULT_FAST_DTI_LINK_MAX_RETRIES;
        }
        return n;
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
        if (incGr.isValidField('work_notes')) {
            incGr.setValue('work_notes', String(value));
        } else if (incGr.isValidField('comments')) {
            incGr.setValue('comments', String(value));
        }
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

    claimAlertForIncident: function (alertSysId, incidentSysId) {
        var claimGr;
        if (!this.core.looksLikeSysId(alertSysId) || !this.core.looksLikeSysId(incidentSysId)) {
            return { claimed: false, incident: null };
        }

        claimGr = new GlideRecord('em_alert');
        claimGr.addQuery('sys_id', alertSysId);
        if (claimGr.isValidField('task')) {
            claimGr.addNullQuery('task');
        } else if (claimGr.isValidField('incident')) {
            claimGr.addNullQuery('incident');
        }
        claimGr.setLimit(1);
        this.queryNow(claimGr);
        if (!claimGr.next()) {
            claimGr = new GlideRecord('em_alert');
            if (claimGr.get(alertSysId)) {
                return { claimed: false, incident: this.getIncidentFromAlert(claimGr) };
            }
            return { claimed: false, incident: null };
        }

        if (claimGr.isValidField('incident')) {
            claimGr.setValue('incident', incidentSysId);
        }
        if (claimGr.isValidField('task')) {
            claimGr.setValue('task', incidentSysId);
        }
        claimGr.update();
        return { claimed: true, incident: null };
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
        var createdIncident;
        var claim;
        var refreshedAlert;

        if (!alertGr) {
            return { incident: null, status: 'alert_not_found' };
        }

        refreshedAlert = this.getAlertBySysId(alertGr.getUniqueValue());
        existingIncident = this.getIncidentFromAlert(refreshedAlert || alertGr);
        if (existingIncident) {
            return { incident: existingIncident, status: 'existing' };
        }

        if (!ctx.dti.allow_incident) {
            return { incident: null, status: 'suppressed_by_severity_map' };
        }

        createdIncident = this.createIncidentRecord(ctx);
        if (!createdIncident) {
            return { incident: null, status: 'create_failed' };
        }

        claim = this.claimAlertForIncident(alertGr.getUniqueValue(), createdIncident.getUniqueValue());
        if (claim.claimed) {
            this.core.tracePush(ctx.debug, 'incident created and linked: ' + createdIncident.getUniqueValue());
            return { incident: createdIncident, status: 'created' };
        }

        if (claim.incident) {
            this.core.tracePush(ctx.debug, 'incident race detected, existing linked incident reused');
            this.deleteIncidentBestEffort(createdIncident);
            return { incident: claim.incident, status: 'existing_after_race' };
        }

        return { incident: createdIncident, status: 'created_unlinked' };
    },

    getExistingIncidentByCorrelationId: function (messageKey, trace) {
        var gr;
        if (!this.core.hasValue(messageKey) || !this.core.tableExists('incident', trace)) {
            return null;
        }
        gr = new GlideRecord('incident');
        if (!gr.isValidField('correlation_id')) {
            return null;
        }
        gr.addQuery('correlation_id', messageKey);
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

        if (!ctx.dti.allow_incident) {
            return { incident: null, status: 'suppressed_by_severity_map' };
        }

        alertGr = this.findAlertByMessageKey(ctx.mapped.message_key, ctx.mapped.source, ctx.mapped.event_class, ctx.debug);
        if (alertGr) {
            existingIncident = this.getIncidentFromAlert(alertGr);
            if (existingIncident) {
                this.upsertMapWithIncident(ctx.mapped.message_key, existingIncident.getUniqueValue(), ctx.result.event_sys_id, ctx.debug);
                return { incident: existingIncident, status: 'existing_from_alert' };
            }
        }

        existingIncident = this.getExistingIncidentByCorrelationId(ctx.mapped.message_key, ctx.debug);
        if (existingIncident) {
            this.upsertMapWithIncident(ctx.mapped.message_key, existingIncident.getUniqueValue(), ctx.result.event_sys_id, ctx.debug);
            return { incident: existingIncident, status: 'existing_from_correlation_id' };
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
        return { incident: createdIncident, status: 'created_fast' };
    },

    buildAsyncLinkPayload: function (ctx, incidentGr, retryCount) {
        return this.core.safeJSONStringify({
            event_sys_id: ctx.result.event_sys_id || '',
            incident_sys_id: incidentGr ? (incidentGr.getUniqueValue() || '') : '',
            message_key: ctx.mapped.message_key || '',
            source: ctx.mapped.source || '',
            event_class: ctx.mapped.event_class || '',
            retry_count: typeof retryCount === 'number' ? retryCount : 0
        });
    },

    parseAsyncLinkPayload: function (parm1, parm2) {
        var parsed = this.core.tryParseJSON(parm2);
        var out = this.core.isObject(parsed) ? parsed : {};
        if (!this.core.hasValue(out.event_sys_id) && this.core.hasValue(parm1)) {
            out.event_sys_id = String(parm1);
        }
        if (!this.core.hasValue(out.retry_count)) {
            out.retry_count = 0;
        } else {
            out.retry_count = this.core.toInt(out.retry_count, 0);
        }
        return out;
    },

    queueScheduledLinkEvent: function (incidentGr, payload, trace) {
        var eventName;
        var delaySeconds;
        var processTime;
        var payloadText;
        if (!incidentGr || !incidentGr.isValidRecord || !incidentGr.isValidRecord()) {
            return false;
        }

        eventName = this.getFastDtiEventName(trace);
        if (!this.core.hasValue(eventName)) {
            return false;
        }
        delaySeconds = this.getFastDtiLinkDelaySeconds(trace);
        payloadText = this.core.isObject(payload) ? this.core.safeJSONStringify(payload) : String(payload || '');

        try {
            if (typeof gs.eventQueueScheduled === 'function') {
                processTime = new GlideDateTime();
                processTime.addSecondsLocalTime(delaySeconds);
                gs.eventQueueScheduled(eventName, incidentGr, payload.event_sys_id || '', payloadText, processTime);
            } else {
                gs.eventQueue(eventName, incidentGr, payload.event_sys_id || '', payloadText);
            }
            return true;
        } catch (eQueue) {
            try {
                gs.eventQueue(eventName, incidentGr, payload.event_sys_id || '', payloadText);
                return true;
            } catch (eQueueFallback) {
                return false;
            }
        }
    },

    queueAlertLinkLater: function (ctx, incidentGr) {
        var payload;
        var queued;
        if (!incidentGr) {
            return false;
        }
        payload = {
            event_sys_id: ctx.result.event_sys_id || '',
            incident_sys_id: incidentGr.getUniqueValue() || '',
            message_key: ctx.mapped.message_key || '',
            source: ctx.mapped.source || '',
            event_class: ctx.mapped.event_class || '',
            retry_count: 0
        };
        queued = this.queueScheduledLinkEvent(incidentGr, payload, ctx.debug);
        if (queued) {
            ctx.result.dti_link_status = 'queued';
            ctx.result.dti_link_event_name = this.getFastDtiEventName(ctx.debug);
        } else {
            ctx.result.dti_link_status = 'queue_failed';
        }
        return queued;
    },

    relinkAlertToIncidentAsync: function (incidentGr, parm1, parm2) {
        var payload;
        var alertGr = null;
        var existingIncident;
        var claim;
        var maxRetries;
        var shouldRetry = false;

        payload = this.parseAsyncLinkPayload(parm1, parm2);
        if (!incidentGr || !incidentGr.isValidRecord || !incidentGr.isValidRecord()) {
            return { status: 'incident_missing' };
        }

        if (this.core.looksLikeSysId(payload.event_sys_id)) {
            alertGr = this.getAlertFromEvent(this.getEventBySysId(payload.event_sys_id));
        }
        if (!alertGr && this.core.hasValue(payload.message_key)) {
            alertGr = this.findAlertByMessageKey(payload.message_key, payload.source, payload.event_class);
        }

        if (!alertGr) {
            maxRetries = this.getFastDtiLinkMaxRetries();
            if (payload.retry_count < maxRetries) {
                payload.retry_count = payload.retry_count + 1;
                shouldRetry = this.queueScheduledLinkEvent(incidentGr, payload);
                return {
                    status: shouldRetry ? 'retry_queued' : 'alert_not_found',
                    retry_count: String(payload.retry_count)
                };
            }
            return {
                status: 'alert_not_found',
                retry_count: String(payload.retry_count)
            };
        }

        existingIncident = this.getIncidentFromAlert(alertGr);
        if (existingIncident) {
            this.upsertMapWithIncident(payload.message_key, existingIncident.getUniqueValue(), payload.event_sys_id, null);
            return {
                status: 'already_linked',
                alert_sys_id: alertGr.getUniqueValue(),
                incident_sys_id: existingIncident.getUniqueValue()
            };
        }

        claim = this.claimAlertForIncident(alertGr.getUniqueValue(), incidentGr.getUniqueValue());
        if (claim.claimed) {
            this.upsertMapWithIncident(payload.message_key, incidentGr.getUniqueValue(), payload.event_sys_id, null);
            return {
                status: 'linked',
                alert_sys_id: alertGr.getUniqueValue(),
                incident_sys_id: incidentGr.getUniqueValue()
            };
        }

        if (claim.incident) {
            this.upsertMapWithIncident(payload.message_key, claim.incident.getUniqueValue(), payload.event_sys_id, null);
            return {
                status: 'already_linked',
                alert_sys_id: alertGr.getUniqueValue(),
                incident_sys_id: claim.incident.getUniqueValue()
            };
        }

        return {
            status: 'link_failed',
            alert_sys_id: alertGr.getUniqueValue(),
            incident_sys_id: incidentGr.getUniqueValue()
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
            this.queueAlertLinkLater(ctx, outcome.incident);
        }
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

