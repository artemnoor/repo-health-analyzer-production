use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::{
    Category, Issue, Level, Location, Range, Replacement, Suggestion, SuggestionSource,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
struct ShellcheckMessage {
    file: String,
    line: u32,
    #[serde(alias = "endLine")]
    end_line: u32,
    column: u32,
    #[serde(alias = "endColumn")]
    end_column: u32,
    level: String,
    code: u32,
    message: String,
    #[serde(default)]
    fix: Option<ShellcheckFix>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct ShellcheckFix {
    replacements: Vec<ShellcheckReplacement>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct ShellcheckReplacement {
    column: u32,
    #[serde(alias = "endColumn")]
    end_column: u32,
    #[serde(alias = "endLine")]
    end_line: u32,
    #[serde(alias = "insertionPoint")]
    insertion_point: String,
    line: u32,
    precedence: u32,
    replacement: String,
}

pub struct Shellcheck;

impl Parser for Shellcheck {
    fn parse(&self, plugin_name: &str, output: &str) -> Result<Vec<Issue>> {
        let mut issues = vec![];

        let messages: Vec<ShellcheckMessage> = serde_json::from_str(output)?;

        for message in messages {
            let suggestions = self.build_suggestions(&message);
            let issue = Issue {
                tool: plugin_name.into(),
                message: message.message,
                category: Category::Lint.into(),
                level: level_to_level(&message.level).into(),
                rule_key: message.code.to_string(),
                suggestions,
                location: Some(Location {
                    path: message.file,
                    range: Some(Range {
                        start_line: message.line,
                        start_column: message.column,
                        end_line: message.end_line,
                        end_column: message.end_column,
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

impl Shellcheck {
    fn build_suggestions(&self, message: &ShellcheckMessage) -> Vec<Suggestion> {
        if let Some(fix) = &message.fix {
            let replacements = fix
                .replacements
                .iter()
                .map(|replacement| Replacement {
                    data: replacement.replacement.clone(),
                    location: Some(Location {
                        path: message.file.clone(),
                        range: Some(Range {
                            start_line: replacement.line,
                            start_column: replacement.column,
                            end_line: replacement.end_line,
                            end_column: replacement.end_column,
                            ..Default::default()
                        }),
                    }),
                })
                .collect();

            vec![Suggestion {
                source: SuggestionSource::Tool.into(),
                replacements,
                ..Default::default()
            }]
        } else {
            vec![]
        }
    }
}

fn level_to_level(level: &str) -> Level {
    match level {
        "error" => Level::High,
        "warning" => Level::Medium,
        "style" => Level::Low,
        "info" => Level::Low,
        _ => Level::Low,
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn parse() {
        let input = r###"[
            {
                "file": "cli/test_script.sh",
                "line": 15,
                "endLine": 15,
                "column": 8,
                "endColumn": 15,
                "level": "style",
                "code": 2006,
                "message": "Use $(...) notation instead of legacy backticks `...`",
                "fix": {
                    "replacements": [
                        {
                            "column": 8,
                            "endColumn": 9,
                            "endLine": 15,
                            "insertionPoint": "afterEnd",
                            "line": 15,
                            "precedence": 8,
                            "replacement": "$("
                        },
                        {
                            "column": 14,
                            "endColumn": 15,
                            "endLine": 15,
                            "insertionPoint": "beforeStart",
                            "line": 15,
                            "precedence": 8,
                            "replacement": ")"
                        }
                    ]
                }
            },
            {
                "file": "cli/test_script.sh",
                "line": 24,
                "endLine": 24,
                "column": 8,
                "endColumn": 11,
                "level": "warning",
                "code": 2050,
                "message": "This expression is constant. Did you forget the $ on a variable?",
                "fix": null
            },
            {
                "file": "cli/test_script.sh",
                "line": 50,
                "endLine": 50,
                "column": 6,
                "endColumn": 22,
                "level": "info",
                "code": 2086,
                "message": "Double quote to prevent globbing and word splitting.",
                "fix": {
                    "replacements": [
                        {
                            "column": 6,
                            "endColumn": 6,
                            "endLine": 50,
                            "insertionPoint": "afterEnd",
                            "line": 50,
                            "precedence": 7,
                            "replacement": "\""
                        },
                        {
                            "column": 22,
                            "endColumn": 22,
                            "endLine": 50,
                            "insertionPoint": "beforeStart",
                            "line": 50,
                            "precedence": 7,
                            "replacement": "\""
                        }
                    ]
                }
            },
            {
                "file": "cli/test_script.sh",
                "line": 55,
                "endLine": 55,
                "column": 5,
                "endColumn": 13,
                "level": "error",
                "code": 2007,
                "message": "Use $((..)) instead of deprecated $[..]",
                "fix": null
            }
        ]"###;

        let parser = Shellcheck {};
        let issues = parser.parse("shellcheck", input).unwrap();

        insta::assert_yaml_snapshot!(issues, @r#"
        - tool: shellcheck
          ruleKey: "2006"
          message: "Use $(...) notation instead of legacy backticks `...`"
          level: LEVEL_LOW
          category: CATEGORY_LINT
          location:
            path: cli/test_script.sh
            range:
              startLine: 15
              startColumn: 8
              endLine: 15
              endColumn: 15
          suggestions:
            - source: SUGGESTION_SOURCE_TOOL
              replacements:
                - data: $(
                  location:
                    path: cli/test_script.sh
                    range:
                      startLine: 15
                      startColumn: 8
                      endLine: 15
                      endColumn: 9
                - data: )
                  location:
                    path: cli/test_script.sh
                    range:
                      startLine: 15
                      startColumn: 14
                      endLine: 15
                      endColumn: 15
        - tool: shellcheck
          ruleKey: "2050"
          message: This expression is constant. Did you forget the $ on a variable?
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: cli/test_script.sh
            range:
              startLine: 24
              startColumn: 8
              endLine: 24
              endColumn: 11
        - tool: shellcheck
          ruleKey: "2086"
          message: Double quote to prevent globbing and word splitting.
          level: LEVEL_LOW
          category: CATEGORY_LINT
          location:
            path: cli/test_script.sh
            range:
              startLine: 50
              startColumn: 6
              endLine: 50
              endColumn: 22
          suggestions:
            - source: SUGGESTION_SOURCE_TOOL
              replacements:
                - data: "\""
                  location:
                    path: cli/test_script.sh
                    range:
                      startLine: 50
                      startColumn: 6
                      endLine: 50
                      endColumn: 6
                - data: "\""
                  location:
                    path: cli/test_script.sh
                    range:
                      startLine: 50
                      startColumn: 22
                      endLine: 50
                      endColumn: 22
        - tool: shellcheck
          ruleKey: "2007"
          message: "Use $((..)) instead of deprecated $[..]"
          level: LEVEL_HIGH
          category: CATEGORY_LINT
          location:
            path: cli/test_script.sh
            range:
              startLine: 55
              startColumn: 5
              endLine: 55
              endColumn: 13
        "#);
    }
}
