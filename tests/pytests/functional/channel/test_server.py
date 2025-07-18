import asyncio
import ctypes
import logging
import multiprocessing
import os
import pathlib
import shutil
import stat
import time
from pathlib import Path

import pytest
from saltfactories.utils import random_string

import salt.channel.client
import salt.channel.server
import salt.config
import salt.crypt
import salt.master
import salt.utils.platform
import salt.utils.process
import salt.utils.stringutils
from tests.conftest import FIPS_TESTRUN

log = logging.getLogger(__name__)


pytestmark = [
    pytest.mark.skip_on_spawning_platform(
        reason="These tests are currently broken on spawning platforms. Need to be rewritten.",
    ),
    pytest.mark.timeout_unless_on_windows(120),
]


@pytest.fixture
def channel_minion_id():
    return random_string("Tha-Minion-")


@pytest.fixture
def root_dir(tmp_path):
    if salt.utils.platform.is_darwin():
        # To avoid 'OSError: AF_UNIX path too long'
        _root_dir = pathlib.Path("/tmp").resolve() / tmp_path.name
    else:
        _root_dir = tmp_path
    try:
        yield _root_dir
    finally:
        shutil.rmtree(str(_root_dir), ignore_errors=True)


def transport_ids(value):
    return f"transport({value})"


# @pytest.fixture(params=["ws", "tcp", "zeromq"], ids=transport_ids)
@pytest.fixture(
    params=[
        "ws",
        "tcp",
        "zeromq",
    ],
    ids=transport_ids,
)
def transport(request):
    return request.param


@pytest.fixture
def master_config(master_opts, transport, root_dir):
    master_opts.update(
        transport=transport,
        id="master",
        interface="127.0.0.1",
        fips_mode=FIPS_TESTRUN,
        publish_signing_algorithm=(
            "PKCS1v15-SHA224" if FIPS_TESTRUN else "PKCS1v15-SHA1"
        ),
        root_dir=str(root_dir),
    )
    priv, pub = salt.crypt.gen_keys(4096)
    path = pathlib.Path(master_opts["pki_dir"], "master")
    path.with_suffix(".pem").write_text(priv, encoding="utf-8")
    path.with_suffix(".pub").write_text(pub, encoding="utf-8")
    yield master_opts


@pytest.fixture
def minion_config(minion_opts, master_config, channel_minion_id):
    minion_opts.update(
        transport=master_config["transport"],
        root_dir=master_config["root_dir"],
        id=channel_minion_id,
        cachedir=master_config["cachedir"],
        sock_dir=master_config["sock_dir"],
        ret_port=master_config["ret_port"],
        interface="127.0.0.1",
        pki_dir=os.path.join(master_config["root_dir"], "pki_minion"),
        master_port=master_config["ret_port"],
        master_ip="127.0.0.1",
        master_uri="tcp://127.0.0.1:{}".format(master_config["ret_port"]),
        fips_mode=FIPS_TESTRUN,
        encryption_algorithm="OAEP-SHA224" if FIPS_TESTRUN else "OAEP-SHA1",
        signing_algorithm="PKCS1v15-SHA224" if FIPS_TESTRUN else "PKCS1v15-SHA1",
    )
    os.makedirs(minion_opts["pki_dir"], exist_ok=True)
    salt.crypt.AsyncAuth(minion_opts).get_keys()  # generate minion.pem/pub
    minion_pub = os.path.join(minion_opts["pki_dir"], "minion.pub")
    pub_on_master = os.path.join(master_config["pki_dir"], "minions", channel_minion_id)
    shutil.copyfile(minion_pub, pub_on_master)
    return minion_opts


@pytest.fixture
def process_manager():
    process_manager = salt.utils.process.ProcessManager()
    try:
        yield process_manager
    finally:
        process_manager.terminate()


@pytest.fixture
def master_secrets():
    salt.master.SMaster.secrets["aes"] = {
        "secret": multiprocessing.Array(
            ctypes.c_char,
            salt.utils.stringutils.to_bytes(salt.crypt.Crypticle.generate_key_string()),
        ),
        "serial": multiprocessing.Value(
            ctypes.c_longlong, lock=False  # We'll use the lock from 'secret'
        ),
    }
    yield
    salt.master.SMaster.secrets.pop("aes")


async def _connect_and_publish(
    io_loop, channel_minion_id, channel, server, received, timeout=60
):
    await channel.connect()

    async def cb(payload):
        received.append(payload)
        io_loop.stop()

    channel.on_recv(cb)
    io_loop.spawn_callback(
        server.publish, {"tgt_type": "glob", "tgt": [channel_minion_id], "WTF": "SON"}
    )
    start = time.time()
    while time.time() - start < timeout:
        await asyncio.sleep(1)
    io_loop.stop()


@pytest.fixture
def server_channel(master_config, process_manager):
    server_channel = salt.channel.server.PubServerChannel.factory(
        master_config,
    )
    server_channel.pre_fork(process_manager)
    try:
        yield server_channel
    finally:
        server_channel.close()


@pytest.fixture
def req_server_channel(master_config, process_manager):
    channel = salt.channel.server.ReqServerChannel.factory(master_config)
    channel.pre_fork(process_manager)
    try:
        yield channel
    finally:
        channel.close()


def test_pub_server_channel(
    io_loop,
    channel_minion_id,
    master_config,
    minion_config,
    process_manager,
    master_secrets,
    server_channel,
    req_server_channel,
):
    if not server_channel.transport.started.wait(30):
        pytest.fail("Server channel did not start within 30 seconds.")

    async def handle_payload(payload):
        log.debug("Payload handler got %r", payload)

    req_server_channel.post_fork(handle_payload, io_loop=io_loop)

    if master_config["transport"] == "zeromq":
        p = Path(str(master_config["sock_dir"])) / "workers.ipc"
        start = time.time()
        while not p.exists():
            time.sleep(0.3)
            if time.time() - start > 20:
                raise Exception("IPC socket not created")
        mode = os.lstat(p).st_mode
        assert bool(os.lstat(p).st_mode & stat.S_IRUSR)
        assert not bool(os.lstat(p).st_mode & stat.S_IRGRP)
        assert not bool(os.lstat(p).st_mode & stat.S_IROTH)

    pub_channel = salt.channel.client.AsyncPubChannel.factory(
        minion_config, io_loop=io_loop
    )
    received = []

    try:
        io_loop.add_callback(
            _connect_and_publish,
            io_loop,
            channel_minion_id,
            pub_channel,
            server_channel,
            received,
        )
        io_loop.start()
        assert len(received) == 1
    finally:
        server_channel.close()
        req_server_channel.close()
        pub_channel.close()
