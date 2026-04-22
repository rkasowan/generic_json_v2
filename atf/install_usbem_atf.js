(function () {
    var CONFIG = {
        suite_parent_name: 'USBEM',
        suite_parent_description: 'Parent ATF suite for USBEM connector coverage.',
        suite_name: 'USBEM genericJsonV2 API Coverage',
        suite_description: 'Automated coverage for the USBEM genericJsonV2 inbound connector.',
        test_prefix: 'USBEM genericJsonV2 - ',
        helper_include_name: 'USBEM_ATF_Helper',
        auth_profile_name: 'USBEM ATF Local Admin',
        auth_profile_sys_id: '',
        auth_profile_username: '',
        auth_profile_password: '',
        basic_auth_username: '',
        basic_auth_password: '',
        enable_runner_if_disabled: true,
        delete_existing_assets: true,
        test_active: true
    };

    var STEP_CONFIGS = {
        run_server_script: '41de4a935332120028bc29cac2dc349a'
    };

    function hasValue(value) {
        return value !== null && typeof value !== 'undefined' && String(value).replace(/^\s+|\s+$/g, '') !== '';
    }

    function trim(value) {
        return hasValue(value) ? String(value).replace(/^\s+|\s+$/g, '') : '';
    }

    function log(message) {
        gs.print('USBEM ATF installer: ' + message);
    }

    function setIfValid(gr, fieldName, value) {
        if (gr && gr.isValidField && gr.isValidField(fieldName) && typeof value !== 'undefined') {
            gr.setValue(fieldName, value);
        }
    }

    function deleteAll(gr) {
        gr.query();
        while (gr.next()) {
            gr.deleteRecord();
        }
    }

    function ensureRunnerEnabled() {
        var prop;
        if (!CONFIG.enable_runner_if_disabled) {
            return;
        }
        prop = new GlideRecord('sys_properties');
        if (prop.get('99ca5ab55b1022001f80efe5f0f91a05')) {
            if (prop.getValue('value') !== 'true') {
                prop.setValue('value', 'true');
                prop.update();
                log('Enabled sn_atf.runner.enabled');
            }
        }
    }

    function findAuthProfileByName(profileName) {
        var gr;
        if (!hasValue(profileName)) {
            return null;
        }
        gr = new GlideRecord('sys_auth_profile_basic');
        if (gr.isValidField('name')) {
            gr.addQuery('name', profileName);
        } else if (gr.isValidField('sys_name')) {
            gr.addQuery('sys_name', profileName);
        }
        gr.setLimit(1);
        gr.query();
        if (gr.next()) {
            return gr;
        }
        return null;
    }

    function ensureAuthProfile() {
        var gr;
        var sysId = trim(CONFIG.auth_profile_sys_id);
        var profileName = trim(CONFIG.auth_profile_name);
        var profileUser = trim(CONFIG.auth_profile_username);
        var profilePassword = CONFIG.auth_profile_password;

        if (hasValue(sysId)) {
            gr = new GlideRecord('sys_auth_profile_basic');
            if (gr.get(sysId)) {
                return gr.getUniqueValue();
            }
        }

        gr = findAuthProfileByName(profileName);
        if (gr) {
            if (hasValue(profileUser) && gr.isValidField('username') && gr.getValue('username') !== profileUser) {
                gr.setValue('username', profileUser);
            }
            if (hasValue(profilePassword) && gr.isValidField('password')) {
                gr.setValue('password', profilePassword);
            }
            gr.update();
            log('Using auth profile ' + profileName + ' (' + gr.getUniqueValue() + ')');
            return gr.getUniqueValue();
        }

        if (!hasValue(profileUser) || !hasValue(profilePassword)) {
            throw new Error('Auth profile not found. Set CONFIG.auth_profile_sys_id or provide CONFIG.auth_profile_username/password.');
        }

        gr = new GlideRecord('sys_auth_profile_basic');
        gr.initialize();
        if (gr.isValidField('name')) {
            gr.setValue('name', profileName);
        }
        if (gr.isValidField('username')) {
            gr.setValue('username', profileUser);
        }
        if (gr.isValidField('password')) {
            gr.setValue('password', profilePassword);
        }
        gr.insert();
        log('Created auth profile ' + profileName + ' (' + gr.getUniqueValue() + ')');
        return gr.getUniqueValue();
    }

    function helperScriptSource() {
        return [
            'var USBEM_ATF_Helper = Class.create();',
            'USBEM_ATF_Helper.prototype = {',
            '    initialize: function (options) {',
            '        options = options || {};',
            '        this.authProfileSysId = options.authProfileSysId || "";',
            '        this.basicAuthUsername = options.basicAuthUsername || "";',
            '        this.basicAuthPassword = options.basicAuthPassword || "";',
            '        this.baseUrl = gs.getProperty("glide.servlet.uri", "");',
            '    },',
            '',
            '    hasValue: function (value) {',
            '        return value !== null && typeof value !== "undefined" && String(value).replace(/^\\s+|\\s+$/g, "") !== "";',
            '    },',
            '',
            '    trim: function (value) {',
            '        return this.hasValue(value) ? String(value).replace(/^\\s+|\\s+$/g, "") : "";',
            '    },',
            '',
            '    setIfValid: function (gr, fieldName, value) {',
            '        if (gr && gr.isValidField && gr.isValidField(fieldName) && typeof value !== "undefined") {',
            '            gr.setValue(fieldName, value);',
            '        }',
            '    },',
            '',
            '    fail: function (message) {',
            '        throw new Error(message);',
            '    },',
            '',
            '    assertTrue: function (condition, message) {',
            '        if (!condition) {',
            '            this.fail(message || "Assertion failed");',
            '        }',
            '    },',
            '',
            '    assertEquals: function (expected, actual, message) {',
            '        if (String(expected) !== String(actual)) {',
            '            this.fail((message || "Values do not match") + " expected=[" + expected + "] actual=[" + actual + "]");',
            '        }',
            '    },',
            '',
            '    assertBlank: function (actual, message) {',
            '        if (this.hasValue(actual)) {',
            '            this.fail((message || "Value should be blank") + " actual=[" + actual + "]");',
            '        }',
            '    },',
            '',
            '    safeParseJson: function (text) {',
            '        if (!this.hasValue(text)) {',
            '            return null;',
            '        }',
            '        try {',
            '            return JSON.parse(String(text));',
            '        } catch (e) {',
            '            return null;',
            '        }',
            '    },',
            '',
            '    parseAdditionalInfo: function (gr) {',
            '        var raw;',
            '        if (!gr || !gr.isValidField || !gr.isValidField("additional_info")) {',
            '            return {};',
            '        }',
            '        raw = gr.getValue("additional_info") || "";',
            '        return this.safeParseJson(raw) || {};',
            '    },',
            '',
            '    cleanupByMessageKeys: function (keys) {',
            '        var i;',
            '        var ev;',
            '        var al;',
            '        var inc;',
            '        var dbg;',
            '        if (!keys || !keys.length) {',
            '            return;',
            '        }',
            '        for (i = 0; i < keys.length; i++) {',
            '            ev = new GlideRecord("em_event");',
            '            if (ev.isValidField("message_key")) {',
            '                ev.addQuery("message_key", keys[i]);',
            '                ev.query();',
            '                while (ev.next()) {',
            '                    ev.deleteRecord();',
            '                }',
            '            }',
            '            al = new GlideRecord("em_alert");',
            '            if (al.isValid() && al.isValidField("message_key")) {',
            '                al.addQuery("message_key", keys[i]);',
            '                al.query();',
            '                while (al.next()) {',
            '                    al.deleteRecord();',
            '                }',
            '            }',
            '            inc = new GlideRecord("incident");',
            '            if (inc.isValidField("correlation_id")) {',
            '                inc.addQuery("correlation_id", keys[i]);',
            '                inc.query();',
            '                while (inc.next()) {',
            '                    inc.deleteRecord();',
            '                }',
            '            }',
            '            dbg = new GlideRecord("em_event");',
            '            dbg.addQuery("source", "USBEM Debug");',
            '            dbg.addQuery("additional_info", "CONTAINS", keys[i]);',
            '            dbg.query();',
            '            while (dbg.next()) {',
            '                dbg.deleteRecord();',
            '            }',
            '        }',
            '    },',
            '',
            '    deleteByName: function (tableName, nameValue) {',
            '        var gr = new GlideRecord(tableName);',
            '        if (!gr.isValid() || !gr.isValidField("name")) {',
            '            return;',
            '        }',
            '        gr.addQuery("name", nameValue);',
            '        gr.query();',
            '        while (gr.next()) {',
            '            gr.deleteRecord();',
            '        }',
            '    },',
            '',
            '    ensureRecord: function (tableName, queryField, queryValue, values) {',
            '        var gr = new GlideRecord(tableName);',
            '        var field;',
            '        if (!gr.isValid()) {',
            '            this.fail("Invalid table: " + tableName);',
            '        }',
            '        if (!gr.isValidField(queryField)) {',
            '            this.fail("Invalid query field " + queryField + " on " + tableName);',
            '        }',
            '        gr.addQuery(queryField, queryValue);',
            '        gr.setLimit(1);',
            '        gr.query();',
            '        if (!gr.next()) {',
            '            gr.initialize();',
            '            gr.setValue(queryField, queryValue);',
            '        }',
            '        values = values || {};',
            '        for (field in values) {',
            '            if (values.hasOwnProperty(field) && gr.isValidField(field) && typeof values[field] !== "undefined") {',
            '                gr.setValue(field, values[field]);',
            '            }',
            '        }',
            '        if (gr.isNewRecord()) {',
            '            gr.insert();',
            '        } else {',
            '            gr.update();',
            '        }',
            '        return gr.getUniqueValue();',
            '    },',
            '',
            '    ensureGroup: function (nameValue) {',
            '        return this.ensureRecord("sys_user_group", "name", nameValue, { active: true });',
            '    },',
            '',
            '    ensureCi: function (tableName, nameValue, extraValues) {',
            '        var values = extraValues || {};',
            '        if (typeof values.name === "undefined") {',
            '            values.name = nameValue;',
            '        }',
            '        if (typeof values.operational_status === "undefined") {',
            '            values.operational_status = "1";',
            '        }',
            '        if (typeof values.install_status === "undefined") {',
            '            values.install_status = "1";',
            '        }',
            '        if (typeof values.active === "undefined") {',
            '            values.active = true;',
            '        }',
            '        return this.ensureRecord(tableName, "name", nameValue, values);',
            '    },',
            '',
            '    ensureBusinessApp: function (nameValue, carIdValue) {',
            '        var gr = new GlideRecord("cmdb_ci_business_app");',
            '        var values = { name: nameValue, operational_status: "1", install_status: "1", active: true };',
            '        if (!gr.isValid()) {',
            '            this.fail("cmdb_ci_business_app is not available");',
            '        }',
            '        if (gr.isValidField("u_car_id") && this.hasValue(carIdValue)) {',
            '            return this.ensureRecord("cmdb_ci_business_app", "u_car_id", carIdValue, values);',
            '        }',
            '        return this.ensureRecord("cmdb_ci_business_app", "name", nameValue, values);',
            '    },',
            '',
            '    ensureService: function (nameValue) {',
            '        var gr = new GlideRecord("cmdb_ci_service");',
            '        if (!gr.isValid()) {',
            '            this.fail("cmdb_ci_service is not available");',
            '        }',
            '        gr.addQuery("name", nameValue);',
            '        if (gr.isValidField("sys_class_name")) {',
            '            gr.addQuery("sys_class_name", "cmdb_ci_service");',
            '        }',
            '        gr.setLimit(1);',
            '        gr.query();',
            '        if (!gr.next()) {',
            '            gr.initialize();',
            '            gr.setValue("name", nameValue);',
            '            if (gr.isValidField("number")) {',
            '                gr.setValue("number", "BSNATF" + String(gs.generateGUID()).replace(/-/g, "").substring(0, 10));',
            '            }',
            '            if (gr.isValidField("sys_class_name")) {',
            '                gr.setValue("sys_class_name", "cmdb_ci_service");',
            '            }',
            '        }',
            '        if (gr.isValidField("operational_status")) {',
            '            gr.setValue("operational_status", "1");',
            '        }',
            '        if (gr.isValidField("install_status")) {',
            '            gr.setValue("install_status", "1");',
            '        }',
            '        if (gr.isValidField("active")) {',
            '            gr.setValue("active", true);',
            '        }',
            '        if (gr.isValidField("service_classification")) {',
            '            gr.setValue("service_classification", "Business Service");',
            '        }',
            '        if (gr.isValidField("portfolio_status")) {',
            '            gr.setValue("portfolio_status", "pipeline");',
            '        }',
            '        if (gr.isValidField("service_status")) {',
            '            gr.setValue("service_status", "requirements");',
            '        }',
            '        if (gr.isNewRecord()) {',
            '            gr.insert();',
            '        } else {',
            '            gr.update();',
            '        }',
            '        return gr.getUniqueValue();',
            '    },',
            '',
            '    ensureOffering: function (nameValue, parentSysId) {',
            '        var gr = new GlideRecord("service_offering");',
            '        if (!gr.isValid()) {',
            '            this.fail("service_offering is not available");',
            '        }',
            '        gr.addQuery("name", nameValue);',
            '        if (gr.isValidField("parent") && this.hasValue(parentSysId)) {',
            '            gr.addQuery("parent", parentSysId);',
            '        }',
            '        gr.setLimit(1);',
            '        gr.query();',
            '        if (!gr.next()) {',
            '            gr.initialize();',
            '            gr.setValue("name", nameValue);',
            '            if (gr.isValidField("number")) {',
            '                gr.setValue("number", "BSNOATF" + String(gs.generateGUID()).replace(/-/g, "").substring(0, 9));',
            '            }',
            '        }',
            '        if (gr.isValidField("parent") && this.hasValue(parentSysId)) {',
            '            gr.setValue("parent", parentSysId);',
            '        }',
            '        if (gr.isValidField("active")) {',
            '            gr.setValue("active", true);',
            '        }',
            '        if (gr.isValidField("operational_status")) {',
            '            gr.setValue("operational_status", "1");',
            '        }',
            '        if (gr.isValidField("install_status")) {',
            '            gr.setValue("install_status", "1");',
            '        }',
            '        if (gr.isNewRecord()) {',
            '            gr.insert();',
            '        } else {',
            '            gr.update();',
            '        }',
            '        return gr.getUniqueValue();',
            '    },',
            '',
            '    ensureSvcAssoc: function (ciSysId, serviceSysId) {',
            '        var gr = new GlideRecord("svc_ci_assoc");',
            '        if (!gr.isValid()) {',
            '            return "";',
            '        }',
            '        if (!gr.isValidField("ci_id") || !gr.isValidField("service_id")) {',
            '            return "";',
            '        }',
            '        gr.addQuery("ci_id", ciSysId);',
            '        gr.addQuery("service_id", serviceSysId);',
            '        gr.setLimit(1);',
            '        gr.query();',
            '        if (!gr.next()) {',
            '            gr.initialize();',
            '            gr.setValue("ci_id", ciSysId);',
            '            gr.setValue("service_id", serviceSysId);',
            '            if (gr.isValidField("ignore_errors")) {',
            '                gr.setValue("ignore_errors", false);',
            '            }',
            '            gr.insert();',
            '        }',
            '        return gr.getUniqueValue();',
            '    },',
            '',
            '    getLatestByField: function (tableName, fieldName, value) {',
            '        var gr = new GlideRecord(tableName);',
            '        if (!gr.isValid() || !gr.isValidField(fieldName)) {',
            '            return null;',
            '        }',
            '        gr.addQuery(fieldName, value);',
            '        gr.orderByDesc("sys_created_on");',
            '        gr.setLimit(1);',
            '        gr.query();',
            '        if (gr.next()) {',
            '            return gr;',
            '        }',
            '        return null;',
            '    },',
            '',
            '    getEventByMessageKey: function (messageKey) {',
            '        return this.getLatestByField("em_event", "message_key", messageKey);',
            '    },',
            '',
            '    getAlertByMessageKey: function (messageKey) {',
            '        return this.getLatestByField("em_alert", "message_key", messageKey);',
            '    },',
            '',
            '    getIncidentByCorrelationId: function (messageKey) {',
            '        return this.getLatestByField("incident", "correlation_id", messageKey);',
            '    },',
            '',
            '    countByField: function (tableName, fieldName, value) {',
            '        var gr = new GlideRecord(tableName);',
            '        if (!gr.isValid() || !gr.isValidField(fieldName)) {',
            '            return 0;',
            '        }',
            '        gr.addQuery(fieldName, value);',
            '        gr.query();',
            '        return gr.getRowCount();',
            '    },',
            '',
            '    waitForLatestByField: function (tableName, fieldName, value, timeoutMs) {',
            '        var deadlineMs = new Date().getTime() + (parseInt(timeoutMs, 10) || 20000);',
            '        var nextPollAt = 0;',
            '        var now;',
            '        var gr;',
            '        while (true) {',
            '            now = new Date().getTime();',
            '            if (now >= deadlineMs) {',
            '                break;',
            '            }',
            '            if (now < nextPollAt) {',
            '                continue;',
            '            }',
            '            nextPollAt = now + 250;',
            '            gr = this.getLatestByField(tableName, fieldName, value);',
            '            if (gr) {',
            '                return gr;',
            '            }',
            '        }',
            '        return this.getLatestByField(tableName, fieldName, value);',
            '    },',
            '',
            '    waitForAlertByMessageKey: function (messageKey, timeoutMs) {',
            '        return this.waitForLatestByField("em_alert", "message_key", messageKey, timeoutMs);',
            '    },',
            '',
            '    waitForIncidentByCorrelationId: function (messageKey, timeoutMs) {',
            '        return this.waitForLatestByField("incident", "correlation_id", messageKey, timeoutMs);',
            '    },',
            '',
            '    getAlertIncidentSysId: function (alertGr) {',
            '        var sysId = "";',
            '        if (!alertGr) {',
            '            return "";',
            '        }',
            '        if (alertGr.isValidField("incident")) {',
            '            sysId = alertGr.getValue("incident") || "";',
            '            if (this.hasValue(sysId)) {',
            '                return sysId;',
            '            }',
            '        }',
            '        if (alertGr.isValidField("task")) {',
            '            sysId = alertGr.getValue("task") || "";',
            '            if (this.hasValue(sysId)) {',
            '                return sysId;',
            '            }',
            '        }',
            '        return "";',
            '    },',
            '',
            '    waitForSingleLinkedIncident: function (messageKey, timeoutMs) {',
            '        var deadlineMs = new Date().getTime() + (parseInt(timeoutMs, 10) || 25000);',
            '        var nextPollAt = 0;',
            '        var now;',
            '        var alertGr;',
            '        var incidentGr;',
            '        var linkedIncidentSysId = "";',
            '        var incidentCount = 0;',
            '        while (true) {',
            '            now = new Date().getTime();',
            '            if (now >= deadlineMs) {',
            '                break;',
            '            }',
            '            if (now < nextPollAt) {',
            '                continue;',
            '            }',
            '            nextPollAt = now + 250;',
            '            alertGr = this.getAlertByMessageKey(messageKey);',
            '            incidentGr = this.getIncidentByCorrelationId(messageKey);',
            '            incidentCount = this.countByField("incident", "correlation_id", messageKey);',
            '            linkedIncidentSysId = this.getAlertIncidentSysId(alertGr);',
            '        }',
            '        alertGr = this.getAlertByMessageKey(messageKey);',
            '        incidentGr = this.getIncidentByCorrelationId(messageKey);',
            '        incidentCount = this.countByField("incident", "correlation_id", messageKey);',
            '        linkedIncidentSysId = this.getAlertIncidentSysId(alertGr);',
            '        return {',
            '            alert: alertGr,',
            '            incident: incidentGr,',
            '            linkedIncidentSysId: linkedIncidentSysId,',
            '            incidentCount: incidentCount',
            '        };',
            '    },',
            '',
            '    getDebugEventByParentKey: function (messageKey) {',
            '        var gr = new GlideRecord("em_event");',
            '        gr.addQuery("source", "USBEM Debug");',
            '        gr.addQuery("additional_info", "CONTAINS", messageKey);',
            '        gr.orderByDesc("sys_created_on");',
            '        gr.setLimit(1);',
            '        gr.query();',
            '        if (gr.next()) {',
            '            return gr;',
            '        }',
            '        return null;',
            '    },',
            '',
            '    getAttachmentByName: function (tableName, recordSysId, fileName) {',
            '        var gr = new GlideRecord("sys_attachment");',
            '        gr.addQuery("table_name", tableName);',
            '        gr.addQuery("table_sys_id", recordSysId);',
            '        gr.addQuery("file_name", fileName);',
            '        gr.orderByDesc("sys_created_on");',
            '        gr.setLimit(1);',
            '        gr.query();',
            '        if (gr.next()) {',
            '            return gr;',
            '        }',
            '        return null;',
            '    },',
            '',
            '    getAttachmentText: function (tableName, recordSysId, fileName) {',
            '        var attachment = this.getAttachmentByName(tableName, recordSysId, fileName);',
            '        var bytes;',
            '        if (!attachment) {',
            '            return "";',
            '        }',
            '        bytes = new GlideSysAttachment().getBytes(attachment);',
            '        if (!bytes) {',
            '            return "";',
            '        }',
            '        return String(Packages.java.lang.String(bytes, "UTF-8"));',
            '    },',
            '',
            '    getAttachmentJson: function (tableName, recordSysId, fileName) {',
            '        return this.safeParseJson(this.getAttachmentText(tableName, recordSysId, fileName)) || null;',
            '    },',
            '',
            '    unwrapConnectorResponse: function (bodyText) {',
            '        var parsed = this.safeParseJson(bodyText) || {};',
            '        var inner;',
            '        var key;',
            '        if (parsed.result) {',
            '            for (key in parsed.result) {',
            '                if (parsed.result.hasOwnProperty(key)) {',
            '                    inner = parsed.result[key];',
            '                    break;',
            '                }',
            '            }',
            '        }',
            '        if (typeof inner === "string") {',
            '            inner = this.safeParseJson(inner) || { raw: inner };',
            '        }',
            '        if (!inner) {',
            '            inner = parsed;',
            '        }',
            '        return { outer: parsed, inner: inner };',
            '    },',
            '',
            '    postPayload: function (payload) {',
            '        var rm;',
            '        var response;',
            '        if (!this.hasValue(this.basicAuthUsername) && !this.hasValue(this.authProfileSysId)) {',
            '            this.fail("Either inline basic auth credentials or authProfileSysId is required");',
            '        }',
            '        rm = new sn_ws.RESTMessageV2();',
            '        rm.setHttpMethod("post");',
            '        rm.setEndpoint(this.baseUrl + "api/sn_em_connector/em/inbound_event?source=genericJsonV2");',
            '        if (this.hasValue(this.basicAuthUsername) && this.hasValue(this.basicAuthPassword)) {',
            '            rm.setBasicAuth(this.basicAuthUsername, this.basicAuthPassword);',
            '        } else {',
            '            rm.setAuthenticationProfile("basic", this.authProfileSysId);',
            '        }',
            '        rm.setRequestHeader("Content-Type", "application/json");',
            '        rm.setRequestBody(typeof payload === "string" ? payload : JSON.stringify(payload));',
            '        response = rm.execute();',
            '        return {',
            '            status: response.getStatusCode(),',
            '            body: response.getBody(),',
            '            parsed: this.unwrapConnectorResponse(response.getBody())',
            '        };',
            '    },',
            '',
            '    assertConnectorSuccess: function (response, minimumInserted) {',
            '        var inner = response && response.parsed ? response.parsed.inner : null;',
            '        this.assertEquals("200", response.status, "Unexpected HTTP status");',
            '        this.assertTrue(!!inner, "Missing parsed connector payload");',
            '        this.assertEquals("success", inner.status, "Connector status was not success");',
            '        if (this.hasValue(minimumInserted)) {',
            '            this.assertEquals(String(minimumInserted), inner.inserted, "Unexpected inserted count");',
            '        }',
            '        return inner;',
            '    },',
            '',
            '    type: "USBEM_ATF_Helper"',
            '};'
        ].join('\n');
    }

    function ensureHelperInclude() {
        var script = helperScriptSource();
        var gr = new GlideRecord('sys_script_include');
        gr.addQuery('name', CONFIG.helper_include_name);
        gr.setLimit(1);
        gr.query();
        if (!gr.next()) {
            gr.initialize();
            gr.setValue('name', CONFIG.helper_include_name);
        }
        setIfValid(gr, 'script', script);
        setIfValid(gr, 'active', true);
        setIfValid(gr, 'client_callable', false);
        if (gr.isNewRecord()) {
            gr.insert();
            log('Created helper include ' + CONFIG.helper_include_name);
        } else {
            gr.update();
            log('Updated helper include ' + CONFIG.helper_include_name);
        }
    }

    function deleteExistingAssets() {
        var suite;
        var suiteTest;
        var test;
        var step;

        if (!CONFIG.delete_existing_assets) {
            return;
        }

        suite = new GlideRecord('sys_atf_test_suite');
        suite.addQuery('name', CONFIG.suite_name);
        suite.query();
        while (suite.next()) {
            suiteTest = new GlideRecord('sys_atf_test_suite_test');
            suiteTest.addQuery('test_suite', suite.getUniqueValue());
            deleteAll(suiteTest);
            suite.deleteRecord();
        }

        test = new GlideRecord('sys_atf_test');
        test.addQuery('name', 'STARTSWITH', CONFIG.test_prefix);
        test.query();
        while (test.next()) {
            step = new GlideRecord('sys_atf_step');
            step.addQuery('test', test.getUniqueValue());
            deleteAll(step);
            test.deleteRecord();
        }
    }

    function findSuiteByName(nameValue, parentSysId) {
        var suite = new GlideRecord('sys_atf_test_suite');
        suite.addQuery('name', nameValue);
        if (hasValue(parentSysId) && suite.isValidField('parent')) {
            suite.addQuery('parent', parentSysId);
        } else if (suite.isValidField('parent')) {
            suite.addNullQuery('parent');
        }
        suite.setLimit(1);
        suite.query();
        if (suite.next()) {
            return suite;
        }
        return null;
    }

    function ensureSuite(nameValue, descriptionValue, parentSysId) {
        var suite = new GlideRecord('sys_atf_test_suite');
        var existing = findSuiteByName(nameValue, parentSysId);

        if (existing) {
            suite = existing;
        } else {
            suite.initialize();
            suite.setValue('name', nameValue);
        }
        suite.setValue('description', descriptionValue);
        suite.setValue('active', true);
        if (suite.isValidField('parent')) {
            if (hasValue(parentSysId)) {
                suite.setValue('parent', parentSysId);
            } else {
                suite.setValue('parent', '');
            }
        }
        if (suite.isNewRecord()) {
            suite.insert();
        } else {
            suite.update();
        }
        return suite.getUniqueValue();
    }

    function createTest(nameSuffix, description, suiteSysId, suiteOrder) {
        var test = new GlideRecord('sys_atf_test');
        var suiteTest = new GlideRecord('sys_atf_test_suite_test');
        test.initialize();
        test.setValue('name', CONFIG.test_prefix + nameSuffix);
        test.setValue('description', description);
        test.setValue('active', CONFIG.test_active);
        setIfValid(test, 'fail_on_server_error', true);
        test.insert();

        suiteTest.initialize();
        suiteTest.setValue('test_suite', suiteSysId);
        suiteTest.setValue('test', test.getUniqueValue());
        if (hasValue(suiteOrder)) {
            suiteTest.setValue('order', suiteOrder);
        }
        suiteTest.insert();
        return test.getUniqueValue();
    }

    function addServerScriptStep(testSysId, order, scriptText) {
        var step = new GlideRecord('sys_atf_step');
        step.initialize();
        step.setValue('test', testSysId);
        step.setValue('order', order);
        step.setValue('step_config', STEP_CONFIGS.run_server_script);
        step.inputs.jasmine_version = '3.1';
        step.inputs.script = scriptText;
        step.insert();
        return step.getUniqueValue();
    }

    function buildScript(lines) {
        return lines.join('\n');
    }

    function commonHeader(authProfileSysId) {
        return [
            '(function(outputs, steps, params, stepResult, assertEqual) {',
            '    var h = new USBEM_ATF_Helper({ authProfileSysId: "' + authProfileSysId + '", basicAuthUsername: "' + String(CONFIG.basic_auth_username).replace(/"/g, '\\"') + '", basicAuthPassword: "' + String(CONFIG.basic_auth_password).replace(/"/g, '\\"') + '" });'
        ];
    }

    function commonFooter() {
        return [
            '    return true;',
            '})(outputs, steps, params, stepResult, assertEqual);'
        ];
    }

    function mergeScript(parts) {
        return buildScript(parts[0].concat(parts[1]).concat(parts[2]));
    }

    function setupScript(authProfileSysId, bodyLines) {
        return mergeScript([commonHeader(authProfileSysId), bodyLines, commonFooter()]);
    }

    function createTests(authProfileSysId, suiteSysId) {
        var testSysId;
        var keys;

        testSysId = createTest(
            '01 Field Mapping And Generated Message Key',
            'Covers single-record field mapping, generated message_key, resolution_state/time_of_event, and additional_info object handling.',
            suiteSysId,
            100
        );
        keys = ['ZZ_USBEM_ATF_FIELDSfields-nodemetricAlertapp-1cpu'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        source: "ZZ_USBEM_ATF_FIELDS",',
            '        event_class: "USBEM ATF",',
            '        node: "fields-node",',
            '        type: "metricAlert",',
            '        resource: "app-1",',
            '        metric_name: "cpu",',
            '        severity: "2",',
            '        description: "Field mapping test",',
            '        resolution_state: "New",',
            '        time_of_event: "2026-04-21 10:00:00",',
            '        additional_info: { extra_flag: "yes", extra_count: "7" }',
            '    };',
            '    var response = h.postPayload(payload);',
            '    var inner = h.assertConnectorSuccess(response, 1);',
            '    h.assertEquals("ZZ_USBEM_ATF_FIELDSfields-nodemetricAlertapp-1cpu", inner.message_key, "Unexpected generated message_key");',
            '    stepResult.setOutputMessage(JSON.stringify({ status: response.status, message_key: inner.message_key }));'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var ev = h.getEventByMessageKey("ZZ_USBEM_ATF_FIELDSfields-nodemetricAlertapp-1cpu");',
            '    var ai;',
            '    h.assertTrue(!!ev, "Event was not inserted");',
            '    h.assertEquals("ZZ_USBEM_ATF_FIELDS", ev.getValue("source"), "source mismatch");',
            '    h.assertEquals("USBEM ATF", ev.getValue("event_class"), "event_class mismatch");',
            '    h.assertEquals("fields-node", ev.getValue("node"), "node mismatch");',
            '    h.assertEquals("metricAlert", ev.getValue("type"), "type mismatch");',
            '    h.assertEquals("app-1", ev.getValue("resource"), "resource mismatch");',
            '    h.assertEquals("cpu", ev.getValue("metric_name"), "metric_name mismatch");',
            '    h.assertEquals("2", ev.getValue("severity"), "severity mismatch");',
            '    h.assertEquals("Field mapping test", ev.getValue("description"), "description mismatch");',
            '    h.assertEquals("2026-04-21 10:00:00", ev.getValue("time_of_event"), "time_of_event mismatch");',
            '    h.assertEquals("New", ev.getDisplayValue("resolution_state"), "resolution_state mismatch");',
            '    ai = h.parseAdditionalInfo(ev);',
            '    h.assertEquals("yes", ai.extra_flag, "extra_flag missing from additional_info");',
            '    h.assertEquals("7", ai.extra_count, "extra_count missing from additional_info");'
        ]));

        testSysId = createTest(
            '02 Bulk Events Wrapper And Legacy additional_info String',
            'Covers the events[] bulk wrapper and escaped-string additional_info parsing/promotion.',
            suiteSysId,
            200
        );
        keys = ['ZZ_USBEM_ATF_BULK_1', 'ZZ_USBEM_ATF_BULK_2'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        events: [',
            '            {',
            '                source: "USBEM_ATF",',
            '                event_class: "USBEM ATF",',
            '                node: "bulk-1",',
            '                resource: "resource-1",',
            '                metric_name: "metric-1",',
            '                severity: "3",',
            '                message_key: "ZZ_USBEM_ATF_BULK_1",',
            '                description: "Bulk event 1",',
            '                additional_info: "{\\"legacy_flag\\":\\"yes\\",\\"legacy_owner\\":\\"ops\\"}"',
            '            },',
            '            {',
            '                source: "USBEM_ATF",',
            '                event_class: "USBEM ATF",',
            '                node: "bulk-2",',
            '                resource: "resource-2",',
            '                metric_name: "metric-2",',
            '                severity: "4",',
            '                message_key: "ZZ_USBEM_ATF_BULK_2",',
            '                additional_info: "{\\"description\\":\\"Legacy promoted description\\",\\"legacy_note\\":\\"lifted\\"}"',
            '            }',
            '        ]',
            '    };',
            '    var response = h.postPayload(payload);',
            '    var inner = h.assertConnectorSuccess(response, 2);',
            '    h.assertEquals("2", inner.inserted, "Expected two inserted records");'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var ev1 = h.getEventByMessageKey("ZZ_USBEM_ATF_BULK_1");',
            '    var ev2 = h.getEventByMessageKey("ZZ_USBEM_ATF_BULK_2");',
            '    var ai1;',
            '    var ai2;',
            '    h.assertTrue(!!ev1 && !!ev2, "Bulk events were not both inserted");',
            '    ai1 = h.parseAdditionalInfo(ev1);',
            '    ai2 = h.parseAdditionalInfo(ev2);',
            '    h.assertEquals("yes", ai1.legacy_flag, "legacy_flag missing");',
            '    h.assertEquals("ops", ai1.legacy_owner, "legacy_owner missing");',
            '    h.assertEquals("Legacy promoted description", ev2.getValue("description"), "description was not promoted from additional_info string");',
            '    h.assertEquals("lifted", ai2.legacy_note, "legacy_note missing");'
        ]));

        testSysId = createTest(
            '03 Assignment Group Exact Canonical And Sys Id',
            'Covers assignment_group direct sys_id use plus exact and canonicalized name resolution.',
            suiteSysId,
            300
        );
        keys = ['ZZ_USBEM_ATF_AG_SYSID', 'ZZ_USBEM_ATF_AG_EXACT', 'ZZ_USBEM_ATF_AG_CANON'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    var groupId = h.ensureGroup("ZZ USBEM ATF Ops Team");',
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');',
            '    stepResult.setOutputMessage("group=" + groupId);'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var groupId = h.ensureGroup("ZZ USBEM ATF Ops Team");',
            '    var payload = {',
            '        records: [',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "ag-sysid", resource: "r1", metric_name: "m1", severity: "3", message_key: "ZZ_USBEM_ATF_AG_SYSID", assignment_group: groupId },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "ag-exact", resource: "r2", metric_name: "m2", severity: "3", message_key: "ZZ_USBEM_ATF_AG_EXACT", assignment_group: "ZZ USBEM ATF Ops Team" },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "ag-canon", resource: "r3", metric_name: "m3", severity: "3", message_key: "ZZ_USBEM_ATF_AG_CANON", assignment_group: "zz_usbem_atf_ops_team" }',
            '        ]',
            '    };',
            '    h.assertConnectorSuccess(h.postPayload(payload), 3);'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var groupId = h.ensureGroup("ZZ USBEM ATF Ops Team");',
            '    var aiSys = h.parseAdditionalInfo(h.getEventByMessageKey("ZZ_USBEM_ATF_AG_SYSID"));',
            '    var aiExact = h.parseAdditionalInfo(h.getEventByMessageKey("ZZ_USBEM_ATF_AG_EXACT"));',
            '    var aiCanon = h.parseAdditionalInfo(h.getEventByMessageKey("ZZ_USBEM_ATF_AG_CANON"));',
            '    h.assertEquals(groupId, aiSys.assignment_group, "sys_id assignment group did not persist");',
            '    h.assertEquals(groupId, aiExact.assignment_group, "exact assignment group lookup failed");',
            '    h.assertEquals(groupId, aiCanon.assignment_group, "canonical assignment group lookup failed");'
        ]));

        testSysId = createTest(
            '04 CI Lookup Exact Canonical Sys Id ci_type And No Match',
            'Covers cmdb_ci direct sys_id, exact name, canonical name, human-readable ci_type lookup, and blank-on-no-match behavior.',
            suiteSysId,
            400
        );
        keys = ['ZZ_USBEM_ATF_CI_SYSID', 'ZZ_USBEM_ATF_CI_EXACT', 'ZZ_USBEM_ATF_CI_CANON', 'ZZ_USBEM_ATF_CI_TYPE', 'ZZ_USBEM_ATF_CI_NOMATCH'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    var ciId = h.ensureCi("cmdb_ci_server", "ZZ USBEM ATF Money Movement");',
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');',
            '    stepResult.setOutputMessage("ci=" + ciId);'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var ciId = h.ensureCi("cmdb_ci_server", "ZZ USBEM ATF Money Movement");',
            '    var payload = {',
            '        records: [',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "ci-sysid", resource: "r1", metric_name: "m1", severity: "3", message_key: "ZZ_USBEM_ATF_CI_SYSID", cmdb_ci: ciId },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "ci-exact", resource: "r2", metric_name: "m2", severity: "3", message_key: "ZZ_USBEM_ATF_CI_EXACT", cmdb_ci: "ZZ USBEM ATF Money Movement" },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "ci-canon", resource: "r3", metric_name: "m3", severity: "3", message_key: "ZZ_USBEM_ATF_CI_CANON", cmdb_ci: "zz_usbem_atf_money_movement" },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "", resource: "r4", metric_name: "m4", severity: "3", message_key: "ZZ_USBEM_ATF_CI_TYPE", ci_type: "Server", ci_identifier: { name: "ZZ USBEM ATF Money Movement" } },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "ci-miss", resource: "r5", metric_name: "m5", severity: "3", message_key: "ZZ_USBEM_ATF_CI_NOMATCH", cmdb_ci: "ZZ USBEM ATF Not Real" }',
            '        ]',
            '    };',
            '    h.assertConnectorSuccess(h.postPayload(payload), 5);'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var ciId = h.ensureCi("cmdb_ci_server", "ZZ USBEM ATF Money Movement");',
            '    var evSys = h.getEventByMessageKey("ZZ_USBEM_ATF_CI_SYSID");',
            '    var evExact = h.getEventByMessageKey("ZZ_USBEM_ATF_CI_EXACT");',
            '    var evCanon = h.getEventByMessageKey("ZZ_USBEM_ATF_CI_CANON");',
            '    var evType = h.getEventByMessageKey("ZZ_USBEM_ATF_CI_TYPE");',
            '    var evMiss = h.getEventByMessageKey("ZZ_USBEM_ATF_CI_NOMATCH");',
            '    h.assertEquals(ciId, evSys.getValue("cmdb_ci"), "cmdb_ci sys_id input failed");',
            '    h.assertEquals(ciId, evExact.getValue("cmdb_ci"), "cmdb_ci exact lookup failed");',
            '    h.assertEquals(ciId, evCanon.getValue("cmdb_ci"), "cmdb_ci canonical lookup failed");',
            '    h.assertEquals(ciId, evType.getValue("cmdb_ci"), "ci_type human label lookup failed");',
            '    h.assertBlank(evMiss.getValue("cmdb_ci"), "no-match CI should stay blank");'
        ]));

        testSysId = createTest(
            '05 CI Duplicate Preference',
            'Covers duplicate-name class preference for business_app over service and server over vmware_instance.',
            suiteSysId,
            500
        );
        keys = ['ZZ_USBEM_ATF_DUP_SERVER_EXACT', 'ZZ_USBEM_ATF_DUP_SERVER_CANON', 'ZZ_USBEM_ATF_DUP_BIZ_EXACT', 'ZZ_USBEM_ATF_DUP_BIZ_CANON'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    h.ensureCi("cmdb_ci_server", "ZZ USBEM ATF Duplicate Compute");',
            '    h.ensureCi("cmdb_ci_vmware_instance", "ZZ USBEM ATF Duplicate Compute");',
            '    h.ensureBusinessApp("ZZ USBEM ATF Duplicate Business", "ZZ-USBEM-ATF-DUP");',
            '    h.ensureService("ZZ USBEM ATF Duplicate Business");',
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        records: [',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "dup-server-exact", resource: "r1", metric_name: "m1", severity: "3", message_key: "ZZ_USBEM_ATF_DUP_SERVER_EXACT", cmdb_ci: "ZZ USBEM ATF Duplicate Compute" },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "dup-server-canon", resource: "r2", metric_name: "m2", severity: "3", message_key: "ZZ_USBEM_ATF_DUP_SERVER_CANON", cmdb_ci: "zz_usbem_atf_duplicate_compute" },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "dup-biz-exact", resource: "r3", metric_name: "m3", severity: "3", message_key: "ZZ_USBEM_ATF_DUP_BIZ_EXACT", cmdb_ci: "ZZ USBEM ATF Duplicate Business" },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "dup-biz-canon", resource: "r4", metric_name: "m4", severity: "3", message_key: "ZZ_USBEM_ATF_DUP_BIZ_CANON", cmdb_ci: "zz_usbem_atf_duplicate_business" }',
            '        ]',
            '    };',
            '    h.assertConnectorSuccess(h.postPayload(payload), 4);'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var serverId = h.ensureCi("cmdb_ci_server", "ZZ USBEM ATF Duplicate Compute");',
            '    var appId = h.ensureBusinessApp("ZZ USBEM ATF Duplicate Business", "ZZ-USBEM-ATF-DUP");',
            '    h.assertEquals(serverId, h.getEventByMessageKey("ZZ_USBEM_ATF_DUP_SERVER_EXACT").getValue("cmdb_ci"), "server should beat vmware duplicate");',
            '    h.assertEquals(serverId, h.getEventByMessageKey("ZZ_USBEM_ATF_DUP_SERVER_CANON").getValue("cmdb_ci"), "server should beat vmware duplicate for canonical input");',
            '    h.assertEquals(appId, h.getEventByMessageKey("ZZ_USBEM_ATF_DUP_BIZ_EXACT").getValue("cmdb_ci"), "business app should beat service duplicate");',
            '    h.assertEquals(appId, h.getEventByMessageKey("ZZ_USBEM_ATF_DUP_BIZ_CANON").getValue("cmdb_ci"), "business app should beat service duplicate for canonical input");'
        ]));

        testSysId = createTest(
            '06 Business App Service Offering And Service Association Helpers',
            'Covers usbem_car_id, usbem_service, usbem_offering, and service inference through svc_ci_assoc.',
            suiteSysId,
            600
        );
        keys = ['ZZ_USBEM_ATF_HELPERS_DIRECT', 'ZZ_USBEM_ATF_HELPERS_ASSOC'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    var ciId = h.ensureCi("cmdb_ci_server", "ZZ USBEM ATF Helper CI");',
            '    var serviceId = h.ensureService("ZZ USBEM ATF Helper Service");',
            '    h.ensureBusinessApp("ZZ USBEM ATF Helper App", "ZZ-USBEM-ATF-CAR");',
            '    h.ensureOffering("ZZ USBEM ATF Helper Offering", serviceId);',
            '    h.ensureSvcAssoc(ciId, serviceId);',
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        records: [',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "helper-direct", resource: "r1", metric_name: "m1", severity: "3", message_key: "ZZ_USBEM_ATF_HELPERS_DIRECT", cmdb_ci: "ZZ USBEM ATF Helper CI", usbem_car_id: "ZZ-USBEM-ATF-CAR", usbem_service: "ZZ USBEM ATF Helper Service", usbem_offering: "ZZ USBEM ATF Helper Offering" },',
            '            { source: "USBEM_ATF", event_class: "USBEM ATF", node: "helper-assoc", resource: "r2", metric_name: "m2", severity: "3", message_key: "ZZ_USBEM_ATF_HELPERS_ASSOC", cmdb_ci: "ZZ USBEM ATF Helper CI", usbem_offering: "ZZ USBEM ATF Helper Offering" }',
            '        ]',
            '    };',
            '    h.assertConnectorSuccess(h.postPayload(payload), 2);'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var appId = h.ensureBusinessApp("ZZ USBEM ATF Helper App", "ZZ-USBEM-ATF-CAR");',
            '    var serviceId = h.ensureService("ZZ USBEM ATF Helper Service");',
            '    var offeringId = h.ensureOffering("ZZ USBEM ATF Helper Offering", serviceId);',
            '    var aiDirect = h.parseAdditionalInfo(h.getEventByMessageKey("ZZ_USBEM_ATF_HELPERS_DIRECT"));',
            '    var aiAssoc = h.parseAdditionalInfo(h.getEventByMessageKey("ZZ_USBEM_ATF_HELPERS_ASSOC"));',
            '    h.assertEquals(appId, aiDirect.cmdb_ci_business_app, "usbem_car_id lookup failed");',
            '    h.assertEquals(serviceId, aiDirect.cmdb_ci_service, "usbem_service lookup failed");',
            '    h.assertEquals(offeringId, aiDirect.cmdb_ci_service_offering, "usbem_offering lookup failed");',
            '    h.assertEquals(serviceId, aiAssoc.cmdb_ci_service, "svc_ci_assoc inference failed");',
            '    h.assertEquals(offeringId, aiAssoc.cmdb_ci_service_offering, "offering lookup with inferred service failed");'
        ]));

        testSysId = createTest(
            '07 Debug Companion Event And Lookup Diagnostics',
            'Covers usbem_debug response/debug event creation and verbose lookup diagnostics in additional_info.',
            suiteSysId,
            700
        );
        keys = ['ZZ_USBEM_ATF_DEBUG'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    h.ensureGroup("ZZ USBEM ATF Debug Group");',
            '    h.ensureCi("cmdb_ci_server", "ZZ USBEM ATF Debug CI");',
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        source: "USBEM_ATF",',
            '        event_class: "USBEM ATF",',
            '        node: "debug-node",',
            '        resource: "debug-resource",',
            '        metric_name: "debug-metric",',
            '        severity: "3",',
            '        message_key: "ZZ_USBEM_ATF_DEBUG",',
            '        assignment_group: "zz_usbem_atf_debug_group",',
            '        cmdb_ci: "zz_usbem_atf_debug_ci",',
            '        usbem_debug: true',
            '    };',
            '    var response = h.postPayload(payload);',
            '    var inner = h.assertConnectorSuccess(response, 1);',
            '    h.assertTrue(h.hasValue(inner.debug_raw_event_sys_id), "debug_raw_event_sys_id missing from response");'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var ev = h.getEventByMessageKey("ZZ_USBEM_ATF_DEBUG");',
            '    var dbg = h.getDebugEventByParentKey("ZZ_USBEM_ATF_DEBUG");',
            '    var trace;',
            '    var corr;',
            '    var lookups;',
            '    h.assertTrue(!!ev, "Main debug event not found");',
            '    h.assertTrue(!!dbg, "Companion debug event not found");',
            '    h.assertEquals("USBEM Debug", dbg.getValue("source"), "Unexpected debug event source");',
            '    trace = h.getAttachmentJson("em_event", dbg.getUniqueValue(), "04_lookup_trace.json") || [];',
            '    corr = h.getAttachmentJson("em_event", dbg.getUniqueValue(), "06_correlation_hints.json") || [];',
            '    lookups = trace.length ? (trace[0].lookups || {}) : {};',
            '    h.assertTrue(!!h.getAttachmentByName("em_event", dbg.getUniqueValue(), "04_lookup_trace.json"), "lookup trace attachment missing");',
            '    h.assertTrue(!!lookups.assignment_group, "assignment group lookup trace missing");',
            '    h.assertTrue(!!lookups.cmdb_ci, "cmdb_ci lookup trace missing");',
            '    h.assertEquals("matched", lookups.assignment_group.status, "assignment group debug status mismatch");',
            '    h.assertEquals("matched", lookups.cmdb_ci.status, "cmdb_ci debug status mismatch");',
            '    h.assertTrue(corr.length > 0, "correlation hints attachment missing");',
            '    h.assertTrue(h.hasValue(corr[0].assignment_group), "assignment group correlation hint missing");',
            '    h.assertTrue(h.hasValue(corr[0].cmdb_ci), "cmdb_ci correlation hint missing");'
        ]));

        testSysId = createTest(
            '08 Wait For Alert',
            'Covers usbem_wait_for_alert synchronous alert wait behavior and alert identifiers.',
            suiteSysId,
            800
        );
        keys = ['ZZ_USBEM_ATF_WAIT_ALERT'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        source: "USBEM_ATF",',
            '        event_class: "USBEM ATF",',
            '        node: "wait-alert-node",',
            '        resource: "wait-alert-resource",',
            '        metric_name: "wait-alert-metric",',
            '        severity: "2",',
            '        message_key: "ZZ_USBEM_ATF_WAIT_ALERT",',
            '        description: "Wait for alert test",',
            '        usbem_wait_for_alert: true,',
            '        usbem_wait_seconds: 20',
            '    };',
            '    var response = h.postPayload(payload);',
            '    var inner = h.assertConnectorSuccess(response, 1);',
            '    h.assertTrue(h.hasValue(inner.alert_sys_id), "alert_sys_id missing from wait-for-alert response");',
            '    h.assertTrue(h.hasValue(inner.alert_number), "alert_number missing from wait-for-alert response");'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var alertGr = h.getAlertByMessageKey("ZZ_USBEM_ATF_WAIT_ALERT");',
            '    var ev = h.getEventByMessageKey("ZZ_USBEM_ATF_WAIT_ALERT");',
            '    h.assertTrue(!!ev, "Wait-for-alert event missing");',
            '    h.assertTrue(!!alertGr, "Alert was not created for wait-for-alert test");'
        ]));

        testSysId = createTest(
            '09 DTI No Wait Single Incident And Link',
            'Covers direct_to_incident without dti_wait_for_incident and validates one linked incident with no late duplicate.',
            suiteSysId,
            900
        );
        keys = ['ZZ_USBEM_ATF_DTI_NOWAIT'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        source: "USBEM_ATF",',
            '        event_class: "USBEM ATF",',
            '        node: "dti-nowait-node",',
            '        resource: "dti-nowait-resource",',
            '        metric_name: "dti-nowait-metric",',
            '        severity: "3",',
            '        message_key: "ZZ_USBEM_ATF_DTI_NOWAIT",',
            '        description: "DTI no wait test",',
            '        direct_to_incident: true',
            '    };',
            '    var response = h.postPayload(payload);',
            '    var inner = h.assertConnectorSuccess(response, 1);',
            '    h.assertTrue(inner.dti_mode === "inline_after_alert" || inner.dti_mode === "deferred_after_response", "Unexpected DTI no-wait mode: " + inner.dti_mode);'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var state = h.waitForSingleLinkedIncident("ZZ_USBEM_ATF_DTI_NOWAIT", 30000);',
            '    var ev = h.getEventByMessageKey("ZZ_USBEM_ATF_DTI_NOWAIT");',
            '    var ai = h.parseAdditionalInfo(ev);',
            '    h.assertTrue(!!ev, "DTI no-wait event missing");',
            '    h.assertTrue(!!state.alert, "DTI no-wait alert missing");',
            '    h.assertTrue(!!state.incident, "DTI no-wait incident missing");',
            '    h.assertEquals("1", String(state.incidentCount), "DTI no-wait created duplicate incidents");',
            '    h.assertEquals(state.incident.getUniqueValue(), state.linkedIncidentSysId, "DTI no-wait alert not linked to the only incident");',
            '    h.assertEquals("true", ai.direct_to_incident, "direct_to_incident breadcrumb missing");',
            '    h.assertEquals("DTI no wait test", ai.dti_short_description, "dti_short_description was not auto-filled");',
            '    h.assertEquals("3", ai.dti_impact, "dti_impact did not come from severity map");',
            '    h.assertEquals("3", ai.dti_urgency, "dti_urgency did not come from severity map");'
        ]));

        testSysId = createTest(
            '10 DTI Wait And Incident Creation',
            'Covers synchronous direct_to_incident with incident creation plus custom impact/urgency propagation.',
            suiteSysId,
            1000
        );
        keys = ['ZZ_USBEM_ATF_DTI_WAIT'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        source: "USBEM_ATF",',
            '        event_class: "USBEM ATF",',
            '        node: "dti-wait-node",',
            '        resource: "dti-wait-resource",',
            '        metric_name: "dti-wait-metric",',
            '        severity: "3",',
            '        message_key: "ZZ_USBEM_ATF_DTI_WAIT",',
            '        description: "DTI wait test",',
            '        direct_to_incident: true,',
            '        dti_wait_for_incident: true,',
            '        dti_impact: "1",',
            '        dti_urgency: "2",',
            '        dti_short_description: "USBEM ATF DTI wait short description",',
            '        usbem_wait_seconds: 20',
            '    };',
            '    var response = h.postPayload(payload);',
            '    var inner = h.assertConnectorSuccess(response, 1);',
            '    h.assertEquals("wait_for_incident", inner.dti_mode, "Expected wait_for_incident mode");',
            '    h.assertTrue(h.hasValue(inner.incident_sys_id), "incident_sys_id missing from DTI wait response");'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var inc = h.getIncidentByCorrelationId("ZZ_USBEM_ATF_DTI_WAIT");',
            '    var ev = h.getEventByMessageKey("ZZ_USBEM_ATF_DTI_WAIT");',
            '    var ai = h.parseAdditionalInfo(ev);',
            '    h.assertTrue(!!inc, "DTI wait did not create an incident");',
            '    h.assertEquals("USBEM ATF DTI wait short description", inc.getValue("short_description"), "short_description mismatch");',
            '    h.assertEquals("1", inc.getValue("impact"), "impact mismatch");',
            '    h.assertEquals("2", inc.getValue("urgency"), "urgency mismatch");',
            '    h.assertEquals("1", ai.dti_impact, "event additional_info dti_impact mismatch");',
            '    h.assertEquals("2", ai.dti_urgency, "event additional_info dti_urgency mismatch");'
        ]));

        testSysId = createTest(
            '11 DTI Severity Suppression',
            'Covers severity-map incident suppression for severity 5 while waiting for incident creation.',
            suiteSysId,
            1100
        );
        keys = ['ZZ_USBEM_ATF_DTI_SUPPRESS'];
        addServerScriptStep(testSysId, 100, setupScript(authProfileSysId, [
            '    h.cleanupByMessageKeys(' + JSON.stringify(keys) + ');'
        ]));
        addServerScriptStep(testSysId, 200, setupScript(authProfileSysId, [
            '    var payload = {',
            '        source: "USBEM_ATF",',
            '        event_class: "USBEM ATF",',
            '        node: "dti-suppress-node",',
            '        resource: "dti-suppress-resource",',
            '        metric_name: "dti-suppress-metric",',
            '        severity: "5",',
            '        message_key: "ZZ_USBEM_ATF_DTI_SUPPRESS",',
            '        description: "DTI suppression test",',
            '        direct_to_incident: true,',
            '        dti_wait_for_incident: true,',
            '        usbem_wait_seconds: 20',
            '    };',
            '    var response = h.postPayload(payload);',
            '    var inner = h.assertConnectorSuccess(response, 1);',
            '    h.assertEquals("suppressed_by_severity_map", inner.dti_incident_status, "Expected suppressed_by_severity_map");'
        ]));
        addServerScriptStep(testSysId, 300, setupScript(authProfileSysId, [
            '    var inc = h.getIncidentByCorrelationId("ZZ_USBEM_ATF_DTI_SUPPRESS");',
            '    var ev = h.getEventByMessageKey("ZZ_USBEM_ATF_DTI_SUPPRESS");',
            '    var ai = h.parseAdditionalInfo(ev);',
            '    h.assertTrue(!inc, "Suppressed DTI test should not create an incident");',
            '    h.assertEquals("4", ai.dti_impact, "suppressed severity should still map dti_impact");',
            '    h.assertEquals("4", ai.dti_urgency, "suppressed severity should still map dti_urgency");'
        ]));
    }

    try {
        var authProfileSysId;
        var parentSuiteSysId;
        var suiteSysId;

        ensureRunnerEnabled();
        authProfileSysId = ensureAuthProfile();
        ensureHelperInclude();
        deleteExistingAssets();
        parentSuiteSysId = ensureSuite(CONFIG.suite_parent_name, CONFIG.suite_parent_description, '');
        suiteSysId = ensureSuite(CONFIG.suite_name, CONFIG.suite_description, parentSuiteSysId);
        createTests(authProfileSysId, suiteSysId);

        log('Installed parent suite ' + CONFIG.suite_parent_name + ' and child suite ' + CONFIG.suite_name + ' with auth profile ' + authProfileSysId);
        log('ATF install complete');
    } catch (e) {
        gs.error('USBEM ATF installer failed: ' + e);
        throw e;
    }
})();
