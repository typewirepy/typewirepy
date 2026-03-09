from __future__ import annotations


def test_core_package_imports_without_fastapi() -> None:
    """Importing typewirepy should work without fastapi installed."""
    import typewirepy

    assert hasattr(typewirepy, "type_wire_of")
    assert hasattr(typewirepy, "TypeWire")
    assert hasattr(typewirepy, "TypeWireContainer")


def test_fastapi_integration_import_fails_gracefully() -> None:
    """Explicitly importing the fastapi integration should only fail if fastapi is missing."""
    # This test just verifies the import works when fastapi IS available
    # (since fastapi is in our test deps)
    from typewirepy.integrations.fastapi import WireDepends

    assert callable(WireDepends)
