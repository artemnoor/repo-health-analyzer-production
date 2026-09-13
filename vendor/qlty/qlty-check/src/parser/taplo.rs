use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::Issue;
use serde::{Deserialize, Serialize};

// #[derive(Debug, Serialize, Deserialize, Clone)]
// pub struct PylintMessage {
//     #[serde(alias = "message-id")]
//     pub message_id: Option<String>,
//     #[serde(alias = "type")]
//     pub message_type: String,
//     pub message: String,
//     pub symbol: String,
//     pub path: String,
//     pub line: Option<i32>,
//     pub column: Option<i32>,
//     #[serde(alias = "endLine")]
//     pub end_line: Option<i32>,
//     #[serde(alias = "endColumn")]
//     pub end_column: Option<i32>,
// }

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct Taplo {}

impl Parser for Taplo {
    fn parse(&self, _plugin_name: &str, _output: &str) -> Result<Vec<Issue>> {
        let issues = vec![];
        // let messages: Vec<PylintMessage> = serde_json::from_str(output)?;

        // for message in messages {
        //     let line = message.line.unwrap_or(1);
        //     let column = message.line.unwrap_or(1);

        //     let issue = Issue {
        //         message: message.message,
        //         level: message_type_to_level(&message.message_type).into(),
        //         rule_key: message.symbol.to_string(),
        //         path: message.path,
        //         start_line: line as u32,
        //         start_column: column as u32,
        //         end_line: message.end_line.unwrap_or(line) as u32,
        //         end_column: message.end_column.unwrap_or(column) as u32,
        //         ..Default::default()
        //     };

        //     issues.push(issue);
        // }

        Ok(issues)
    }
}
