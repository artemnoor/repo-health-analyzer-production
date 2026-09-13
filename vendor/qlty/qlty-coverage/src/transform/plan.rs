use crate::Transformer;
use qlty_types::tests::v1::ReportFile;

#[derive(Debug, Clone, Default)]
pub struct Plan {
    pub report_file: ReportFile,
    pub transformers: Vec<Box<dyn Transformer>>,
}
