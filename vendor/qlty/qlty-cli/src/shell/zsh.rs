use super::{TabCompletingShell, TabCompletions};
use anyhow::Result;
use clap_complete::Shell;
use qlty_analysis::utils::fs::path_to_string;
use std::io::Write;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug)]
pub struct Zsh;

impl TabCompletingShell for Zsh {
    fn completions_filename(&self, completions: &TabCompletions) -> PathBuf {
        PathBuf::from(format!("_{}", completions.bin_name))
    }

    fn completions_directory(&self) -> Option<PathBuf> {
        if let Ok(fpath) = std::env::var("fpath") {
            for dir in fpath.split_whitespace() {
                let completions_dir = PathBuf::from(dir);

                if std::fs::read_dir(&completions_dir).is_ok() {
                    return Some(completions_dir);
                }
            }
        }

        if let Ok(data_dir) = std::env::var("XDG_DATA_HOME") {
            let completions_dir = PathBuf::from(data_dir).join("zsh-completions");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        if let Ok(home_dir) = std::env::var("HOME") {
            let completions_dir = PathBuf::from(home_dir).join(".oh-my-zsh/completions");

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        let dirs_to_try = [
            "/usr/local/share/zsh/site-functions",
            "/usr/local/share/zsh/completions",
            "/opt/homebrew/share/zsh/completions",
            "/opt/homebrew/share/zsh/site-functions",
        ];

        for dir in &dirs_to_try {
            let completions_dir = PathBuf::from(dir);

            if std::fs::read_dir(&completions_dir).is_ok() {
                return Some(completions_dir);
            }
        }

        None
    }

    fn update_rc(&self, completions_path: &Path) -> Result<()> {
        let completions_filename = completions_path.file_name().unwrap();

        if let Ok(home_dir) = std::env::var("HOME") {
            let oh_my_zsh_completions_path = PathBuf::from(home_dir)
                .join(".oh-my-zsh/completions")
                .join(completions_filename);

            // If we installed completions into ~/.oh-my-zsh/completions
            // we assume that directory is automaticallt sources and we do
            // not need to update .zshrc
            if completions_path == oh_my_zsh_completions_path {
                return Ok(());
            }
        }

        let remind_user_to_add_completions_file = match zshrc_path() {
            Some(zshrc_filepath) => {
                if let Ok(zshrc_contents) = std::fs::read_to_string(&zshrc_filepath) {
                    if zshrc_contents.contains(&path_to_string(completions_path)) {
                        false
                    } else {
                        let mut dot_zshrc = std::fs::OpenOptions::new()
                            .append(true)
                            .open(&zshrc_filepath)?;

                        writeln!(
                            dot_zshrc,
                            "\n# qlty completions\n[ -s \"{}\" ] && source \"{}\"",
                            completions_path.display(),
                            completions_path.display()
                        )?;
                        eprintln!(
                            "Enabled loading qlty's completions in {}",
                            zshrc_filepath.display()
                        );
                        false
                    }
                } else {
                    eprintln!(
                        "Could not read {} to enable loading qlty's completions",
                        zshrc_filepath.display()
                    );
                    true
                }
            }
            None => true,
        };

        if remind_user_to_add_completions_file {
            eprintln!(
            "To enable completions, add this to your .zshrc:\n      [ -s \"{}\" ] && source \"{}\"",
            completions_path.display(),
            completions_path.display()
        );
        }

        Ok(())
    }

    fn clap_shell(&self) -> Shell {
        Shell::Zsh
    }
}

fn zshrc_path() -> Option<PathBuf> {
    let env_vars = ["ZDOTDIR", "HOME"];
    let filenames = [".zshrc", ".zshenv"];

    for env_var_name in &env_vars {
        if let Ok(path) = std::env::var(env_var_name) {
            let base = PathBuf::from(path);

            for filename in &filenames {
                let candidate = base.join(filename);

                if candidate.exists() {
                    return Some(candidate);
                }
            }
        }
    }

    None
}
