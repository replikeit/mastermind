//! JSON selection and explicit native-client application of the shared policy.

use std::ffi::OsString;
use std::io::{self, Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

#[derive(Clone, Copy, clap::ValueEnum)]
pub enum Client {
    Codex,
    Claude,
}

impl Client {
    fn program(self) -> &'static str {
        match self {
            Self::Codex => "codex",
            Self::Claude => "claude",
        }
    }
}

#[derive(clap::Args)]
pub struct Options {
    /// JSON request file; defaults to stdin for selection only.
    #[arg(long)]
    pub request: Option<PathBuf>,
    /// Launch this client with routed effort; prompt stdin and native arguments are preserved.
    #[arg(long, value_enum, requires = "request")]
    pub exec: Option<Client>,
    /// Client arguments after --. Set explicit effort in the request's user_effort field.
    #[arg(last = true, requires = "exec")]
    pub native_args: Vec<OsString>,
}

#[derive(Debug)]
pub struct NativeExit {
    pub code: u8,
}

impl std::fmt::Display for NativeExit {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "native client exited with {}", self.code)
    }
}

impl std::error::Error for NativeExit {}

fn validate_native_args(client: Client, args: &[OsString]) -> Result<(), &'static str> {
    let mut arguments = args.iter();
    while let Some(argument) = arguments.next() {
        let Some(argument) = argument.to_str() else {
            continue;
        };
        if argument == "--" {
            break;
        }
        let conflict = match client {
            Client::Claude => argument == "--effort" || argument.starts_with("--effort="),
            Client::Codex => {
                let config = if argument == "-c" || argument == "--config" {
                    arguments.next().and_then(|value| value.to_str())
                } else {
                    argument.strip_prefix("--config=").or_else(|| {
                        argument
                            .strip_prefix("-c")
                            .map(|value| value.strip_prefix('=').unwrap_or(value))
                    })
                };
                config.is_some_and(|value| {
                    // Accept the same quoted TOML key spellings as the native CLI.
                    value.split_once('=').is_some_and(|(key, _)| {
                        key.trim().trim_matches(['\'', '"']) == "model_reasoning_effort"
                    })
                })
            }
        };
        if conflict {
            return Err(
                "native effort arguments conflict with routing; use user_effort in the request",
            );
        }
    }
    Ok(())
}

pub fn route(options: &Options) -> Result<(), Box<dyn std::error::Error>> {
    const LIMIT: u64 = 16 * 1024;
    let reader: Box<dyn Read> = match &options.request {
        Some(path) => Box::new(std::fs::File::open(path)?),
        None => Box::new(io::stdin().lock()),
    };
    let mut bytes = Vec::new();
    reader.take(LIMIT + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > LIMIT {
        return Err("effort request exceeds 16 KiB".into());
    }
    let request: mmcg::effort::Request = serde_json::from_slice(&bytes)?;
    let decision = mmcg::effort::select(&request).map_err(io::Error::other)?;
    let Some(client) = options.exec else {
        println!("{}", serde_json::to_string_pretty(&decision)?);
        return Ok(());
    };
    validate_native_args(client, &options.native_args)?;
    if matches!(client, Client::Claude)
        && std::env::var_os("CLAUDE_CODE_EFFORT_LEVEL")
            .is_some_and(|value| value != decision.requested_effort.as_str())
    {
        return Err("CLAUDE_CODE_EFFORT_LEVEL conflicts with routing; use the matching user_effort or invoke without that environment override".into());
    }
    let overrides = match client {
        Client::Codex => &decision.codex_args,
        Client::Claude => &decision.claude_args,
    };
    let mut child = Command::new(client.program())
        .args(overrides)
        .args(&options.native_args)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()?;
    // Submission is observable; provider/agent settings may still override it.
    let _ = writeln!(
        io::stderr().lock(),
        "{}",
        serde_json::json!({
            "effort_route": decision,
            "client": client.program(),
            "override_submitted": true,
            "served_effort": null
        })
    );
    let status = child.wait()?;
    if !status.success() {
        return Err(Box::new(NativeExit {
            code: status
                .code()
                .and_then(|code| u8::try_from(code).ok())
                .unwrap_or(1),
        }));
    }
    Ok(())
}
