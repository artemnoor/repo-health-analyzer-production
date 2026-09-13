use crate::formats::{parser_for, Formats};
use crate::transform::Plan;
use anyhow::{bail, Result};
use qlty_types::tests::v1::FileCoverage;
use std::path::PathBuf;
use std::str::FromStr;

pub struct Processor {
    plan: Plan,
}

impl Processor {
    pub fn new(plan: &Plan) -> Self {
        Self { plan: plan.clone() }
    }

    pub fn compute(&self) -> Result<Vec<FileCoverage>> {
        // let mut file_coverages = vec![];
        let report_file_path = PathBuf::from(&self.plan.report_file.path);

        if !report_file_path.exists() {
            bail!(
                "Coverage report file not found: {}",
                report_file_path.display()
            );
        }

        let format = Formats::from_str(&self.plan.report_file.format)?;
        let parser = parser_for(&format);
        let file_coverages = parser.parse_file(&report_file_path)?;

        let result = file_coverages
            .iter()
            .filter_map(|file_coverage| self.transform(file_coverage.to_owned()))
            .collect::<Vec<_>>();

        Ok(result)
    }

    fn transform(&self, file_coverage: FileCoverage) -> Option<FileCoverage> {
        let mut file_coverage: Option<FileCoverage> = Some(file_coverage.clone());

        for transformer in self.plan.transformers.iter() {
            if file_coverage.is_some() {
                file_coverage = transformer.transform(file_coverage.unwrap());
            } else {
                return None;
            }
        }

        file_coverage
    }
}
