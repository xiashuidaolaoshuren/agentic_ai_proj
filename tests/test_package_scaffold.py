"""Scaffold checks: package must be importable (Task 1)."""


def test_ai_news_agent_package_importable() -> None:
    import ai_news_agent

    assert hasattr(ai_news_agent, "__version__")
    assert isinstance(ai_news_agent.__version__, str)
    assert ai_news_agent.__version__
