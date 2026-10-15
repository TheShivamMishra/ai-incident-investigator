"""Capture real loopback HTTP requests from a deliberately tiny service lab.

These are custom JSON telemetry records, not OpenTelemetry spans. The lab is
intentionally isolated: ephemeral ports, fake payments, and no external traffic.
"""
import json
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def now():
    return datetime.now(timezone.utc).isoformat()


def capture(scenario="payment-latency", requests=6):
    if scenario not in ("payment-latency", "healthy", "payment-errors"):
        raise ValueError("Unknown lab scenario")
    if not 1 <= requests <= 100:
        raise ValueError("requests must be between 1 and 100")
    records = []
    lock = threading.Lock()
    timeout = 0.15

    def record(kind, service, **fields):
        with lock:
            records.append(dict(id="e%04d" % (len(records) + 1),
                                timestamp=now(), kind=kind, service=service, **fields))

    class QuietHandler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when checkout has already timed out.

    class Payment(QuietHandler):
        def do_GET(self):
            start = time.perf_counter()
            trace = self.headers["X-Trace-ID"]
            time.sleep(0.4 if scenario == "payment-latency" else 0.01)
            status = 503 if scenario == "payment-errors" else 200
            record("span", "payment", trace_id=trace, operation="charge",
                   duration_ms=round((time.perf_counter() - start) * 1000, 2), status=status)
            if status != 200:
                record("log", "payment", trace_id=trace, level="ERROR", message="Provider unavailable")
            self.reply(status, {"payment": "accepted" if status == 200 else "unavailable"})

    payment = ThreadingHTTPServer(("127.0.0.1", 0), Payment)
    # Wait for in-flight telemetry before capture returns.
    payment.daemon_threads = False
    payment_url = "http://127.0.0.1:%s/charge" % payment.server_port

    class Checkout(QuietHandler):
        def do_GET(self):
            start = time.perf_counter()
            trace = self.headers.get("X-Trace-ID", uuid.uuid4().hex)
            status, failure = 200, None
            try:
                with urlopen(Request(payment_url, headers={"X-Trace-ID": trace}), timeout=timeout) as response:
                    response.read()
            except HTTPError as error:
                status, failure = 502, "upstream_http_%s" % error.code
                error.close()
            except (socket.timeout, TimeoutError):
                status, failure = 504, "upstream_timeout"
            except URLError:
                status, failure = 502, "upstream_connection_error"
            if failure:
                record("log", "checkout", trace_id=trace, level="ERROR",
                       message=failure, dependency="payment", timeout_ms=timeout * 1000)
            record("span", "checkout", trace_id=trace, operation="checkout",
                   duration_ms=round((time.perf_counter() - start) * 1000, 2), status=status)
            self.reply(status, {"status": "failed" if failure else "complete", "trace_id": trace})

    checkout = ThreadingHTTPServer(("127.0.0.1", 0), Checkout)
    checkout.daemon_threads = False
    servers = [payment, checkout]
    threads = [threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}) for s in servers]
    record("config", "checkout", dependency="payment", timeout_ms=timeout * 1000)
    for thread in threads:
        thread.start()
    try:
        for _ in range(requests):
            try:
                with urlopen("http://127.0.0.1:%s/checkout" % checkout.server_port, timeout=5) as response:
                    response.read()
            except HTTPError as error:
                error.read()
                error.close()
    finally:
        for server in reversed(servers):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join()
    return {
        "schema_version": 1,
        "captured_at": now(),
        "source": "local HTTP lab; simulated services and injected faults",
        # Deliberately exclude the scenario label / ground truth from agent input.
        "records": records,
        "runbooks": [{"id": "rb-payment", "title": "Checkout dependency failures",
                      "text": "Correlate checkout and payment spans by trace_id. For timeouts, compare "
                              "payment duration with checkout's configured timeout. A payment may finish "
                              "after checkout times out; verify idempotency before retrying. Distinguish "
                              "slow success from explicit upstream HTTP failures. Check provider health "
                              "and recent changes before recommending a rollback."}],
    }
