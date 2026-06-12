# Dummy ai_guard module
def chunk_delta(*args, **kwargs):
    return ""

def normalize_chunk(*args, **kwargs):
    return ""

def compute_payload_hash(*args, **kwargs):
    return ""

def is_duplicate_payload(*args, **kwargs):
    return False

def make_idempotency_key(*args, **kwargs):
    return ""

def idempotency_get(*args, **kwargs):
    return None

def idempotency_set(*args, **kwargs):
    pass

def enforce_token_limits(*args, **kwargs):
    pass

def enforce_budgets(*args, **kwargs):
    pass

def acquire_source_lease(*args, **kwargs):
    pass

def release_source_lease(*args, **kwargs):
    pass

def check_hard_refusals(*args, **kwargs):
    pass

def retry_execute(*args, **kwargs):
    pass

def audit_log(*args, **kwargs):
    pass

def budget_status(*args, **kwargs):
    return {}

def estimate_tokens(*args, **kwargs):
    return 0

class GuardReject(Exception):
    pass
