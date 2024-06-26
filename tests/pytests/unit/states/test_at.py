"""
    :codeauthor: Jayesh Kariya <jayeshk@saltstack.com>
"""

import pytest

import salt.states.at as at
from tests.support.mock import MagicMock, patch


@pytest.fixture
def configure_loader_modules():
    return {at: {}}


def test_present():
    """
    Test to add a job to queue.
    """
    name = "jboss"
    timespec = "9:09 11/04/15"
    tag = "love"
    user = "jam"

    # mock for at.at module call
    mock_atat = {
        "jobs": [
            {
                "date": "2015-11-04",
                "job": "1476031633.a",
                "queue": "a",
                "tag": tag,
                "time": "09:09:00",
                "user": user,
            },
        ],
    }

    # normale return
    ret = {
        "name": name,
        "result": True,
        "changes": {
            "date": "2015-11-04",
            "job": "1476031633.a",
            "queue": "a",
            "tag": "love",
            "time": "09:09:00",
            "user": "jam",
        },
        "comment": "job {name} added and will run on {timespec}".format(
            name=name, timespec=timespec
        ),
    }

    # unknown user return
    ret_user = {}
    ret_user.update(ret)
    ret_user.update(
        {
            "result": False,
            "changes": {},
            "comment": f"user {user} does not exists",
        }
    )

    # add a job
    mock = MagicMock(return_value=mock_atat)
    with patch.dict(at.__opts__, {"test": False}):
        with patch.dict(at.__salt__, {"at.at": mock}):
            assert at.present(name, timespec, tag) == ret

    # add a job with a non-existing user
    mock = MagicMock(return_value=False)
    with patch.dict(at.__opts__, {"test": False}):
        with patch.dict(at.__salt__, {"user.info": mock}):
            assert at.present(name, timespec, tag, user) == ret_user

    # add a job with test=True
    with patch.dict(at.__opts__, {"test": True}):
        ret_test = {}
        ret_test.update(ret)
        ret_test.update({"result": None, "changes": {}})
        assert at.present(name, timespec, tag, user) == ret_test


def test_absent():
    """
    Test to remove a job from queue
    """
    name = "jboss"
    tag = "rose"
    user = "jam"

    # mock for at.atrm module call
    mock_atatrm = {
        "jobs": {"removed": ["1476033859.a", "1476033855.a"], "tag": None},
    }

    # mock for at.jobcheck module call
    mock_atjobcheck = {
        "jobs": [
            {
                "date": "2015-11-04",
                "job": "1476031633.a",
                "queue": "a",
                "tag": tag,
                "time": "09:09:00",
                "user": user,
            },
        ],
    }

    # normal return
    ret = {
        "name": name,
        "result": True,
        "changes": {"removed": ["1476033859.a", "1476033855.a"]},
        "comment": "removed 2 job(s)",
    }

    # remove a job with test=True
    with patch.dict(at.__opts__, {"test": True}):
        ret_test = {}
        ret_test.update(ret)
        ret_test.update({"result": None, "changes": {}, "comment": "removed ? job(s)"})
        assert at.absent(name) == ret_test

    # remove a job and pass limit parameter
    with patch.dict(at.__opts__, {"test": False}):
        ret_limit = {}
        ret_limit.update(ret)
        ret_limit.update(
            {
                "result": False,
                "changes": {},
                "comment": f"limit parameter not supported {name}",
            }
        )
        assert at.absent(name, limit="all") == ret_limit

    # remove all jobs (2 jobs found)
    mock = MagicMock(return_value=mock_atatrm)
    with patch.dict(at.__salt__, {"at.atrm": mock}):
        with patch.dict(at.__opts__, {"test": False}):
            assert at.absent(name) == ret

    # remove all jobs (0 jobs found)
    mock_atatrm_nojobs = {}
    mock_atatrm_nojobs.update(mock_atatrm)
    mock_atatrm_nojobs.update({"jobs": {"removed": []}})
    mock = MagicMock(return_value=mock_atatrm_nojobs)
    with patch.dict(at.__salt__, {"at.atrm": mock}):
        with patch.dict(at.__opts__, {"test": False}):
            ret_nojobs = {}
            ret_nojobs.update(ret)
            ret_nojobs.update(
                {"changes": {}, "comment": ret["comment"].replace("2", "0")}
            )
            assert at.absent(name) == ret_nojobs

    # remove all tagged jobs (1 jobs found)
    mock_atatrm_tag = {}
    mock_atatrm_tag.update(mock_atatrm)
    mock_atatrm_tag.update({"jobs": {"removed": ["1476031633.a"], "tag": "rose"}})
    mock = MagicMock(return_value=mock_atatrm_tag)
    with patch.dict(at.__salt__, {"at.atrm": mock}):
        mock = MagicMock(return_value=mock_atjobcheck)
        with patch.dict(at.__salt__, {"at.jobcheck": mock}):
            with patch.dict(at.__opts__, {"test": False}):
                ret_tag = {}
                ret_tag.update(ret)
                ret_tag.update(
                    {
                        "changes": {"removed": ["1476031633.a"]},
                        "comment": ret["comment"].replace("2", "1"),
                    }
                )
                assert at.absent(name, tag=tag) == ret_tag
