# OWNER: Member 3
# The ONLY module other code imports to get providers. Singletons, built from env
# (MOCK_BASE_URL, NADRA_MOCK_KEY, RAAST_MOCK_KEY, SMS_MOCK_KEY) on first use.
# Swapping mocks for real providers later means changing only this file.
from typing import Optional

from .base import IdentityProvider, NotificationProvider, PaymentProvider
from .identity import MockNadraIdentityProvider
from .notification import MockSmsNotificationProvider
from .payment import MockRaastPaymentProvider

_identity: Optional[IdentityProvider] = None
_payment: Optional[PaymentProvider] = None
_notification: Optional[NotificationProvider] = None


def get_identity_provider() -> IdentityProvider:
    global _identity
    if _identity is None:
        _identity = MockNadraIdentityProvider.from_env()
    return _identity


def get_payment_provider() -> PaymentProvider:
    global _payment
    if _payment is None:
        _payment = MockRaastPaymentProvider.from_env()
    return _payment


def get_notification_provider() -> NotificationProvider:
    global _notification
    if _notification is None:
        _notification = MockSmsNotificationProvider.from_env()
    return _notification


def reset_providers() -> None:
    """Forget the singletons (tests, or after env changes)."""
    global _identity, _payment, _notification
    _identity = _payment = _notification = None
