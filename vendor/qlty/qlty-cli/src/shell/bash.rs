use super::{TabCompletingShell, TabCompletions};
use clap_complete::Shell;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Bash;

impl TabCompletingShell for Bash {
    fn completions_filename(&self, completions: &TabCompletions) -> PathBuf {
        PathBuf::from(format!("{}.completion.bash", completions.bin_name))
    }

    fn completions_directory(&self) -> Option<PathBuf> {
        if let Ok(data_dir) = std::env::var("XDG_DATA_HOME") {
            let completions_dir = PathBuf::from(data_dir).join("bash-completion/completions");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        if let Ok(config_dir) = std::env::var("XDG_CONFIG_HOME") {
            let completions_dir = PathBuf::from(config_dir).join("bash-completion/completions");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        if let Ok(home_dir) = std::env::var("HOME") {
            let completions_dir = PathBuf::from(home_dir.clone()).join(".oh-my-bash/completions");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }

            let completions_dir = PathBuf::from(home_dir).join(".bash_completion.d");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        let dirs_to_try = [
            "/opt/homebrew/share/bash-completion/completions/",
            "/opt/local/share/bash-completion/completions/",
        ];

        for dir in &dirs_to_try {
            let completions_dir = PathBuf::from(dir);

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        None
    }

    fn clap_shell(&self) -> Shell {
        Shell::Bash
    }
}
