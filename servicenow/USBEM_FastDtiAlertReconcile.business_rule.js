(function executeRule(current, previous /*null when async*/) {
    var core;
    var dti;
    var outcome;

    try {
        core = new x_usbna_usb_event.USBEM_Core();
        dti = new x_usbna_usb_event.USBEM_DTI(core);
        outcome = dti.reconcileAlertIncident(current, null);
        if (outcome && (outcome.status === 'linked' || outcome.status === 'relinked_to_fast_incident')) {
            gs.info('USBEM fast DTI alert reconcile outcome: ' + core.safeJSONStringify(outcome));
        }
    } catch (e) {
        gs.error('USBEM fast DTI alert reconcile failed: ' + e);
    }
})(current, previous);
