#[derive(Debug, Default, Clone)]
pub struct ExecResult {
    pub exit_code: Option<i64>,
    pub stdout: String,
    pub stderr: String,
}

impl ExecResult {
    pub fn from_process_output(output: &std::process::Output) -> Self {
        Self {
            exit_code: output.status.code().map(|c| c as i64),
            stdout: String::from_utf8_lossy(&output.stdout).to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        }
    }
}
