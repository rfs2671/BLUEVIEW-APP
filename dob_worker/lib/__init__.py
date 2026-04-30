"""dob_worker shared infrastructure modules.

Public modules:
    handler_types — HandlerContext + HandlerResult contract
    queue_client  — Redis BRPOP poll + idempotent job pickup
    crypto        — RSA-OAEP + AES-GCM hybrid decrypt for credentials
    browser_context — per-GC BrowserContext dispatch via storage_state
    heartbeat     — backend POST every 60s
    circuit_breaker — per-job-type 30-min pause when challenge_rate > 10%
"""
