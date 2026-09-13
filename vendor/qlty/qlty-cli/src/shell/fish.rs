use super::{TabCompletingShell, TabCompletions};
use clap_complete::Shell;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Fish;

impl TabCompletingShell for Fish {
    fn completions_filename(&self, completions: &TabCompletions) -> PathBuf {
        PathBuf::from(format!("{}.fish", completions.bin_name))
    }

    fn completions_directory(&self) -> Option<PathBuf> {
        if let Ok(config_dir) = std::env::var("XDG_CONFIG_HOME") {
            let completions_dir = PathBuf::from(config_dir).join("fish/completions");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        if let Ok(data_dir) = std::env::var("XDG_DATA_HOME") {
            let completions_dir = PathBuf::from(data_dir).join("fish/completions");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        if let Ok(home_dir) = std::env::var("HOME") {
            let completions_dir = PathBuf::from(home_dir).join(".config/fish/completions");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        if std::env::consts::OS == "macos" {
            let dir = if std::env::consts::ARCH == "aarch64" {
                "/opt/homebrew/share/fish/completions"
            } else {
                "/usr/local/share/fish/completions"
            };

            let completions_dir = PathBuf::from(dir);

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        let completions_dir = PathBuf::from("/etc/fish/completions");
        if std::fs::read_dir(&completions_dir).is_ok() {
            return Some(completions_dir);
        }

        None
    }

    fn clap_shell(&self) -> Shell {
        Shell::Fish
    }
}
