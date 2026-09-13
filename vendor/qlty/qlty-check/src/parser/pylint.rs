use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::{Category, Issue, Level, Location, Range};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct PylintMessage {
    #[serde(alias = "message-id")]
    pub message_id: Option<String>,
    #[serde(alias = "type")]
    pub message_type: String,
    pub message: String,
    pub symbol: String,
    pub path: String,
    pub line: Option<i32>,
    pub column: Option<i32>,
    #[serde(alias = "endLine")]
    pub end_line: Option<i32>,
    #[serde(alias = "endColumn")]
    pub end_column: Option<i32>,
}

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct Pylint {}

impl Parser for Pylint {
    fn parse(&self, _plugin_name: &str, output: &str) -> Result<Vec<Issue>> {
        let mut issues = vec![];
        let messages: Vec<PylintMessage> = serde_json::from_str(output)?;

        for message in messages {
            let line = message.line.unwrap_or(1);
            let column = message.line.unwrap_or(1);

            let issue = Issue {
                tool: "pylint".into(),
                message: message.message,
                category: Category::Lint.into(),
                level: message_type_to_level(&message.message_type).into(),
                rule_key: message.symbol.to_string(),
                location: Some(Location {
                    path: message.path,
                    range: Some(Range {
                        start_line: line as u32,
                        start_column: column as u32,
                        end_line: message.end_line.unwrap_or(line) as u32,
                        end_column: message.end_column.unwrap_or(column) as u32,
                        ..Default::default()
                    }),
                }),
                ..Default::default()
            };

            issues.push(issue);
        }

        Ok(issues)
    }
}

fn message_type_to_level(message_type: &str) -> Level {
    match message_type {
        "fatal" => Level::High,
        "error" => Level::High,
        "refactor" => Level::Medium,
        "convention" => Level::Medium,
        "info" => Level::Low,
        _ => Level::Low,
    }
}
