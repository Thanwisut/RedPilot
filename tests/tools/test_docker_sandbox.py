"""Container-backed tests for DockerSandboxFactory.

Tests are skipped if Docker is not available. Each test creates real Docker
containers and networks, exercises them, and cleans up.

See the HONEST GAP LIST in sandbox.py for what isn't tested here and why.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Any

import pytest

from redpilot_core.models.tool_manifest import SandboxProfile
from redpilot_tools.sandbox import DockerSandboxFactory


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


docker_required = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not available",
)


@pytest.fixture
def factory() -> DockerSandboxFactory:
    return DockerSandboxFactory()


def _safe_cleanup(cmd: list[str]) -> None:
    """Run a cleanup command, ignoring errors."""
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        pass


# ======================================================================
# 1. NETWORK EGRESS ALLOW-LIST
# ======================================================================


@docker_required
@pytest.mark.asyncio
async def test_egress_cannot_reach_external_host(factory: DockerSandboxFactory) -> None:
    """Sandbox with --internal network must NOT reach external hosts."""
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "10.255.255.255")
    result = await factory.execute(
        ["sh", "-c", "ping -c 1 -W 3 1.1.1.1 2>&1 || echo 'EGRESS_BLOCKED'"],
        ctx,
    )
    assert "EGRESS_BLOCKED" in result.stdout or "Network is unreachable" in result.stderr, (
        f"Should not reach external host. Exit={result.exit_code}, "
        f"stdout={result.stdout[:200]}, stderr={result.stderr[:200]}"
    )


@docker_required
@pytest.mark.asyncio
async def test_egress_target_on_same_network(factory: DockerSandboxFactory) -> None:
    """Sandbox CAN reach a target container on the same --internal network.

    Approach:
    1. build() to get the context (includes network_name in metadata)
    2. Pre-create the network and start a target container on it
    3. execute() creates the sandbox container on the same (pre-existing) network
    4. Sandbox reaches target by container name via Docker embedded DNS
    """
    target_name = "rp_target_samenet"
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, target_name)
    net_name = ctx.metadata.get("network_name", "rp_test_net")

    try:
        # Pre-create the network
        subprocess.run(
            ["docker", "network", "create", "--driver", "bridge", "--internal", net_name],
            capture_output=True, check=True, timeout=15,
        )

        # Start a target container on this network (listens on port 9999)
        subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "--name", target_name,
                "--network", net_name,
                "python:3.12-alpine",
                "sh", "-c",
                "while true; do echo -e 'HTTP/1.1 200 OK\\r\\n\\r\\ntarget_ok' | "
                "nc -l -p 9999 2>/dev/null; done",
            ],
            capture_output=True, check=True, timeout=15,
        )
        # Give the target a moment to start
        time.sleep(1)

        # Execute sandbox — it will find the network already exists and reuse it
        result = await factory.execute(
            [
                "sh", "-c",
                f"wget -q -O - http://{target_name}:9999 -T 5 2>/dev/null "
                f"|| echo 'WGET_FAILED'",
            ],
            ctx,
        )

        assert "target_ok" in result.stdout, (
            f"Sandbox should reach target on same network. "
            f"Got: stdout={result.stdout[:300]}, stderr={result.stderr[:200]}"
        )
    finally:
        _safe_cleanup(["docker", "kill", target_name])
        _safe_cleanup(["docker", "network", "rm", net_name])


@docker_required
@pytest.mark.asyncio
async def test_egress_cannot_reach_second_target(factory: DockerSandboxFactory) -> None:
    """Sandbox scoped to target A cannot reach a different target B on a
    separate network.

    This tests the weaker but verifiable version of per-target isolation:
    - Target A is on the sandbox's --internal network (reachable)
    - Target B is on a DIFFERENT network (unreachable from the --internal net)

    The test uses a single execute() call to avoid the network lifecycle
    issue where the factory's cleanup removes the network between calls.
    Inside the container, we try to reach both targets and report results.
    """
    target_a_name = "rp_iso_a"
    target_b_name = "rp_iso_b"
    net_name = "rp_net_isolation_test"

    try:
        # Create the sandbox network + connect target A
        subprocess.run(
            ["docker", "network", "create", "--driver", "bridge", "--internal", net_name],
            capture_output=True, check=True, timeout=15,
        )
        subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "--name", target_a_name, "--network", net_name,
                "python:3.12-alpine",
                "sh", "-c",
                "while true; do echo 'I_AM_TARGET_A' | nc -l -p 9999 2>/dev/null; done",
            ],
            capture_output=True, check=True, timeout=15,
        )

        # Target B is on default bridge (not the --internal network)
        subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "--name", target_b_name,
                "python:3.12-alpine",
                "sh", "-c",
                "while true; do echo 'I_AM_TARGET_B' | nc -l -p 9999 2>/dev/null; done",
            ],
            capture_output=True, check=True, timeout=15,
        )

        time.sleep(1)

        # Build context referencing target_a name
        ctx = factory.build(SandboxProfile.CODE_ANALYSIS, target_a_name)
        # Override network name to match our pre-created one
        ctx.metadata["network_name"] = net_name

        # Single execute() — inside the container, probe both targets
        result = await factory.execute(
            [
                "sh", "-c",
                f"echo '' | nc -w 2 {target_a_name} 9999 2>&1; "
                f"echo '---TARGET_B---'; "
                f"echo '' | nc -w 2 {target_b_name} 9999 2>&1 || echo 'B_UNREACHABLE'",
            ],
            ctx,
        )

        # Should reach target A (on the same network)
        assert "I_AM_TARGET_A" in result.stdout, (
            f"Should reach target A on same network. "
            f"stdout={result.stdout[:300]}, stderr={result.stderr[:200]}"
        )

        # Should NOT reach target B (different network)
        assert "B_UNREACHABLE" in result.stdout or "I_AM_TARGET_B" not in result.stdout, (
            f"Should NOT reach target B on separate network. "
            f"stdout={result.stdout[:300]}, stderr={result.stderr[:200]}"
        )

    finally:
        _safe_cleanup(["docker", "kill", target_a_name])
        _safe_cleanup(["docker", "kill", target_b_name])
        _safe_cleanup(["docker", "network", "rm", net_name])
        _safe_cleanup(["docker", "rm", "-f", target_b_name])


@docker_required
@pytest.mark.asyncio
async def test_concurrent_per_target_isolation(
    factory: DockerSandboxFactory,
) -> None:
    """Two concurrent invocations on separate --internal networks.
    Each sandbox can reach ONLY its own invocation's target.

    This verifies the per-target egress granularity: each invocation
    gets its own fresh Docker network with a unique name. Container A
    on network_A cannot reach target_B on network_B, and vice versa.

    Architecture note: This works because each invocation creates its
    own ``--internal`` Docker network. Per-target filtering WITHIN a
    single network (e.g., two targets on the same network but one
    container can only reach one of them) is NOT achieved — that
    requires iptables/nftables which are not available in this
    Docker-for-Mac environment. See the HONEST GAP LIST for details.
    """
    import asyncio

    target_a = "rp_conc_tgt_a"
    target_b = "rp_conc_tgt_b"
    net_a = "rp_conc_net_a"
    net_b = "rp_conc_net_b"

    try:
        # Create two separate --internal networks
        for net in [net_a, net_b]:
            subprocess.run(
                ["docker", "network", "create", "--driver", "bridge", "--internal", net],
                capture_output=True, check=True, timeout=15,
            )

        # Start target A on net_a
        subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "--name", target_a, "--network", net_a,
                "python:3.12-alpine",
                "sh", "-c",
                "while true; do echo 'TGT_A_DATA' | nc -l -p 9999 2>/dev/null; done",
            ],
            capture_output=True, check=True, timeout=15,
        )

        # Start target B on net_b
        subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "--name", target_b, "--network", net_b,
                "python:3.12-alpine",
                "sh", "-c",
                "while true; do echo 'TGT_B_DATA' | nc -l -p 9999 2>/dev/null; done",
            ],
            capture_output=True, check=True, timeout=15,
        )

        time.sleep(1)

        # Build two contexts, each pointing to its own network
        ctx_a = factory.build(SandboxProfile.CODE_ANALYSIS, target_a)
        ctx_a.metadata["network_name"] = net_a
        ctx_a.timeout_seconds = 15

        ctx_b = factory.build(SandboxProfile.CODE_ANALYSIS, target_b)
        ctx_b.metadata["network_name"] = net_b
        ctx_b.timeout_seconds = 15

        # ---- Concurrent execution ----
        # Container A probes both targets; container B probes both targets.
        results = await asyncio.gather(
            factory.execute(
                [
                    "sh", "-c",
                    f"echo '' | nc -w 3 {target_a} 9999 2>&1; "
                    f"echo '---SEP---'; "
                    f"echo '' | nc -w 3 {target_b} 9999 2>&1 || echo 'B_NOT_REACHABLE'",
                ],
                ctx_a,
            ),
            factory.execute(
                [
                    "sh", "-c",
                    f"echo '' | nc -w 3 {target_b} 9999 2>&1; "
                    f"echo '---SEP---'; "
                    f"echo '' | nc -w 3 {target_a} 9999 2>&1 || echo 'A_NOT_REACHABLE'",
                ],
                ctx_b,
            ),
        )

        result_a, result_b = results

        # Container A can reach its own target (target_a) but NOT target_b
        assert "TGT_A_DATA" in result_a.stdout, (
            f"A should reach its target. stdout={result_a.stdout[:300]}"
        )
        assert "B_NOT_REACHABLE" in result_a.stdout or "TGT_B_DATA" not in result_a.stdout, (
            f"A should NOT reach B's target. stdout={result_a.stdout[:300]}"
        )

        # Container B can reach its own target (target_b) but NOT target_a
        assert "TGT_B_DATA" in result_b.stdout, (
            f"B should reach its target. stdout={result_b.stdout[:300]}"
        )
        assert "A_NOT_REACHABLE" in result_b.stdout or "TGT_A_DATA" not in result_b.stdout, (
            f"B should NOT reach A's target. stdout={result_b.stdout[:300]}"
        )

    finally:
        _safe_cleanup(["docker", "kill", target_a])
        _safe_cleanup(["docker", "kill", target_b])
        for net in [net_a, net_b]:
            _safe_cleanup(["docker", "network", "rm", net])


# ======================================================================
# 3b. SUPERVISOR HARDENING (Items 1-3)
# ======================================================================


@docker_required
@pytest.mark.asyncio
async def test_supervisor_start_new_session(
    factory: DockerSandboxFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supervisor Popen uses ``start_new_session=True`` so it survives
    a signal sent to the parent's process group.

    ITEM 1 — PROCESS-GROUP ISOLATION.

    This test captures the supervisor's Popen kwargs via monkeypatch
    and verifies ``start_new_session=True`` is passed. The supervisor
    must be detached from the parent's session so Ctrl+C or a process
    manager's SIGTERM to the entire group doesn't kill it before it
    can fire ``docker kill``.
    """
    original_popen = subprocess.Popen
    captured: dict[str, Any] = {}

    def tracking_popen(cmd: list[str], **kwargs: Any) -> subprocess.Popen:
        # Identify the supervisor call: uses sys.executable + _SUPERVISOR_SCRIPT
        if len(cmd) >= 4 and cmd[1] == "-c" and "docker kill" in cmd[2]:
            captured["start_new_session"] = kwargs.get("start_new_session", False)
            captured["has_shell_string"] = any(
                isinstance(arg, str) and ("sh" in arg or "$(" in arg)
                for arg in cmd
            )
        return original_popen(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", tracking_popen)

    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
    ctx.timeout_seconds = 5
    await factory.execute(["sh", "-c", "echo 'DONE'"], ctx)

    assert captured.get("start_new_session") is True, (
        "Supervisor Popen must have start_new_session=True "
        "for process-group independence"
    )
    assert not captured.get("has_shell_string", True), (
        "Supervisor must use argv-based command (no shell string)"
    )


@docker_required
@pytest.mark.asyncio
async def test_supervisor_reaped_after_normal_completion(
    factory: DockerSandboxFactory,
) -> None:
    """After a fast invocation that finishes within its timeout, the
    supervisor process must be killed and reaped — no zombie left behind.

    ITEM 2 — SUPERVISOR CLEANUP ON NORMAL COMPLETION.

    The test runs a quick command and then checks that the factory's
    ``_last_supervisor`` (tracked internally) has been polled/wait'd
    and its exit status is set, proving it was reaped.
    """
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
    ctx.timeout_seconds = 30  # Well more than the command needs

    await factory.execute(["sh", "-c", "echo 'DONE'"], ctx)

    sup = factory._last_supervisor
    assert sup is not None, "Factory should track the last supervisor"

    sup_return = sup.poll()
    assert sup_return is not None, (
        f"Supervisor should be reaped after normal completion. "
        f"poll() returned None (still running). "
        f"Return code: {sup_return}"
    )
    # If supervisor was killed (normal path): exit code is -9 (SIGKILL)
    # If supervisor was still sleeping and we killed it: exit code is -9
    # If supervisor already exited by coincidence: exit code is 0
    # SIGKILL (-9) from .kill() is the expected exit code.
    # 0 would mean the supervisor exited normally (not killed) — a bug.
    assert sup_return == -9, (
        f"Supervisor should be killed with SIGKILL (-9), "
        f"got {sup_return}. Full poll: {sup.poll()}"
    )


# ======================================================================
# 2. RESOURCE LIMITS
# ======================================================================


@docker_required
@pytest.mark.asyncio
async def test_memory_limit_enforced(factory: DockerSandboxFactory) -> None:
    """Tight memory limit should cause process failure via OOM."""
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
    ctx.resource_limits.memory_mb = 15  # Very tight
    ctx.timeout_seconds = 30

    result = await factory.execute(
        [
            "sh", "-c",
            "python3 -c \"x = bytearray(50_000_000); print('ALLOCATED')\" 2>&1 "
            "|| echo 'ALLOC_FAILED'",
        ],
        ctx,
    )

    # The process should fail due to memory limit (OOM kill via cgroup)
    assert result.exit_code != 0 or "ALLOC_FAILED" in result.stdout, (
        f"Tight memory should cause failure. Exit={result.exit_code}, "
        f"stdout={result.stdout[:200]}, stderr={result.stderr[:200]}"
    )


@docker_required
@pytest.mark.asyncio
async def test_cpu_limit_applied(factory: DockerSandboxFactory) -> None:
    """CPU limit should be accepted by Docker."""
    ctx = factory.build(SandboxProfile.NETWORK_SCAN_STANDARD, "127.0.0.1")
    ctx.resource_limits.cpu_count = 0.5
    ctx.timeout_seconds = 15

    result = await factory.execute(["sh", "-c", "echo 'DONE'"], ctx)
    assert result.exit_code == 0, f"CPU-limited container should start. Exit={result.exit_code}"
    assert "DONE" in result.stdout


# ======================================================================
# 3. TWO INDEPENDENT TIMEOUT ENFORCEMENT POINTS
# ======================================================================


@docker_required
@pytest.mark.asyncio
async def test_sandbox_timeout_kills_hung_process(factory: DockerSandboxFactory) -> None:
    """Prove the OS-level supervisor is the real timeout mechanism.

    The factory sets ``communicate(timeout=timeout + 300)`` — with
    ``timeout_seconds=3``, the Python-level communicate won't fire
    until 303 seconds. If the container is killed in ~3 seconds, the
    independent OS-level supervisor (``sleep 3 && docker kill`` in a
    separate ``subprocess.Popen``) did it, not the communicate() call.
    """
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
    ctx.timeout_seconds = 3

    start = time.monotonic()
    result = await factory.execute(
        ["sh", "-c", "echo 'START'; sleep 60; echo 'END'"],
        ctx,
    )
    elapsed = time.monotonic() - start

    assert elapsed < 10, (
        f"Supervisor should fire at ~3s. Elapsed: {elapsed:.1f}s. "
        f"If communicate() were the mechanism this would take ~303s."
    )
    assert result.exit_code == -1, f"Should indicate timeout. Exit={result.exit_code}"
    assert "TIMEOUT" in result.stderr, f"Should report timeout. stderr={result.stderr[:200]}"
    assert "START" in result.stdout, "Partial output should be captured"





# ======================================================================
# 4. CAPABILITIES
# ======================================================================


@docker_required
@pytest.mark.asyncio
async def test_default_no_raw_socket(factory: DockerSandboxFactory) -> None:
    """Without NET_RAW, raw socket creation must fail."""
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
    ctx.granted_capabilities = []
    ctx.timeout_seconds = 30

    result = await factory.execute(
        [
            "sh", "-c",                "python3 -c 'import socket; "
            "s=socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)' "
            "2>&1 || echo 'RAW_DENIED_EXPECTED'",
        ],
        ctx,
    )

    assert "RAW_DENIED_EXPECTED" in result.stdout or "Operation not permitted" in result.stderr, (
        f"Raw socket should fail without NET_RAW. "
        f"stdout={result.stdout[:300]}, stderr={result.stderr[:200]}"
    )


@docker_required
@pytest.mark.asyncio
async def test_net_raw_granted(factory: DockerSandboxFactory) -> None:
    """With NET_RAW granted, raw socket creation must succeed."""
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
    ctx.granted_capabilities = ["NET_RAW"]
    ctx.timeout_seconds = 30

    result = await factory.execute(
        [
            "sh", "-c",
            "python3 -c 'import socket; "
            "s=socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP); "
            "print(\"RAW_OK\")' 2>&1",
        ],
        ctx,
    )

    assert "RAW_OK" in result.stdout, (
        f"Raw socket should succeed with NET_RAW. "
        f"stdout={result.stdout[:300]}, stderr={result.stderr[:200]}"
    )


# ======================================================================
# 5. FILESYSTEM / SCRATCH DIR
# ======================================================================


@docker_required
@pytest.mark.asyncio
async def test_scratch_dir_read_write(factory: DockerSandboxFactory) -> None:
    """Scratch dir must be read-write accessible inside container."""
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
    ctx.timeout_seconds = 10

    result = await factory.execute(
        ["sh", "-c", "echo 'sandbox_data' > /scratch/sb_test.txt && cat /scratch/sb_test.txt"],
        ctx,
    )
    assert result.exit_code == 0, f"Container should run. Exit={result.exit_code}"
    assert "sandbox_data" in result.stdout


@docker_required
@pytest.mark.asyncio
async def test_scratch_dir_file_persists_on_host(factory: DockerSandboxFactory) -> None:
    """Files written inside container appear on the host filesystem."""
    with tempfile.TemporaryDirectory() as tmpdir:
        factory_local = DockerSandboxFactory(scratch_base=tmpdir)
        ctx = factory_local.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
        ctx.timeout_seconds = 10

        await factory_local.execute(
            ["sh", "-c", "echo 'evidence_data' > /scratch/evidence.txt"],
            ctx,
        )

        evidence_file = os.path.join(ctx.scratch_dir, "evidence.txt")
        assert os.path.exists(evidence_file), f"File should persist on host: {evidence_file}"
        with open(evidence_file) as f:
            content = f.read()
        assert "evidence_data" in content
        assert ctx.scratch_dir.startswith(tmpdir), (
            f"Scratch dir should be under scratch_base: {ctx.scratch_dir}"
        )


@docker_required
@pytest.mark.asyncio
async def test_clean_invocation_isolation(factory: DockerSandboxFactory) -> None:
    """Two invocations — second must start with clean filesystem."""
    with tempfile.TemporaryDirectory() as tmpdir:
        factory_iso = DockerSandboxFactory(scratch_base=tmpdir)

        # First invocation writes file
        ctx1 = factory_iso.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
        ctx1.timeout_seconds = 15
        await factory_iso.execute(
            ["sh", "-c", "echo 'first_run_data' > /scratch/data.txt"],
            ctx1,
        )

        # Second invocation checks that /scratch is empty inside container
        ctx2 = factory_iso.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
        ctx2.timeout_seconds = 15
        result2 = await factory_iso.execute(
            ["sh", "-c", "ls /scratch/ 2>&1; echo '---DONE---'"],
            ctx2,
        )

        # Container's /scratch should be empty (no data.txt)
        assert "data.txt" not in result2.stdout, (
            f"Second container's scratch dir should be clean. "
            f"Got: {result2.stdout[:200]}"
        )

        # Scratch dirs must be different paths
        assert ctx1.scratch_dir != ctx2.scratch_dir, (
            "Each invocation must get a fresh scratch dir"
        )


@docker_required
@pytest.mark.asyncio
async def test_upload_download(factory: DockerSandboxFactory) -> None:
    """Files placed in scratch dir from host are visible inside container,
    and files written inside persist back to host."""
    ctx = factory.build(SandboxProfile.CODE_ANALYSIS, "127.0.0.1")
    ctx.timeout_seconds = 10

    # Write input file from host side
    host_file = os.path.join(ctx.scratch_dir, "input.txt")
    with open(host_file, "w") as f:
        f.write("host_data")

    result = await factory.execute(
        [
            "sh", "-c",
            "cat /scratch/input.txt && echo '---SEPARATOR---' "
            "&& echo 'output_ok' && echo 'output_ok' > /scratch/output.txt",
        ],
        ctx,
    )

    assert "host_data" in result.stdout, (
        f"Should read host file. Got: {result.stdout[:200]}"
    )
    assert "output_ok" in result.stdout, (
        f"'output_ok' should appear in stdout. Got: {result.stdout[:200]}"
    )
    assert os.path.exists(os.path.join(ctx.scratch_dir, "output.txt")), (
        "Output file should persist on host"
    )
