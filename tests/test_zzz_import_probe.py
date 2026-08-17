def test_api_importable():
    import api.auth, api.main, api.db  # noqa
    from api.db import Base  # noqa
    assert True
