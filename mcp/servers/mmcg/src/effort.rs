//! Deterministic effort selection from declared agent duties and task scope.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Level {
    Low,
    Medium,
    High,
    Xhigh,
    Max,
}

impl Level {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::Medium => "medium",
            Self::High => "high",
            Self::Xhigh => "xhigh",
            Self::Max => "max",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Risk {
    Low,
    High,
    #[default]
    Unknown,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Request {
    pub agent: String,
    pub task_family: String,
    pub read_only: bool,
    pub bounded_scope: bool,
    pub stable_inputs: bool,
    pub lexical_repo_map: bool,
    pub risk: Risk,
    pub user_effort: Option<Level>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Decision {
    pub schema_version: u32,
    pub policy: &'static str,
    pub requested_effort: Level,
    pub reason: &'static str,
    pub codex_args: Vec<String>,
    pub claude_args: Vec<String>,
    pub applied: bool,
    pub declarations_verified: bool,
    pub quality_qualified: bool,
}

pub fn select(request: &Request) -> Result<Decision, &'static str> {
    if request.agent.len() > 80 || request.task_family.len() > 80 {
        return Err("agent and task_family must fit 80 UTF-8 bytes");
    }
    let agent = request
        .agent
        .strip_prefix("mastermind-")
        .unwrap_or(&request.agent);
    let family_allowed = matches!(
        request.task_family.as_str(),
        "callees_trace" | "source_read_reuse" | "task_phase_trace"
    );
    let (effort, reason) = if let Some(level) = request.user_effort {
        (level, "explicit_user_effort")
    } else if request.risk != Risk::Low {
        (Level::High, "risk_high_or_unknown")
    } else if agent != "researcher" {
        (Level::High, "agent_not_allowlisted")
    } else if !family_allowed {
        (Level::High, "task_family_not_allowlisted")
    } else if !(request.read_only
        && request.bounded_scope
        && request.stable_inputs
        && request.lexical_repo_map)
    {
        (Level::High, "research_context_incomplete")
    } else {
        (Level::Low, "allowlisted_bounded_research_pilot")
    };
    Ok(Decision {
        schema_version: 1,
        policy: "task_agent_effort_v1",
        requested_effort: effort,
        reason,
        codex_args: vec![
            "-c".into(),
            format!("model_reasoning_effort=\"{}\"", effort.as_str()),
        ],
        claude_args: vec!["--effort".into(), effort.as_str().into()],
        // A tool result cannot change its caller's model configuration.
        applied: false,
        declarations_verified: false,
        quality_qualified: false,
    })
}

pub fn input_schema() -> Value {
    json!({
        "type": "object", "additionalProperties": false,
        "properties": {
            "agent": {"type": "string", "maxLength": 80, "description": "Actual agent duty; researcher or mastermind-researcher is eligible for the low pilot. Unknown duties retain high."},
            "task_family": {"type": "string", "maxLength": 80, "description": "Declared task family: callees_trace, source_read_reuse or task_phase_trace. Other families retain high."},
            "read_only": {"type": "boolean", "default": false},
            "bounded_scope": {"type": "boolean", "default": false},
            "stable_inputs": {"type": "boolean", "default": false},
            "lexical_repo_map": {"type": "boolean", "default": false, "description": "The research invocation uses the lexical map with a 1600-byte budget and the frozen direct-read/uncovered-range instruction."},
            "risk": {"type": "string", "enum": ["low", "high", "unknown"], "default": "unknown"},
            "user_effort": {"type": "string", "enum": ["low", "medium", "high", "xhigh", "max"], "description": "Explicit human override only; takes precedence over automatic routing."}
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn research() -> Request {
        Request {
            agent: "researcher".into(),
            task_family: "callees_trace".into(),
            read_only: true,
            bounded_scope: true,
            stable_inputs: true,
            lexical_repo_map: true,
            risk: Risk::Low,
            user_effort: None,
        }
    }

    #[test]
    fn approved_families_produce_client_overrides_without_claiming_application() {
        let mut request = research();
        request.agent = "mastermind-researcher".into();
        for family in ["callees_trace", "source_read_reuse", "task_phase_trace"] {
            request.task_family = family.into();
            let result = select(&request).unwrap();
            assert_eq!(result.requested_effort, Level::Low);
            assert_eq!(result.codex_args, ["-c", "model_reasoning_effort=\"low\""]);
            assert_eq!(result.claude_args, ["--effort", "low"]);
            assert!(!result.applied);
            assert!(!result.quality_qualified);
        }
    }

    #[test]
    fn missing_or_excluded_context_retains_high() {
        let mut cases = vec![Request::default()];
        for agent in [
            "executor",
            "auditor",
            "investigator",
            "security-auditor",
            "unknown",
        ] {
            cases.push(Request {
                agent: agent.into(),
                ..research()
            });
        }
        for family in ["concept_normalization", "removal_evidence", "unknown"] {
            cases.push(Request {
                task_family: family.into(),
                ..research()
            });
        }
        for risk in [Risk::High, Risk::Unknown] {
            cases.push(Request { risk, ..research() });
        }
        cases.extend([
            Request {
                read_only: false,
                ..research()
            },
            Request {
                bounded_scope: false,
                ..research()
            },
            Request {
                stable_inputs: false,
                ..research()
            },
            Request {
                lexical_repo_map: false,
                ..research()
            },
        ]);
        for request in cases {
            assert_eq!(
                select(&request).unwrap().requested_effort,
                Level::High,
                "{request:?}"
            );
        }
    }

    #[test]
    fn human_override_precedes_the_router_and_invalid_inputs_are_rejected() {
        let request = Request {
            user_effort: Some(Level::Max),
            ..research()
        };
        assert_eq!(select(&request).unwrap().requested_effort, Level::Max);
        let request = Request {
            user_effort: Some(Level::Low),
            ..Request::default()
        };
        assert_eq!(select(&request).unwrap().reason, "explicit_user_effort");
        assert!(serde_json::from_value::<Request>(json!({"read_only": "true"})).is_err());
        assert!(serde_json::from_value::<Request>(json!({"risk": "safe"})).is_err());
        assert!(
            serde_json::from_value::<Request>(json!({"task_famliy": "callees_trace"})).is_err()
        );
        assert!(select(&Request {
            agent: "x".repeat(81),
            ..research()
        })
        .is_err());
    }
}
