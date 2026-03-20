"""Tests for legion.plumbing.exceptions."""

from legion.plumbing.exceptions import LegionError


class TestLegionError:
    def test_basic_creation(self):
        err = LegionError("something broke")
        assert str(err) == "something broke"
        assert err.message == "something broke"
        assert err.retryable is False

    def test_retryable_flag(self):
        err = LegionError("timeout", retryable=True)
        assert err.retryable is True

    def test_to_dict(self):
        err = LegionError("fail", retryable=True)
        d = err.to_dict()
        assert d["type"] == "LegionError"
        assert d["message"] == "fail"
        assert d["retryable"] is True

    def test_repr(self):
        err = LegionError("oops")
        assert "LegionError" in repr(err)
        assert "oops" in repr(err)

    def test_is_exception(self):
        err = LegionError("test")
        assert isinstance(err, Exception)

    def test_subclass_inherits_serialization(self):
        class CustomError(LegionError):
            _serializable_fields = ("message", "retryable", "code")

            def __init__(self, message: str, code: int):
                super().__init__(message)
                self.code = code

        err = CustomError("not found", code=404)
        d = err.to_dict()
        assert d["type"] == "CustomError"
        assert d["code"] == 404

    def test_chaining(self):
        original = ValueError("original")
        try:
            raise LegionError("wrapped") from original
        except LegionError as err:
            assert err.__cause__ is original
