use anyhow::{anyhow, bail, Result};
use std::path::PathBuf;

pub mod fs;

pub fn filename_to_language(filename: &str) -> Result<String> {
    if filename.starts_with("Dockerfile") {
        return Ok("dockerfile".to_string());
    }

    let path_buf = PathBuf::from(filename);
    let file_extension = path_buf
        .extension()
        .ok_or_else(|| anyhow!("Failed to get file extension"))?
        .to_str()
        .ok_or_else(|| anyhow!("Failed to convert file extension to string"))?;

    match file_extension {
        "rs" => Ok("rust".to_string()),
        "rb" => Ok("ruby".to_string()),
        "sh" => Ok("shell".to_string()),
        "py" => Ok("python".to_string()),
        "php" => Ok("php".to_string()),
        "css" => Ok("css".to_string()),
        "js" => Ok("javascript".to_string()),
        "mjs" => Ok("javascript".to_string()),
        "cjs" => Ok("javascript".to_string()),
        "jsx" => Ok("javascript".to_string()),
        "ts" => Ok("typescript".to_string()),
        "mts" => Ok("typescript".to_string()),
        "cts" => Ok("typescript".to_string()),
        "tsx" => Ok("typescript".to_string()),
        "mtsx" => Ok("typescript".to_string()),
        "ctsx" => Ok("typescript".to_string()),
        "go" => Ok("go".to_string()),
        "java" => Ok("java".to_string()),
        _ => bail!("Unsupported file extension: {}", file_extension),
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn test_filename_to_language() {
        assert_eq!(filename_to_language("Dockerfile").unwrap(), "dockerfile");
    }

    #[test]
    fn test_extension_to_language() {
        assert_eq!(filename_to_language("main.rs").unwrap(), "rust");
        assert_eq!(filename_to_language("main.rb").unwrap(), "ruby");
        assert_eq!(filename_to_language("main.sh").unwrap(), "shell");
        assert_eq!(filename_to_language("main.py").unwrap(), "python");
        assert_eq!(filename_to_language("main.css").unwrap(), "css");
        assert_eq!(filename_to_language("main.js").unwrap(), "javascript");
        assert_eq!(filename_to_language("main.mjs").unwrap(), "javascript");
        assert_eq!(filename_to_language("main.cjs").unwrap(), "javascript");
        assert_eq!(filename_to_language("main.jsx").unwrap(), "javascript");
        assert_eq!(filename_to_language("main.ts").unwrap(), "typescript");
        assert_eq!(filename_to_language("main.mts").unwrap(), "typescript");
        assert_eq!(filename_to_language("main.cts").unwrap(), "typescript");
        assert_eq!(filename_to_language("main.tsx").unwrap(), "typescript");
        assert_eq!(filename_to_language("main.mtsx").unwrap(), "typescript");
        assert_eq!(filename_to_language("main.ctsx").unwrap(), "typescript");
        assert_eq!(filename_to_language("main.go").unwrap(), "go");
        assert_eq!(filename_to_language("main.java").unwrap(), "java");
        assert!(filename_to_language("main").is_err());
    }

    #[test]
    fn test_unknown_file() {
        assert!(filename_to_language("main").is_err());
    }
}
