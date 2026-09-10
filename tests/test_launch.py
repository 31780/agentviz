import os
import multiprocessing
import pathlib
import tempfile
import unittest
import subprocess
import time
from unittest import mock

import agentviz
from hooks import comet_monitor


def claim_launch_at_once(stamp, barrier, results):
    barrier.wait()
    claim = agentviz._claim_launch(8, stamp)
    won = claim is not False
    if won:
        agentviz._finish_launch(claim, True)
    results.put(won)


class LaunchTests(unittest.TestCase):
    ENV_KEYS = (
        "AGENTVIZ_BROWSER",
        "AGENTVIZ_DISABLE",
        "AGENTVIZ_LAUNCH_COOLDOWN",
        "AGENTVIZ_PAGE",
        "AGENTVIZ_PAGE_URL",
    )

    def setUp(self):
        self.saved_env = {key: os.environ.get(key) for key in self.ENV_KEYS}
        for key in self.ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_health_url_uses_the_relay_origin(self):
        self.assertEqual(
            agentviz._health_url("http://127.0.0.1:8766/index-2d.html?hud"),
            "http://127.0.0.1:8766/healthz",
        )

    def test_claim_launch_suppresses_overlapping_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            stamp = os.path.join(directory, "launch.stamp")
            claim = agentviz._claim_launch(8, stamp)
            self.assertIsNot(claim, False)
            agentviz._finish_launch(claim, True)
            self.assertIs(agentviz._claim_launch(8, stamp), False)

    def test_failed_launch_does_not_start_the_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            stamp = os.path.join(directory, "launch.stamp")
            failed = agentviz._claim_launch(8, stamp)
            agentviz._finish_launch(failed, False)
            retry = agentviz._claim_launch(8, stamp)
            self.assertIsNot(retry, False)
            agentviz._finish_launch(retry, True)

    def test_expired_cooldown_can_be_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            stamp = os.path.join(directory, "launch.stamp")
            with open(stamp, "w") as file:
                file.write("old")
            old = time.time() - 20
            os.utime(stamp, (old, old))

            claim = agentviz._claim_launch(8, stamp)

            self.assertIsNot(claim, False)
            agentviz._finish_launch(claim, True)

    @mock.patch("agentviz.os.open", side_effect=OSError("read only"))
    def test_unwritable_stamp_does_not_block_launch(self, open_file):
        self.assertEqual(agentviz._claim_launch(8, "/unwritable/stamp"), -1)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW is unavailable")
    def test_claim_launch_does_not_follow_a_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            victim = os.path.join(directory, "victim")
            stamp = os.path.join(directory, "launch.stamp")
            with open(victim, "w") as file:
                file.write("keep me")
            os.symlink(victim, stamp)

            self.assertEqual(agentviz._claim_launch(0, stamp), -1)
            with open(victim) as file:
                self.assertEqual(file.read(), "keep me")

    def test_claim_launch_is_atomic_across_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            stamp = os.path.join(directory, "launch.stamp")
            context = multiprocessing.get_context("fork")
            barrier = context.Barrier(6)
            results = context.Queue()
            workers = [
                context.Process(
                    target=claim_launch_at_once, args=(stamp, barrier, results)
                )
                for _ in range(6)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(5)
                self.assertEqual(worker.exitcode, 0)

            claims = [results.get(timeout=1) for _ in workers]
            self.assertEqual(claims.count(True), 1)

    @mock.patch("agentviz._open_page")
    @mock.patch("agentviz._start_relay")
    @mock.patch("agentviz._relay_is_ready", return_value=True)
    @mock.patch("agentviz._claim_launch", return_value=-1)
    def test_launch_reuses_a_running_relay(self, claim, ready, start, open_page):
        self.assertTrue(agentviz.launch("http://127.0.0.1:8766"))
        start.assert_not_called()
        open_page.assert_called_once_with("http://127.0.0.1:8766")

    @mock.patch("agentviz.time.sleep")
    @mock.patch("agentviz._open_page")
    @mock.patch("agentviz._start_relay")
    @mock.patch("agentviz._relay_is_ready", side_effect=[False, True])
    @mock.patch("agentviz._claim_launch", return_value=-1)
    def test_launch_starts_a_missing_relay(self, claim, ready, start, open_page, sleep):
        self.assertTrue(agentviz.launch("http://127.0.0.1:8766"))
        start.assert_called_once_with("2d", "http://127.0.0.1:8766")
        open_page.assert_called_once_with("http://127.0.0.1:8766")

    @mock.patch("agentviz.time.sleep")
    @mock.patch("agentviz._open_page")
    @mock.patch("agentviz._start_relay")
    @mock.patch("agentviz._relay_is_ready", return_value=False)
    @mock.patch("agentviz._claim_launch", return_value=-1)
    def test_launch_does_not_open_a_dead_relay(self, claim, ready, start, open_page, sleep):
        self.assertFalse(agentviz.launch("http://127.0.0.1:8766"))
        start.assert_called_once_with("2d", "http://127.0.0.1:8766")
        open_page.assert_not_called()

    @mock.patch("agentviz._open_page")
    @mock.patch("agentviz._relay_is_ready", return_value=True)
    @mock.patch("agentviz._claim_launch", return_value=-1)
    @mock.patch.dict(os.environ, {"AGENTVIZ_LAUNCH_COOLDOWN": "not-a-number"})
    def test_invalid_cooldown_uses_the_default(self, claim, ready, open_page):
        self.assertTrue(agentviz.launch("http://127.0.0.1:8766"))
        claim.assert_called_once_with(8.0)

    @mock.patch("agentviz.subprocess.Popen")
    @mock.patch("agentviz.subprocess.run")
    def test_start_relay_uses_the_launchd_job_when_installed(self, run, popen):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=0)]
        with mock.patch("agentviz.sys.platform", "darwin"):
            agentviz._start_relay("2d")

        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["/bin/launchctl", "kickstart", "-k", "gui/%s/com.agentviz.relay" % os.getuid()],
        )
        popen.assert_not_called()

    @mock.patch("agentviz.subprocess.Popen")
    @mock.patch("agentviz.subprocess.run")
    def test_start_relay_honors_a_custom_local_endpoint(self, run, popen):
        with mock.patch("agentviz.sys.platform", "darwin"):
            agentviz._start_relay("2d", "http://127.0.0.1:9000/view")

        run.assert_not_called()
        self.assertEqual(
            popen.call_args.args[0][-6:],
            ["--host", "127.0.0.1", "--port", "9000", "--page", "2d"],
        )

    @mock.patch("agentviz.subprocess.Popen")
    @mock.patch("agentviz.subprocess.run")
    def test_start_relay_does_not_bind_a_remote_endpoint(self, run, popen):
        self.assertIsNone(agentviz._start_relay("2d", "https://example.com/view"))
        run.assert_not_called()
        popen.assert_not_called()

    @mock.patch("agentviz.subprocess.Popen")
    @mock.patch("agentviz.subprocess.run")
    def test_start_relay_falls_back_when_launchd_restart_fails(self, run, popen):
        run.side_effect = [mock.Mock(returncode=0), mock.Mock(returncode=1)]
        with mock.patch("agentviz.sys.platform", "darwin"):
            agentviz._start_relay("2d")

        popen.assert_called_once()

    @mock.patch("agentviz.subprocess.Popen")
    @mock.patch("agentviz.subprocess.run")
    def test_start_relay_falls_back_when_launchd_is_absent(self, run, popen):
        run.return_value = mock.Mock(returncode=1)
        with mock.patch("agentviz.sys.platform", "darwin"):
            agentviz._start_relay("2d")

        popen.assert_called_once()

    @mock.patch("agentviz._open_page")
    @mock.patch("agentviz._claim_launch", return_value=False)
    def test_launch_cooldown_prevents_duplicate_tabs(self, claim, open_page):
        self.assertFalse(agentviz.launch("http://127.0.0.1:8766"))
        open_page.assert_not_called()

    @mock.patch("agentviz._open_page")
    @mock.patch.dict(os.environ, {"AGENTVIZ_DISABLE": "1"})
    def test_launch_can_be_disabled(self, open_page):
        self.assertFalse(agentviz.launch("http://127.0.0.1:8766"))
        open_page.assert_not_called()

    @mock.patch("agentviz.subprocess.Popen")
    def test_open_page_targets_brave_on_macos(self, popen):
        with mock.patch("agentviz.sys.platform", "darwin"):
            agentviz._open_page("http://127.0.0.1:8766")

        self.assertEqual(
            popen.call_args.args[0],
            ["/usr/bin/open", "-a", "Brave Browser", "http://127.0.0.1:8766"],
        )

    @mock.patch("agentviz.subprocess.Popen")
    @mock.patch.dict(os.environ, {"AGENTVIZ_BROWSER": "Brave Browser Beta"})
    def test_open_page_honors_the_browser_override(self, popen):
        with mock.patch("agentviz.sys.platform", "darwin"):
            agentviz._open_page("http://127.0.0.1:8766")

        self.assertEqual(popen.call_args.args[0][2], "Brave Browser Beta")

    @mock.patch("webbrowser.open")
    def test_open_page_uses_webbrowser_off_macos(self, browser_open):
        with mock.patch("agentviz.sys.platform", "linux"):
            agentviz._open_page("http://127.0.0.1:8766")

        browser_open.assert_called_once_with("http://127.0.0.1:8766", new=2)

    def test_launch_shell_triggers_the_launchd_job(self):
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            launchctl = os.path.join(directory, "launchctl")
            with open(launchctl, "w") as file:
                file.write(
                    "#!/bin/sh\n"
                    "printf '%s\\n' \"$*\" >> \"$AGENTVIZ_TEST_LOG\"\n"
                    "exit 0\n"
                )
            os.chmod(launchctl, 0o755)
            env = os.environ.copy()
            env.update({"PATH": directory + ":/usr/bin:/bin", "AGENTVIZ_TEST_LOG": log})

            result = subprocess.run(
                ["/bin/bash", "hooks/launch.sh"], cwd=os.path.dirname(__file__) + "/..",
                env=env, check=False,
            )

            self.assertEqual(result.returncode, 0)
            with open(log) as file:
                calls = file.read()
            self.assertIn("print gui/", calls)
            self.assertIn("kickstart gui/", calls)

    def test_launch_shell_falls_back_when_launchd_job_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            launchctl = os.path.join(directory, "launchctl")
            python = os.path.join(directory, "python3")
            with open(launchctl, "w") as file:
                file.write("#!/bin/sh\nexit 1\n")
            with open(python, "w") as file:
                file.write("#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$AGENTVIZ_TEST_LOG\"\n")
            os.chmod(launchctl, 0o755)
            os.chmod(python, 0o755)
            env = os.environ.copy()
            env.update({"PATH": directory + ":/usr/bin:/bin", "AGENTVIZ_TEST_LOG": log})

            result = subprocess.run(
                ["/bin/bash", "hooks/launch.sh"], cwd=os.path.dirname(__file__) + "/..",
                env=env, check=False,
            )

            self.assertEqual(result.returncode, 0)
            with open(log) as file:
                self.assertTrue(file.read().strip().endswith("hooks/launch.py"))

    def test_launch_shell_falls_back_when_kickstart_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            launchctl = os.path.join(directory, "launchctl")
            python = os.path.join(directory, "python3")
            with open(launchctl, "w") as file:
                file.write("#!/bin/sh\n[ \"$1\" = print ] && exit 0\nexit 1\n")
            with open(python, "w") as file:
                file.write("#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$AGENTVIZ_TEST_LOG\"\n")
            os.chmod(launchctl, 0o755)
            os.chmod(python, 0o755)
            env = os.environ.copy()
            env.update({"PATH": directory + ":/usr/bin:/bin", "AGENTVIZ_TEST_LOG": log})

            result = subprocess.run(
                ["/bin/bash", "hooks/launch.sh"], cwd=os.path.dirname(__file__) + "/..",
                env=env, check=False,
            )

            self.assertEqual(result.returncode, 0)
            with open(log) as file:
                self.assertTrue(file.read().strip().endswith("hooks/launch.py"))

    def test_launch_shell_honors_disable(self):
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            launchctl = os.path.join(directory, "launchctl")
            with open(launchctl, "w") as file:
                file.write("#!/bin/sh\ntouch \"$AGENTVIZ_TEST_LOG\"\n")
            os.chmod(launchctl, 0o755)
            env = os.environ.copy()
            env.update({
                "PATH": directory + ":/usr/bin:/bin",
                "AGENTVIZ_TEST_LOG": log,
                "AGENTVIZ_DISABLE": "1",
            })

            result = subprocess.run(
                ["/bin/bash", "hooks/launch.sh"], cwd=os.path.dirname(__file__) + "/..",
                env=env, check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertFalse(os.path.exists(log))

    @mock.patch("hooks.comet_monitor.comet_pid", return_value="42")
    @mock.patch("hooks.comet_monitor.subprocess.run")
    def test_comet_monitor_launches_once_for_a_new_process(self, run, pid):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(comet_monitor, "STATE", pathlib.Path(directory) / "pid"):
                self.assertEqual(comet_monitor.main(), 0)
                self.assertEqual(comet_monitor.main(), 0)

        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["/bin/bash", str(comet_monitor.LAUNCHER)])

    @mock.patch("hooks.comet_monitor.comet_pid", return_value="")
    @mock.patch("hooks.comet_monitor.subprocess.run")
    def test_comet_monitor_does_not_launch_when_stopped(self, run, pid):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(comet_monitor, "STATE", pathlib.Path(directory) / "pid"):
                self.assertEqual(comet_monitor.main(), 0)

        run.assert_not_called()

    def test_zsh_ai_detector_invokes_the_launch_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            bash = os.path.join(directory, "bash")
            with open(bash, "w") as file:
                file.write("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$AGENTVIZ_TEST_LOG\"\n")
            os.chmod(bash, 0o755)
            env = os.environ.copy()
            env.update({"PATH": directory + ":/usr/bin:/bin", "AGENTVIZ_TEST_LOG": log})
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script = (
                "unsetopt BG_NICE; source " + root + "/contrib/agentviz.zsh; "
                "_agentviz_ai_preexec 'claude --version'; "
                "for attempt in {1..100}; do [[ -s $AGENTVIZ_TEST_LOG ]] && break; sleep 0.02; done"
            )

            result = subprocess.run(["/bin/zsh", "-fc", script], env=env, check=False)

            self.assertEqual(result.returncode, 0)
            with open(log) as file:
                self.assertIn(root + "/hooks/launch.sh", file.read())

    def test_zsh_ai_detector_handles_sudo_and_env_wrappers(self):
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            bash = os.path.join(directory, "bash")
            with open(bash, "w") as file:
                file.write("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$AGENTVIZ_TEST_LOG\"\n")
            os.chmod(bash, 0o755)
            env = os.environ.copy()
            env.update({"PATH": directory + ":/usr/bin:/bin", "AGENTVIZ_TEST_LOG": log})
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script = (
                "unsetopt BG_NICE; source " + root + "/contrib/agentviz.zsh; "
                "_agentviz_ai_preexec 'sudo -u nino codex'; "
                "_agentviz_ai_preexec 'env -i claude'; "
                "for attempt in {1..100}; do "
                "[[ -f $AGENTVIZ_TEST_LOG ]] && "
                "[[ $(wc -l < $AGENTVIZ_TEST_LOG) -ge 2 ]] && break; sleep 0.02; done"
            )

            result = subprocess.run(["/bin/zsh", "-fc", script], env=env, check=False)

            self.assertEqual(result.returncode, 0)
            with open(log) as file:
                self.assertEqual(file.read().count(root + "/hooks/launch.sh"), 2)

    def test_zsh_ai_detector_ignores_non_ai_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            bash = os.path.join(directory, "bash")
            with open(bash, "w") as file:
                file.write("#!/bin/sh\ntouch \"$AGENTVIZ_TEST_LOG\"\n")
            os.chmod(bash, 0o755)
            env = os.environ.copy()
            env.update({"PATH": directory + ":/usr/bin:/bin", "AGENTVIZ_TEST_LOG": log})
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script = (
                "source " + root + "/contrib/agentviz.zsh; "
                "_agentviz_ai_preexec 'echo claude'"
            )

            result = subprocess.run(["/bin/zsh", "-fc", script], env=env, check=False)

            self.assertEqual(result.returncode, 0)
            self.assertFalse(os.path.exists(log))


if __name__ == "__main__":
    unittest.main()
