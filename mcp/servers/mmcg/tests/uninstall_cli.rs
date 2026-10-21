//! Uninstall stays inside disposable projects, homes, and native client fixtures.

use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};

struct Fixture {
    _temp: tempfile::TempDir,
    root: PathBuf,
    home: PathBuf,
    bin: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        for name in ["project", "home", "bin"] {
            fs::create_dir(temp.path().join(name)).unwrap();
        }
        Self {
            root: temp.path().join("project").canonicalize().unwrap(),
            home: temp.path().join("home").canonicalize().unwrap(),
            bin: temp.path().join("bin").canonicalize().unwrap(),
            _temp: temp,
        }
    }

    fn run(&self, scope: &str, force: bool) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_mmcg"));
        command
            .current_dir(&self.root)
            .env_clear()
            .env("HOME", &self.home)
            .env("USERPROFILE", &self.home)
            .env("PATH", std::env::join_paths([&self.bin]).unwrap())
            .env("FIXTURE_MMCG", env!("CARGO_BIN_EXE_mmcg"))
            .args(["uninstall", "--scope", scope]);
        if force {
            command.arg("--force");
        }
        command.output().unwrap()
    }

    #[cfg(unix)]
    fn native_client(&self) {
        use std::os::unix::fs::PermissionsExt;

        let script = self.bin.join("claude");
        fs::write(
            &script,
            r#"#!/bin/sh
printf '%s\n' "$*" >> "$HOME/native-calls"
[ "$1" = mcp ] || exit 91
case "$2" in
  get)
    [ -f "$HOME/registration" ] || exit 1
    printf '  Scope: User config\n  Type: stdio\n  Command: %s\n  Args: serve\n' "$FIXTURE_MMCG"
    ;;
  remove)
    [ ! -f "$HOME/fail-remove" ] || exit 7
    /bin/rm "$HOME/registration"
    ;;
  *) exit 92;;
esac
"#,
        )
        .unwrap();
        fs::set_permissions(script, fs::Permissions::from_mode(0o700)).unwrap();
        fs::write(self.home.join("registration"), "registered").unwrap();
    }
}

#[test]
fn malformed_project_registration_fails_and_preserves_the_config() {
    for scope in ["project", "all"] {
        let fixture = Fixture::new();
        #[cfg(unix)]
        fixture.native_client();
        let config = fixture.root.join(".mcp.json");
        let malformed = b"{\"mcpServers\": unfinished";
        fs::write(&config, malformed).unwrap();

        let output = fixture.run(scope, true);

        assert!(!output.status.success(), "{scope}: {output:?}");
        assert_eq!(fs::read(config).unwrap(), malformed);
        #[cfg(unix)]
        assert!(!fixture.home.join("native-calls").exists());
    }
}

#[test]
fn canonical_project_uninstall_previews_then_removes_only_owned_state() {
    let fixture = Fixture::new();
    let config = fixture.root.join(".mcp.json");
    let original = serde_json::to_vec(&json!({"mcpServers": {
        "mmcg": {"command": env!("CARGO_BIN_EXE_mmcg"), "args": ["serve"]},
        "other": {"command": "keep-me"}
    }}))
    .unwrap();
    fs::write(&config, &original).unwrap();
    fs::create_dir(fixture.root.join(".mastermind")).unwrap();
    fs::write(fixture.root.join(".mastermind/index"), "owned index").unwrap();
    for name in ["CONTEXT.md", "CLAUDE.md"] {
        fs::write(fixture.root.join(name), name).unwrap();
    }

    let planned = fixture.run("project", false);
    assert!(planned.status.success(), "{planned:?}");
    assert!(String::from_utf8_lossy(&planned.stdout).contains("dry_run"));
    assert_eq!(fs::read(&config).unwrap(), original);
    assert!(fixture.root.join(".mastermind/index").exists());

    let removed = fixture.run("project", true);
    assert!(removed.status.success(), "{removed:?}");
    let remaining: Value = serde_json::from_slice(&fs::read(config).unwrap()).unwrap();
    assert!(remaining["mcpServers"].get("mmcg").is_none());
    assert_eq!(remaining["mcpServers"]["other"]["command"], "keep-me");
    assert!(!fixture.root.join(".mastermind").exists());
    for name in ["CONTEXT.md", "CLAUDE.md"] {
        assert_eq!(fs::read_to_string(fixture.root.join(name)).unwrap(), name);
    }
    let repeated = fixture.run("project", true);
    assert!(repeated.status.success(), "{repeated:?}");
    assert!(String::from_utf8_lossy(&repeated.stdout).contains("outcome=no_change"));
}

#[test]
fn customized_project_registration_refusal_is_nonzero_without_writes() {
    let fixture = Fixture::new();
    let config = fixture.root.join(".mcp.json");
    let original = br#"{"mcpServers":{"mmcg":{"command":"custom-command"}}}"#;
    fs::write(&config, original).unwrap();

    let output = fixture.run("project", false);

    assert!(!output.status.success(), "{output:?}");
    assert!(String::from_utf8_lossy(&output.stdout).contains("refused"));
    assert_eq!(fs::read(config).unwrap(), original);
}

#[cfg(unix)]
#[test]
fn native_removal_failure_is_nonzero_for_global_and_all_scopes() {
    for scope in ["global", "all"] {
        let fixture = Fixture::new();
        fixture.native_client();
        fs::write(fixture.home.join("fail-remove"), "").unwrap();

        let output = fixture.run(scope, true);

        assert!(!output.status.success(), "{scope}: {output:?}");
        assert!(String::from_utf8_lossy(&output.stderr).contains("native_remove_failed"));
        assert!(fs::read_to_string(fixture.home.join("native-calls"))
            .unwrap()
            .lines()
            .any(|line| line == "mcp remove mmcg -s user"));
        assert_eq!(
            fs::read_to_string(fixture.home.join("registration")).unwrap(),
            "registered"
        );
    }
}

#[cfg(unix)]
#[test]
fn canonical_global_uninstall_previews_then_confirms_native_removal() {
    let fixture = Fixture::new();
    fixture.native_client();

    let planned = fixture.run("global", false);
    assert!(planned.status.success(), "{planned:?}");
    assert!(String::from_utf8_lossy(&planned.stdout).contains("dry_run"));
    assert!(fixture.home.join("registration").exists());
    assert!(!fs::read_to_string(fixture.home.join("native-calls"))
        .unwrap()
        .lines()
        .any(|line| line.starts_with("mcp remove")));

    let removed = fixture.run("global", true);
    assert!(removed.status.success(), "{removed:?}");
    assert!(!fixture.home.join("registration").exists());
    let repeated = fixture.run("global", true);
    assert!(repeated.status.success(), "{repeated:?}");
    assert!(String::from_utf8_lossy(&repeated.stdout).contains("outcome=no_change"));
}
