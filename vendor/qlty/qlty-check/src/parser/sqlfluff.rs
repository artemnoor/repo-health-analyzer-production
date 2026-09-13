use super::Parser;
use anyhow::Result;
use qlty_types::analysis::v1::{
    Category, Issue, Level, Location, Range, Replacement, Suggestion, SuggestionSource,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct SqlfluffFile {
    #[serde(alias = "filepath")]
    pub file_path: String,
    pub violations: Vec<SqlfluffMessage>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SqlfluffMessage {
    pub name: String,
    pub code: String,
    pub description: String,
    pub warning: bool,
    pub start_line_no: u32,
    pub start_line_pos: u32,
    pub end_line_no: Option<u32>,
    pub end_line_pos: Option<u32>,
    fixes: Vec<SqlfluffFix>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct SqlfluffFix {
    edit: String,
    start_line_no: u32,
    start_line_pos: u32,
    start_file_pos: u32,
    end_line_no: u32,
    end_line_pos: u32,
    end_file_pos: u32,
}

#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct Sqlfluff {}

impl Parser for Sqlfluff {
    fn parse(&self, _plugin_name: &str, output: &str) -> Result<Vec<Issue>> {
        let mut issues = vec![];
        let files: Vec<SqlfluffFile> = serde_json::from_str(output)?;

        for file in files {
            for violation in file.violations {
                let suggestions = self.build_suggestions(&violation, file.file_path.clone());

                let issue = Issue {
                    tool: "sqlfluff".into(),
                    message: violation.description,
                    category: Category::Lint.into(),
                    level: severity_to_level(violation.warning).into(),
                    rule_key: violation.code,
                    suggestions,
                    location: Some(Location {
                        path: file.file_path.clone(),
                        range: Some(Range {
                            start_line: violation.start_line_no,
                            start_column: violation.start_line_pos,
                            end_line: violation.end_line_no.unwrap_or(violation.start_line_no),
                            end_column: violation.end_line_pos.unwrap_or(violation.start_line_pos),
                            ..Default::default()
                        }),
                    }),
                    ..Default::default()
                };

                issues.push(issue);
            }
        }

        Ok(issues)
    }
}

impl Sqlfluff {
    fn build_suggestions(&self, message: &SqlfluffMessage, path: String) -> Vec<Suggestion> {
        let mut replacements = vec![];

        for fix in &message.fixes {
            let replacement = Replacement {
                data: fix.edit.clone(),
                location: Some(Location {
                    path: path.clone(),
                    range: Some(Range {
                        start_line: fix.start_line_no,
                        start_column: fix.start_line_pos,
                        start_byte: Some(fix.start_file_pos),
                        end_line: fix.end_line_no,
                        end_column: fix.end_line_pos,
                        end_byte: Some(fix.end_file_pos),
                    }),
                }),
            };

            replacements.push(replacement);
        }

        if replacements.is_empty() {
            vec![]
        } else {
            vec![Suggestion {
                source: SuggestionSource::Tool.into(),
                replacements,
                ..Default::default()
            }]
        }
    }
}

fn severity_to_level(warning: bool) -> Level {
    if warning {
        Level::Low
    } else {
        Level::Medium
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn parse() {
        let input = r###"
        [
        {
            "filepath": "/Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql",
            "violations": [
            {
                "start_line_no": 3,
                "start_line_pos": 1,
                "code": "LT02",
                "description": "Expected indent of 4 spaces.",
                "name": "layout.indent",
                "warning": false,
                "fixes": [
                {
                    "type": "replace",
                    "edit": "    ",
                    "start_line_no": 3,
                    "start_line_pos": 1,
                    "start_file_pos": 18,
                    "end_line_no": 3,
                    "end_line_pos": 7,
                    "end_file_pos": 24
                }
                ],
                "start_file_pos": 18,
                "end_line_no": 3,
                "end_line_pos": 7,
                "end_file_pos": 24
            },
            {
                "start_line_no": 4,
                "start_line_pos": 13,
                "code": "LT01",
                "description": "Expected only single space before 'AS' keyword. Found '   '.",
                "name": "layout.spacing",
                "warning": false,
                "fixes": [
                {
                    "type": "replace",
                    "edit": " ",
                    "start_line_no": 4,
                    "start_line_pos": 13,
                    "start_file_pos": 43,
                    "end_line_no": 4,
                    "end_line_pos": 16,
                    "end_file_pos": 46
                }
                ],
                "start_file_pos": 43,
                "end_line_no": 4,
                "end_line_pos": 16,
                "end_file_pos": 46
            },
            {
                "start_line_no": 4,
                "start_line_pos": 18,
                "code": "LT01",
                "description": "Expected only single space before naked identifier. Found '   '.",
                "name": "layout.spacing",
                "warning": false,
                "fixes": [
                {
                    "type": "replace",
                    "edit": " ",
                    "start_line_no": 4,
                    "start_line_pos": 18,
                    "start_file_pos": 48,
                    "end_line_no": 4,
                    "end_line_pos": 21,
                    "end_file_pos": 51
                }
                ],
                "start_file_pos": 48,
                "end_line_no": 4,
                "end_line_pos": 21,
                "end_file_pos": 51
            },
            {
                "start_line_no": 5,
                "start_line_pos": 13,
                "code": "LT01",
                "description": "Expected only single space before 'OVER' keyword. Found '   '.",
                "name": "layout.spacing",
                "warning": false,
                "fixes": [
                {
                    "type": "replace",
                    "edit": " ",
                    "start_line_no": 5,
                    "start_line_pos": 13,
                    "start_file_pos": 68,
                    "end_line_no": 5,
                    "end_line_pos": 16,
                    "end_file_pos": 71
                }
                ],
                "start_file_pos": 68,
                "end_line_no": 5,
                "end_line_pos": 16,
                "end_file_pos": 71
            },
            {
                "start_line_no": 5,
                "start_line_pos": 20,
                "code": "LT01",
                "description": "Expected only single space before start bracket '('. Found '   '.",
                "name": "layout.spacing",
                "warning": false,
                "fixes": [
                {
                    "type": "replace",
                    "edit": " ",
                    "start_line_no": 5,
                    "start_line_pos": 20,
                    "start_file_pos": 75,
                    "end_line_no": 5,
                    "end_line_pos": 23,
                    "end_file_pos": 78
                }
                ],
                "start_file_pos": 75,
                "end_line_no": 5,
                "end_line_pos": 23,
                "end_file_pos": 78
            }
            ],
            "statistics": {
            "source_chars": 186,
            "templated_chars": 186,
            "segments": 122,
            "raw_segments": 88
            },
            "timings": {
            "templating": 0.0007503749802708626,
            "lexing": 0.0012912499951198697,
            "parsing": 0.008845540985930711,
            "linting": 0.01774112501880154,
            "AL01": 0.0001051669823937118,
            "AL02": 7.691700011491776e-5,
            "AL03": 0.00011041603283956647,
            "AL04": 0.0002595830010250211,
            "AL05": 0.000645750027615577,
            "AL06": 4.7874986194074154e-5,
            "AL07": 1.4165998436510563e-5,
            "AL08": 4.3000036384910345e-5,
            "AL09": 5.216599674895406e-5,
            "AM01": 4.0624989196658134e-5,
            "AM02": 4.166970029473305e-6,
            "AM03": 9.458302520215511e-5,
            "AM04": 0.0002549159689806402,
            "AM05": 5.125009920448065e-6,
            "AM06": 0.00011904101120308042,
            "AM07": 1.975003397092223e-5,
            "CP01": 0.0002828749711625278,
            "CP02": 0.00024691701401025057,
            "CP03": 0.00010045798262581229,
            "CP04": 4.959001671522856e-6,
            "CP05": 4.084024112671614e-6,
            "CV01": 3.833032678812742e-6,
            "CV02": 6.562500493600965e-5,
            "CV03": 2.945796586573124e-5,
            "CV04": 7.358298171311617e-5,
            "CV05": 3.999972250312567e-6,
            "CV06": 9.124982170760632e-6,
            "CV07": 9.375042282044888e-6,
            "CV08": 3.7919962778687477e-6,
            "CV09": 0.0002174170222133398,
            "CV10": 3.4374999813735485e-5,
            "CV11": 6.324995774775743e-5,
            "JJ01": 5.334033630788326e-6,
            "LT01": 0.002557208004873246,
            "LT02": 0.001960250025149435,
            "LT03": 1.3042008504271507e-5,
            "LT04": 0.00011154200183227658,
            "LT05": 0.0015581660554744303,
            "LT06": 0.00012145802611485124,
            "LT07": 6.959016900509596e-6,
            "LT08": 4.62500611320138e-6,
            "LT09": 0.000258374959230423,
            "LT10": 3.825000021606684e-5,
            "LT11": 5.04200579598546e-6,
            "LT12": 4.095799522474408e-5,
            "LT13": 1.3749988283962011e-5,
            "RF01": 0.0004235419910401106,
            "RF02": 0.00023512501502409577,
            "RF03": 0.0002882080152630806,
            "RF04": 0.0002622079919092357,
            "RF05": 0.0001984169939532876,
            "RF06": 0.00027966697234660387,
            "ST01": 5.791953299194574e-6,
            "ST02": 4.375004209578037e-6,
            "ST03": 4.04199818149209e-6,
            "ST04": 3.832974471151829e-6,
            "ST05": 0.0006697499775327742,
            "ST06": 7.162499241530895e-5,
            "ST07": 5.62501372769475e-6,
            "ST08": 0.00010416604345664382,
            "ST09": 3.2917014323174953e-5,
            "TQ01": 4.500034265220165e-6
            }
        }]
        "###;

        let issues = Sqlfluff::default().parse("sqlfluff", input);
        insta::assert_yaml_snapshot!(issues.unwrap(), @r#"
        - tool: sqlfluff
          ruleKey: LT02
          message: Expected indent of 4 spaces.
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
            range:
              startLine: 3
              startColumn: 1
              endLine: 3
              endColumn: 7
          suggestions:
            - source: SUGGESTION_SOURCE_TOOL
              replacements:
                - data: "    "
                  location:
                    path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
                    range:
                      startLine: 3
                      startColumn: 1
                      endLine: 3
                      endColumn: 7
                      startByte: 18
                      endByte: 24
        - tool: sqlfluff
          ruleKey: LT01
          message: "Expected only single space before 'AS' keyword. Found '   '."
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
            range:
              startLine: 4
              startColumn: 13
              endLine: 4
              endColumn: 16
          suggestions:
            - source: SUGGESTION_SOURCE_TOOL
              replacements:
                - data: " "
                  location:
                    path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
                    range:
                      startLine: 4
                      startColumn: 13
                      endLine: 4
                      endColumn: 16
                      startByte: 43
                      endByte: 46
        - tool: sqlfluff
          ruleKey: LT01
          message: "Expected only single space before naked identifier. Found '   '."
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
            range:
              startLine: 4
              startColumn: 18
              endLine: 4
              endColumn: 21
          suggestions:
            - source: SUGGESTION_SOURCE_TOOL
              replacements:
                - data: " "
                  location:
                    path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
                    range:
                      startLine: 4
                      startColumn: 18
                      endLine: 4
                      endColumn: 21
                      startByte: 48
                      endByte: 51
        - tool: sqlfluff
          ruleKey: LT01
          message: "Expected only single space before 'OVER' keyword. Found '   '."
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
            range:
              startLine: 5
              startColumn: 13
              endLine: 5
              endColumn: 16
          suggestions:
            - source: SUGGESTION_SOURCE_TOOL
              replacements:
                - data: " "
                  location:
                    path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
                    range:
                      startLine: 5
                      startColumn: 13
                      endLine: 5
                      endColumn: 16
                      startByte: 68
                      endByte: 71
        - tool: sqlfluff
          ruleKey: LT01
          message: "Expected only single space before start bracket '('. Found '   '."
          level: LEVEL_MEDIUM
          category: CATEGORY_LINT
          location:
            path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
            range:
              startLine: 5
              startColumn: 20
              endLine: 5
              endColumn: 23
          suggestions:
            - source: SUGGESTION_SOURCE_TOOL
              replacements:
                - data: " "
                  location:
                    path: /Users/arslan/work/code_climate/plugins/linters/sqlfluff/fixtures/basic_fmt.in.sql
                    range:
                      startLine: 5
                      startColumn: 20
                      endLine: 5
                      endColumn: 23
                      startByte: 75
                      endByte: 78
        "#);
    }
}
