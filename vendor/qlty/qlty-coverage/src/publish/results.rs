use qlty_types::tests::v1::{FileCoverage, ReportFile};

#[derive(Debug, Clone, Default)]
pub struct Results {
    pub report_files: Vec<ReportFile>,
    pub file_coverages: Vec<FileCoverage>,
}
