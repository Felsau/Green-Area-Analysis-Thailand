"""Injected request-plan adapter for existing durable accounting; no network."""
from gis_worker.gee_execution_safety import AccountedTransport, require_real_transport
from gis_worker.gee_runtime_identity import RuntimeBinding

EGRESS_POLICY = 'gee-live-deny-external-v1'
APPROVED_GOOGLE_ENDPOINTS = ()


def require_live_egress(*args, **kwargs):
    # No URL, redirect, DNS result, environment flag or caller boolean opens it.
    raise ValueError('GEE_LIVE_EGRESS_BLOCKED')


class _AuthorizedInjectedPort:
    OFFLINE_INJECTED = True

    def __init__(self, provider, lease, binding, port):
        self.provider, self.lease, self.binding, self.port = provider, lease, binding, port

    def evaluate(self, *, timeout_seconds):
        self.provider.authorize(self.lease, self.binding)
        if getattr(self.port, 'OFFLINE_INJECTED', None) is not True:
            require_real_transport()
        output = self.port.evaluate(timeout_seconds=timeout_seconds)
        self.provider.authorize(self.lease, self.binding)
        return output


class PreparedInjectedTransport:
    """Trusted server-side test plan only; never a plan from a job payload.

    Each entry is a full injected observation, not an actual SDK HTTP response.
    A failed/uncertain entry aborts the plan. It cannot yield a candidate merely
    because a later request succeeded; SQL045 preserves that invariant too.
    """
    def __init__(self, call, job, trusted_subject, provider, lease, *, clock=None):
        self.binding = RuntimeBinding.from_claim(job, trusted_subject)
        provider.authorize(lease, self.binding)
        self.provider, self.lease = provider, lease
        self.accounting = AccountedTransport(call, job, **({} if clock is None else {'clock': clock}))

    def run(self, plan):
        if not isinstance(plan, (list, tuple)) or not 0 < len(plan) <= 32:
            raise ValueError('GEE_INJECTED_PLAN_REJECTED')
        receipts, output = [], None
        for kind, port in plan:
            # Check before reserve AND before the injected attempted evaluation.
            self.provider.authorize(self.lease, self.binding)
            wrapped = _AuthorizedInjectedPort(self.provider, self.lease, self.binding, port)
            output, receipt = self.accounting.execute(wrapped, kind=kind)
            receipts.append(receipt)
        return self.accounting.report(output, receipts)
