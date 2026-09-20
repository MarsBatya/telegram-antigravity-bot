from app.runner import agent_runner, stream_runner


def test_agent_runner_exports_all() -> None:
    for name in agent_runner.__all__:
        assert hasattr(agent_runner, name), f"Missing export: {name}"


def test_agent_runner_aliases() -> None:
    assert agent_runner.resume_session == stream_runner.resume_stream
    assert agent_runner.run_antigravity_agent == stream_runner.run_antigravity_stream
    assert agent_runner.run_smash_mode == stream_runner.run_smash_stream


def test_agent_runner_shared_storage() -> None:
    assert agent_runner.SessionStorage is stream_runner.SessionStorage
