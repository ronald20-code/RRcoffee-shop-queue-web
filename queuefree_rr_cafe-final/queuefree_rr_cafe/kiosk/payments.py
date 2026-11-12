"""
Digital payment layer for QueueFree RR Cafe.

This ships with a *sandbox* gateway that simulates GCash, Maya and card
payments so the whole kiosk flow works offline in development.  No real money
moves and card details are validated but never stored.

To go live, implement ``charge()`` for a real provider (PayMongo, Xendit,
Maya Checkout, ...) behind the same ``PaymentResult`` return type and swap it
in ``get_gateway()``.  Everything else in the app stays unchanged.
"""

import secrets
from dataclasses import dataclass


@dataclass
class PaymentResult:
    success: bool
    reference: str = ""
    message: str = ""


def luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 12:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


class SandboxGateway:
    """Simulated provider. Replace with a real one for production."""

    def charge(self, method, amount, payload) -> PaymentResult:
        if method in ("gcash", "maya"):
            mobile = "".join(c for c in payload.get("mobile", "") if c.isdigit())
            if len(mobile) != 11 or not mobile.startswith("09"):
                return PaymentResult(False, message="Enter an 11-digit mobile number starting with 09.")
            if len(payload.get("pin", "")) != 4 or not payload.get("pin", "").isdigit():
                return PaymentResult(False, message="Enter your 4-digit wallet PIN.")
            prefix = "GC" if method == "gcash" else "MY"
            return PaymentResult(True, f"{prefix}-{secrets.token_hex(4).upper()}")

        if method == "card":
            number = payload.get("number", "")
            if not luhn_ok(number):
                return PaymentResult(False, message="Card number is not valid. (Sandbox test card: 4242 4242 4242 4242)")
            expiry = payload.get("expiry", "")
            if len(expiry) != 5 or expiry[2] != "/":
                return PaymentResult(False, message="Expiry must look like MM/YY.")
            if not (payload.get("cvc", "").isdigit() and len(payload.get("cvc", "")) in (3, 4)):
                return PaymentResult(False, message="Enter the 3 or 4 digit security code.")
            return PaymentResult(True, f"CD-{secrets.token_hex(4).upper()}")

        return PaymentResult(False, message="Unsupported payment method.")


def get_gateway():
    return SandboxGateway()
