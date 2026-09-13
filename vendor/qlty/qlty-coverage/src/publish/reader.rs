use crate::formats::{parser_for, Formats};
use crate::publish::{Plan, Results};
use anyhow::bail;
use anyhow::Result;
use std::path::PathBuf;
use std::str::FromStr;

#[derive(Debug, Clone)]
pub struct Reader {
    plan: Plan,
}

impl Reader {
    pub fn new(plan: &Plan) -> Self {
        Self {
            plan: plan.to_owned(),
        }
    }

    pub fn read(&self) -> Result<Results> {
        let mut file_coverages = vec![];
        let mut report_files = vec![];

        for report_file in &self.plan.report_files {
            let path = PathBuf::from(&report_file.path);

            if !path.exists() {
                bail!("Coverage report file not found: {}", path.display());
            }

            let format = Formats::from_str(&report_file.format)?;
            let parser = parser_for(&format);

            let coverages = parser.parse_file(&path)?;
            file_coverages.extend(coverages);
            report_files.push(report_file.clone());
        }

        Ok(Results {
            report_files,
            file_coverages,
        })
    }
}
