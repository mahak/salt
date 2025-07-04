"""
Integration tests for the rabbitmq_user states
"""

import logging

import pytest

import salt.modules.rabbitmq as rabbitmq
import salt.states.rabbitmq_upstream as rabbitmq_upstream
from salt.utils.versions import Version

log = logging.getLogger(__name__)

docker = pytest.importorskip("docker")

pytestmark = [
    pytest.mark.slow_test,
    pytest.mark.skip_if_binaries_missing(
        "docker", "dockerd", reason="Docker not installed"
    ),
    pytest.mark.skipif(
        Version(docker.__version__) < Version("4.0.0"),
        reason="Test does not work in this version of docker-py",
    ),
]


@pytest.fixture
def configure_loader_modules(docker_cmd_run_all_wrapper):
    return {
        rabbitmq_upstream: {
            "__salt__": {
                "rabbitmq.upstream_exists": rabbitmq.upstream_exists,
                "rabbitmq.list_user_permissions": rabbitmq.list_user_permissions,
            },
            "__opts__": {"test": False},
            "_utils__": {},
        },
        rabbitmq: {
            "__salt__": {"cmd.run_all": docker_cmd_run_all_wrapper},
            "__opts__": {},
            "_utils__": {},
        },
    }


def test_absent(rabbitmq_container):
    """
    Test rabbitmq_upstream.absent
    """

    # Delete the user
    ret = rabbitmq_upstream.absent("upstream")
    expected = {
        "name": "upstream",
        "result": True,
        "comment": 'The upstream "upstream" is already absent.',
        "changes": {},
    }
    assert ret == expected
