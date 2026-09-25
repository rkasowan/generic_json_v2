/*
 * Business Rule: USBEM Fast DTI Alert Reconcile
 *
 * Required record configuration:
 *   Table      em_alert
 *   When       after          <-- NOT async. Event Management best practice: "Do not write
 *                                 async business rules for alert tables."
 *   Insert     true
 *   Update     true
 *   Order      150
 *   Condition  !current.message_key.nil() && current.incident.nil() && current.state != 'Closed'
 *
 * The condition keeps the rule off the vast majority of alert writes: it only runs for an alert
 * that has a message key, has no incident yet, and is not Closed. Everything else is filtered
 * before the script executes.
 *
 * Keep this fast. The same guidance says a rule here must not take "more than a few
 * milliseconds", and that an inefficient one "can cause incident creation for an alert to fail
 * and the alert impact calculation to fail". In the common case the script costs one query: if
 * no open USBEM DTI incident exists for the key, reconcileAlertIncident returns
 * no_usbemdti_incident and writes nothing.
 *
 * If incident.correlation_id is not indexed on your instance, add an index before enabling this
 * at volume; the lookup queries incident by correlation_id.
 */
(function executeRule(current, previous /*null when async*/) {
    // Version stamp, logged with every outcome. The Script Includes report their own versions in
    // the endpoint response; this rule has no response, so the log line is where its version
    // shows up. Keep it in step with the release the rest of the project is on.
    var BR_VERSION = '2026.09.25.3';
    var core;
    var dti;
    var outcome;

    try {
        core = new x_usbna_usb_event.USBEM_Core();
        dti = new x_usbna_usb_event.USBEM_DTI(core);
        outcome = dti.reconcileAlertIncident(current, null);
        if (outcome && (outcome.status === 'linked' || outcome.status === 'relinked_to_fast_incident')) {
            outcome.business_rule_version = BR_VERSION;
            gs.info('USBEM fast DTI alert reconcile [v' + BR_VERSION + '] outcome: ' + core.safeJSONStringify(outcome));
        }
    } catch (e) {
        gs.error('USBEM fast DTI alert reconcile [v' + BR_VERSION + '] failed: ' + e);
    }
})(current, previous);
