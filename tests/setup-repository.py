#!/usr/bin/env python3
"""Check setup's repository selection using local Git repositories only."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = (Path(sys.argv.pop(1)) if len(sys.argv) > 1 else
          Path(__file__).resolve().parents[1] / "sdata/lib/repository.sh")


class SetupRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="setup-source-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.seed = self.root / "seed"
        self.fork = self.root / "fork.git"
        self.work = self.root / "checkout"
        self.git(self.root, "init", "-b", "main", str(self.seed))
        self.configure(self.seed)
        self.commit(self.seed, "base", "base")
        self.git(self.seed, "switch", "-c", "my-config")
        self.commit(self.seed, "custom", "custom")
        self.git(self.seed, "switch", "main")
        self.commit(self.seed, "upstream-only", "upstream")
        self.git(self.root, "clone", "--bare", str(self.seed), str(self.fork))
        self.git(self.root, "clone", str(self.fork), str(self.work))
        self.configure(self.work)

    def git(self, directory, *args):
        return subprocess.run(["git", "-C", str(directory), *args], check=True,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def configure(self, directory):
        self.git(directory, "config", "user.name", "Setup Test")
        self.git(directory, "config", "user.email", "setup@example.invalid")

    def commit(self, directory, name, text):
        (directory / name).write_text(text)
        self.git(directory, "add", name)
        self.git(directory, "commit", "-m", name)

    def run_helper(self, command='setup_update_repository false', url=None):
        env = dict(os.environ, SETUP_REPO_URL=str(url or self.fork),
                   SETUP_REPO_BRANCH="my-config", REPO_ROOT=str(self.work))
        return subprocess.run(["bash", "-c", '''
            log_info() { :; }
            log_error() { printf '%s\\n' "$1" >&2; }
            source "$1"
            cd "$REPO_ROOT" || exit 1
            eval "$2"
        ''', "test", str(SOURCE), command], env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def update_remote(self):
        self.git(self.seed, "switch", "my-config")
        self.commit(self.seed, "new-custom", "new custom")
        self.git(self.seed, "push", str(self.fork), "my-config")
        return self.git(self.seed, "rev-parse", "HEAD")

    def test_selects_custom_branch_instead_of_main(self):
        original_main = self.git(self.work, "rev-parse", "main")
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.work, "branch", "--show-current"), "my-config")
        self.assertTrue((self.work / "custom").is_file())
        self.assertFalse((self.work / "upstream-only").exists())
        self.assertEqual(self.git(self.work, "rev-parse", "main"), original_main)

    def test_ignores_wrong_tracking_branch(self):
        self.git(self.work, "switch", "-c", "my-config", "origin/my-config")
        self.git(self.work, "branch", "--set-upstream-to=origin/main", "my-config")
        expected = self.update_remote()
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), expected)

    def test_detached_dry_run_does_not_switch_or_fetch(self):
        self.git(self.work, "checkout", "--detach")
        head = self.git(self.work, "rev-parse", "HEAD")
        fetch_head = self.work / ".git/FETCH_HEAD"
        before = fetch_head.read_bytes() if fetch_head.exists() else None
        result = self.run_helper('setup_update_repository true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.work, "branch", "--show-current"), "")
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), head)
        self.assertEqual(fetch_head.read_bytes() if fetch_head.exists() else None, before)

    def test_divergence_keeps_local_commits(self):
        self.git(self.work, "switch", "-c", "my-config", "origin/my-config")
        self.commit(self.work, "local-only", "local")
        head = self.git(self.work, "rev-parse", "HEAD")
        self.update_remote()
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), head)
        self.assertEqual((self.work / "local-only").read_text(), "local")

    def test_failed_fetch_keeps_checkout(self):
        head = self.git(self.work, "rev-parse", "HEAD")
        result = self.run_helper(url=self.root / "missing.git")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git(self.work, "branch", "--show-current"), "main")
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), head)

    def test_install_requires_custom_branch(self):
        self.assertNotEqual(self.run_helper('setup_require_branch').returncode, 0)
        self.git(self.work, "switch", "-c", "my-config", "origin/my-config")
        self.assertEqual(self.run_helper('setup_require_branch').returncode, 0)
        self.git(self.work, "checkout", "--detach")
        self.assertNotEqual(self.run_helper('setup_require_branch').returncode, 0)

    def test_default_source(self):
        env = dict(os.environ)
        env.pop("SETUP_REPO_URL", None)
        env.pop("SETUP_REPO_BRANCH", None)
        result = subprocess.run(["bash", "-c", 'source "$1"; printf "%s\\n%s" "$SETUP_REPO_URL" "$SETUP_REPO_BRANCH"',
                                 "test", str(SOURCE)], env=env, check=True,
                                text=True, stdout=subprocess.PIPE)
        self.assertEqual(result.stdout,
                         "https://github.com/anfsity/dots-hyprland.git\nmy-config")


if __name__ == "__main__":
    unittest.main()
